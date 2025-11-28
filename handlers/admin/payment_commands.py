# handlers/admin/payment_commands.py
"""
Payment approval/rejection handlers for admin module.

Callbacks:
    approve_payment_{id}  - First step: show confirmation
    final_approve_{id}    - Second step: execute transaction
    reject_payment_{id}   - Reject payment
    cancel_approval       - Cancel approval flow

Commands:
    &check / &checkpayments - Check pending payments

Templates used:
    admin_payment_confirm_action
    admin_payment_approved
    admin_payment_rejected
    admin_payment_wrong_status
    user_payment_approved
    user_payment_rejected
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from core.templates import MessageTemplates
from models.user import User
from models.payment import Payment
from models.active_balance import ActiveBalance
from models.notification import Notification

logger = logging.getLogger(__name__)

payment_router = Router(name="admin_payment")


# =============================================================================
# ADMIN CHECK
# =============================================================================

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    from config import Config
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    return user_id in admins


# =============================================================================
# HELPER: Create User Notification
# =============================================================================

async def create_user_payment_notification(
        payment: Payment,
        payer: User,
        is_approved: bool,
        session: Session
) -> Notification:
    """Create notification for user about payment approval/rejection."""
    template_key = 'user_payment_approved' if is_approved else 'user_payment_rejected'

    text, buttons = await MessageTemplates.get_raw_template(
        template_key,
        {
            'payment_id': payment.paymentID,
            'payment_date': payment.createdAt.strftime('%Y-%m-%d %H:%M:%S') if payment.createdAt else '',
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
# CALLBACK: Initial Approval
# =============================================================================

@payment_router.callback_query(F.data.startswith('approve_payment_'))
async def handle_initial_approval(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """First step of payment approval - show confirmation dialog."""
    if not is_admin(callback_query.from_user.id):
        return

    try:
        payment_id = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {callback_query.data}")
        return

    logger.info(f"Admin {user.userID} initiating approval for payment {payment_id}")

    payment = session.query(Payment).filter_by(paymentID=payment_id).first()

    if not payment:
        return

    if payment.status != "check":
        await message_manager.send_template(
            user=user,
            template_key='admin_payment_wrong_status',
            variables={'payment_id': payment_id, 'status': payment.status},
            update=callback_query,
            edit=True
        )
        return

    await message_manager.send_template(
        user=user,
        template_key='admin_payment_confirm_action',
        variables={'payment_id': payment_id, 'action': 'approve'},
        update=callback_query,
        edit=True
    )


# =============================================================================
# CALLBACK: Final Approval
# =============================================================================

@payment_router.callback_query(F.data.startswith('final_approve_'))
async def handle_final_approval(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Final payment approval - execute transaction."""
    if not is_admin(callback_query.from_user.id):
        return

    try:
        payment_id = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {callback_query.data}")
        return

    logger.info(f"Admin {user.userID} executing final approval for payment {payment_id}")

    try:
        session.begin_nested()

        payment = session.query(Payment).filter_by(paymentID=payment_id).with_for_update().first()
        if not payment:
            return

        if payment.status != "check":
            session.rollback()
            await message_manager.send_template(
                user=user,
                template_key='admin_payment_wrong_status',
                variables={'payment_id': payment_id, 'status': payment.status},
                update=callback_query,
                edit=True
            )
            return

        payer = session.query(User).filter_by(userID=payment.userID).with_for_update().first()
        if not payer:
            session.rollback()
            logger.error(f"User not found for payment {payment_id}")
            return

        # Transaction
        active_balance_record = ActiveBalance(
            userID=payer.userID,
            firstname=payer.firstname,
            surname=payer.surname,
            amount=Decimal(str(payment.amount)),
            status='done',
            reason=f'payment={payment_id}',
            link='',
            notes=f'Payment approved by admin {user.userID} ({user.firstname})',
            ownerTelegramID=payer.telegramID,
            ownerEmail=payer.email or ''
        )
        session.add(active_balance_record)

        payer.balanceActive = (payer.balanceActive or Decimal("0")) + Decimal(str(payment.amount))
        payment.status = "confirmed"
        payment.confirmedBy = str(callback_query.from_user.id)
        payment.confirmationTime = datetime.now(timezone.utc)

        await create_user_payment_notification(payment, payer, is_approved=True, session=session)

        session.commit()

        logger.info(f"Payment {payment_id} approved: user={payer.userID}, amount={payment.amount}")

        await message_manager.send_template(
            user=user,
            template_key='admin_payment_approved',
            variables={
                'payment_id': payment_id,
                'user_name': payer.firstname,
                'user_id': payer.userID,
                'amount': payment.amount,
                'new_balance': payer.balanceActive
            },
            update=callback_query,
            edit=True
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Error approving payment {payment_id}: {e}", exc_info=True)


# =============================================================================
# CALLBACK: Rejection
# =============================================================================

@payment_router.callback_query(F.data.startswith('reject_payment_'))
async def handle_rejection(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Reject payment."""
    if not is_admin(callback_query.from_user.id):
        return

    try:
        payment_id = int(callback_query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"Invalid callback data: {callback_query.data}")
        return

    logger.info(f"Admin {user.userID} rejecting payment {payment_id}")

    try:
        session.begin_nested()

        payment = session.query(Payment).filter_by(paymentID=payment_id).with_for_update().first()
        if not payment:
            return

        if payment.status not in ["check", "pending"]:
            session.rollback()
            await message_manager.send_template(
                user=user,
                template_key='admin_payment_wrong_status',
                variables={'payment_id': payment_id, 'status': payment.status},
                update=callback_query,
                edit=True
            )
            return

        payer = session.query(User).filter_by(userID=payment.userID).first()
        if not payer:
            session.rollback()
            logger.error(f"User not found for payment {payment_id}")
            return

        payment.status = "failed"
        payment.confirmedBy = str(callback_query.from_user.id)
        payment.confirmationTime = datetime.now(timezone.utc)

        await create_user_payment_notification(payment, payer, is_approved=False, session=session)

        session.commit()

        logger.info(f"Payment {payment_id} rejected by admin {user.userID}")

        await message_manager.send_template(
            user=user,
            template_key='admin_payment_rejected',
            variables={
                'payment_id': payment_id,
                'user_name': payer.firstname,
                'user_id': payer.userID
            },
            update=callback_query,
            edit=True
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Error rejecting payment {payment_id}: {e}", exc_info=True)


# =============================================================================
# CALLBACK: Cancel
# =============================================================================

@payment_router.callback_query(F.data == 'cancel_approval')
async def handle_cancel_approval(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Cancel approval flow."""
    if not is_admin(callback_query.from_user.id):
        return

    logger.info(f"Admin {user.userID} cancelled approval flow")

    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.warning(f"Could not delete message: {e}")


# =============================================================================
# COMMAND: &check / &checkpayments
# =============================================================================

@payment_router.message(F.text.regexp(r'^&check(payments)?$'))
async def cmd_checkpayments(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Check pending payments and recreate admin notifications."""
    if not is_admin(message.from_user.id):
        return

    from handlers.payments import create_payment_check_notification

    logger.info(f"Admin {message.from_user.id} triggered &checkpayments")

    # Use template for loading state
    status_msg = await message_manager.send_template(
        user=user,
        template_key='admin/check/loading',
        update=message
    )

    try:
        pending_payments = session.query(Payment).filter_by(status="check").all()
        total_amount = session.query(func.sum(Payment.amount)).filter_by(status="check").scalar() or 0

        if not pending_payments:
            await message_manager.send_template(
                user=user,
                template_key='admin/check/no_pending',
                update=status_msg,
                edit=True
            )
            return

        # Delete old notifications
        for payment in pending_payments:
            existing = session.query(Notification).filter(
                Notification.source == "payment_checker",
                Notification.text.like(f"%payment_id: {payment.paymentID}%")
            ).all()
            for notif in existing:
                session.delete(notif)
        session.commit()

        # Create new notifications
        notifications_created = 0
        for payment in pending_payments:
            payer = session.query(User).filter_by(userID=payment.userID).first()
            if not payer:
                continue
            try:
                await create_payment_check_notification(payment, payer, session)
                notifications_created += 1
            except Exception as e:
                logger.error(f"Error creating notification for payment {payment.paymentID}: {e}")

        await message_manager.send_template(
            user=user,
            template_key='admin/check/report',
            variables={
                'count': len(pending_payments),
                'total_amount': f"{float(total_amount):,.2f}",
                'notifications_created': notifications_created
            },
            update=status_msg,
            edit=True
        )

    except Exception as e:
        logger.error(f"Error in &checkpayments: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/check/error',
            variables={'error': str(e)},
            update=status_msg,
            edit=True
        )


__all__ = ['payment_router']