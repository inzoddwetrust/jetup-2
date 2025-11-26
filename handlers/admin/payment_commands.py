# handlers/admin/payment_commands.py
"""
Payment approval/rejection handlers for admin module.

Callbacks:
    approve_payment_{id}  - First step: show confirmation
    final_approve_{id}    - Second step: execute transaction
    reject_payment_{id}   - Reject payment
    cancel_approval       - Cancel approval flow
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from core.templates import MessageTemplates
from models.user import User
from models.payment import Payment
from models.active_balance import ActiveBalance
from models.notification import Notification

logger = logging.getLogger(__name__)

# =============================================================================
# ROUTER SETUP
# =============================================================================

payment_router = Router(name="admin_payment")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

async def create_user_payment_notification(
        payment: Payment,
        payer: User,
        is_approved: bool,
        session: Session
) -> Notification:
    """
    Create notification for user about payment approval/rejection.

    Args:
        payment: Payment object
        payer: User who made the payment
        is_approved: True if approved, False if rejected
        session: Database session

    Returns:
        Notification object (already added to session)
    """
    template_key = 'user_payment_approved' if is_approved else 'user_payment_rejected'

    text, buttons = await MessageTemplates.get_raw_template(
        template_key,
        {
            'payment_id': payment.paymentID,
            'payment_date': payment.createdAt.strftime('%Y-%m-%d %H:%M:%S'),
            'amount': payment.amount,
            'balance': payer.balanceActive,
            'txid': payment.txid
        },
        lang=payer.lang or 'en'
    )

    notification = Notification(
        source="payment_processor",
        text=text,
        buttons=buttons,
        targetType="user",
        targetValue=str(payer.userID),
        priority=2,
        category="payment",
        importance="high",
        parseMode="HTML"
    )

    session.add(notification)
    return notification


# =============================================================================
# CALLBACK HANDLERS
# =============================================================================

@payment_router.callback_query(F.data.startswith('approve_payment_'))
async def handle_initial_approval(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    First step of payment approval - show confirmation dialog.

    Flow:
        1. Extract payment_id from callback data
        2. Verify payment exists and status == "check"
        3. Show confirmation message with final_approve button

    Callback data format: approve_payment_{payment_id}
    """
    # Extract payment ID
    try:
        payment_id = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {callback_query.data}")
        await callback_query.answer("Invalid payment ID", show_alert=True)
        return

    logger.info(f"Admin {user.userID} initiating approval for payment {payment_id}")

    # Get payment
    payment = session.query(Payment).filter_by(paymentID=payment_id).first()

    if not payment:
        await callback_query.answer("Payment not found", show_alert=True)
        return

    # Check payment status
    if payment.status != "check":
        # Payment already processed
        text, media_id, keyboard, parse_mode, disable_preview, _, _ = await MessageTemplates.generate_screen(
            user,
            'admin_payment_wrong_status',
            {
                'payment_id': payment_id,
                'status': payment.status
            }
        )

        await callback_query.message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
            disable_web_page_preview=disable_preview
        )
        await callback_query.answer("Payment already processed", show_alert=True)
        return

    # Show confirmation dialog
    text, media_id, keyboard, parse_mode, disable_preview, _, _ = await MessageTemplates.generate_screen(
        user,
        'admin_payment_confirm_action',
        {
            'payment_id': payment_id,
            'action': 'approve'
        }
    )

    await callback_query.message.edit_text(
        text=text,
        parse_mode=parse_mode,
        reply_markup=keyboard,
        disable_web_page_preview=disable_preview
    )

    await callback_query.answer()


@payment_router.callback_query(F.data.startswith('final_approve_'))
async def handle_final_approval(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Final payment approval - execute transaction.

    Transaction:
        1. Create ActiveBalance record (+amount, status='done')
        2. Update user.balanceActive += amount
        3. Update payment.status = 'paid'
        4. Set payment.confirmedBy and confirmationTime
        5. Create notification for user
        6. Commit transaction

    Callback data format: final_approve_{payment_id}
    """
    # Extract payment ID
    try:
        payment_id = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {callback_query.data}")
        await callback_query.answer("Invalid payment ID", show_alert=True)
        return

    logger.info(f"Admin {user.userID} executing final approval for payment {payment_id}")

    try:
        # Start nested transaction (savepoint)
        session.begin_nested()

        # Get payment with row lock
        payment = session.query(Payment).filter_by(
            paymentID=payment_id
        ).with_for_update().first()

        if not payment:
            await callback_query.answer("Payment not found", show_alert=True)
            return

        # Verify status hasn't changed
        if payment.status != "check":
            session.rollback()

            text, media_id, keyboard, parse_mode, disable_preview, _, _ = await MessageTemplates.generate_screen(
                user,
                'admin_payment_wrong_status',
                {
                    'payment_id': payment_id,
                    'status': payment.status
                }
            )

            await callback_query.message.edit_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=keyboard,
                disable_web_page_preview=disable_preview
            )
            await callback_query.answer("Payment already processed", show_alert=True)
            return

        # Get payer with row lock
        payer = session.query(User).filter_by(
            userID=payment.userID
        ).with_for_update().first()

        if not payer:
            session.rollback()
            logger.error(f"User not found for payment {payment_id}")
            await callback_query.answer("User not found", show_alert=True)
            return

        # =====================================================================
        # TRANSACTION: Approve payment
        # =====================================================================

        # 1. Create ActiveBalance record
        active_balance_record = ActiveBalance(
            userID=payer.userID,
            firstname=payer.firstname,
            surname=payer.surname,
            amount=Decimal(str(payment.amount)),
            status='done',
            reason=f'payment={payment_id}',
            link='',
            notes=f'Payment approved by admin {user.userID} ({user.firstname})'
        )
        session.add(active_balance_record)

        # 2. Update user balance
        payer.balanceActive = (payer.balanceActive or Decimal("0")) + Decimal(str(payment.amount))

        # 3. Update payment status
        payment.status = "paid"
        payment.confirmedBy = str(callback_query.from_user.id)
        payment.confirmationTime = datetime.now(timezone.utc)

        # 4. Create notification for user
        await create_user_payment_notification(
            payment, payer, is_approved=True, session=session
        )

        # 5. Commit transaction
        session.commit()

        logger.info(
            f"Payment {payment_id} approved: "
            f"user={payer.userID}, amount={payment.amount}, "
            f"new_balance={payer.balanceActive}"
        )

        # =====================================================================
        # Update admin message
        # =====================================================================

        text, media_id, keyboard, parse_mode, disable_preview, _, _ = await MessageTemplates.generate_screen(
            user,
            'admin_payment_approved',
            {
                'payment_id': payment_id,
                'user_name': payer.firstname,
                'user_id': payer.userID,
                'amount': payment.amount,
                'new_balance': payer.balanceActive
            }
        )

        await callback_query.message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
            disable_web_page_preview=disable_preview
        )

        await callback_query.answer("✅ Payment approved", show_alert=False)

    except Exception as e:
        session.rollback()
        logger.error(f"Error approving payment {payment_id}: {e}", exc_info=True)
        await callback_query.answer(f"Error: {str(e)}", show_alert=True)


@payment_router.callback_query(F.data.startswith('reject_payment_'))
async def handle_rejection(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Reject payment.

    Transaction:
        1. Update payment.status = 'failed'
        2. Set payment.confirmedBy (for audit trail)
        3. Create notification for user
        4. Commit transaction

    Note: No balance changes needed for rejection.

    Callback data format: reject_payment_{payment_id}
    """
    # Extract payment ID
    try:
        payment_id = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {callback_query.data}")
        await callback_query.answer("Invalid payment ID", show_alert=True)
        return

    logger.info(f"Admin {user.userID} rejecting payment {payment_id}")

    try:
        # Start nested transaction
        session.begin_nested()

        # Get payment with row lock
        payment = session.query(Payment).filter_by(
            paymentID=payment_id
        ).with_for_update().first()

        if not payment:
            await callback_query.answer("Payment not found", show_alert=True)
            return

        # Check payment can be rejected (status in check or pending)
        if payment.status not in ["check", "pending"]:
            session.rollback()

            text, media_id, keyboard, parse_mode, disable_preview, _, _ = await MessageTemplates.generate_screen(
                user,
                'admin_payment_wrong_status',
                {
                    'payment_id': payment_id,
                    'status': payment.status
                }
            )

            await callback_query.message.edit_text(
                text=text,
                parse_mode=parse_mode,
                reply_markup=keyboard,
                disable_web_page_preview=disable_preview
            )
            await callback_query.answer("Payment already processed", show_alert=True)
            return

        # Get payer for notification
        payer = session.query(User).filter_by(userID=payment.userID).first()

        if not payer:
            session.rollback()
            logger.error(f"User not found for payment {payment_id}")
            await callback_query.answer("User not found", show_alert=True)
            return

        # =====================================================================
        # TRANSACTION: Reject payment
        # =====================================================================

        # 1. Update payment status
        payment.status = "failed"
        payment.confirmedBy = str(callback_query.from_user.id)
        payment.confirmationTime = datetime.now(timezone.utc)

        # 2. Create notification for user
        await create_user_payment_notification(
            payment, payer, is_approved=False, session=session
        )

        # 3. Commit transaction
        session.commit()

        logger.info(f"Payment {payment_id} rejected by admin {user.userID}")

        # =====================================================================
        # Update admin message
        # =====================================================================

        text, media_id, keyboard, parse_mode, disable_preview, _, _ = await MessageTemplates.generate_screen(
            user,
            'admin_payment_rejected',
            {
                'payment_id': payment_id,
                'user_name': payer.firstname,
                'user_id': payer.userID
            }
        )

        await callback_query.message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=keyboard,
            disable_web_page_preview=disable_preview
        )

        await callback_query.answer("❌ Payment rejected", show_alert=False)

    except Exception as e:
        session.rollback()
        logger.error(f"Error rejecting payment {payment_id}: {e}", exc_info=True)
        await callback_query.answer(f"Error: {str(e)}", show_alert=True)


@payment_router.callback_query(F.data == 'cancel_approval')
async def handle_cancel_approval(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Cancel approval flow - return to original notification.

    This is called when admin clicks "Cancel" on confirmation dialog.
    """
    logger.info(f"Admin {user.userID} cancelled approval flow")

    await callback_query.answer("Cancelled", show_alert=False)

    # Delete the confirmation message
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'payment_router',
    'handle_initial_approval',
    'handle_final_approval',
    'handle_rejection',
]