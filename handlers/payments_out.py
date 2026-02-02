# handlers/payments_out.py
"""
Withdrawal handlers - outgoing payments flow.
Allows users to withdraw funds from passive balance to TRC20 wallet.
"""
import logging
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from models.user import User
from models.payment import Payment
from models.notification import Notification
from core.message_manager import MessageManager
from core.templates import MessageTemplates
from states.fsm_states import WithdrawalState
from utils.wallet_validator import validate_trc20_address
from config import Config

logger = logging.getLogger(__name__)

payments_out_router = Router(name="payments_out_router")

# =============================================================================
# CONSTANTS
# =============================================================================

WITHDRAWAL_METHOD = "USDT-TRC20"


# =============================================================================
# HELPER: Create Admin Notification
# =============================================================================

async def create_outgoing_check_notification(
        payment: Payment,
        user: User,
        session: Session
) -> None:
    """
    Create notification for admins about new withdrawal request.

    Different from incoming payments:
    - Different template (check_outgoing vs check_incoming)
    - Different buttons (history, approve, reject)
    - Shows fee and total to send

    Args:
        payment: Payment record with direction='out', status='check'
        user: User who requested withdrawal
        session: Database session
    """
    admin_user_ids = Config.get(Config.ADMIN_USER_IDS) or []

    if not admin_user_ids:
        logger.error("No admin users configured!")
        raise ValueError("No admin users configured")

    # Calculate fee and total
    fee = Decimal(str(Config.get(Config.WITHDRAWAL_FEE, 1)))
    total_to_send = payment.amount - fee

    # Get template
    text, buttons = await MessageTemplates.get_raw_template(
        'admin/payment/check_outgoing',
        {
            'user_name': user.firstname or 'Unknown',
            'user_id': user.userID,
            'user_telegram_id': user.telegramID,
            'payment_id': payment.paymentID,
            'amount': float(payment.amount),
            'fee': float(fee),
            'total': float(total_to_send),
            'wallet': payment.toWallet,
            'created_at': payment.createdAt.strftime('%Y-%m-%d %H:%M') if payment.createdAt else '',
            'method': payment.method
        }
    )

    # Create notification for each admin
    for admin_id in admin_user_ids:
        notification = Notification(
            source="payment_checker",  # Same source as incoming - one table, one checker
            text=text,
            buttons=buttons,
            targetType="user",
            targetValue=str(admin_id),
            priority=2,
            parseMode="HTML",
            category="payment",
            importance="high"
        )
        session.add(notification)

    session.commit()
    logger.info(f"Created withdrawal notifications for {len(admin_user_ids)} admins, payment {payment.paymentID}")


# =============================================================================
# ENTRY POINT: Start Withdrawal
# =============================================================================

@payments_out_router.callback_query(F.data == "withdrawal")
async def withdrawal_start(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Start withdrawal flow.
    Check balance and show info screen.
    """
    logger.info(f"User {user.userID} started withdrawal flow")

    # Get config values
    min_amount = Decimal(str(Config.get(Config.WITHDRAWAL_MIN, 10)))
    fee = Decimal(str(Config.get(Config.WITHDRAWAL_FEE, 1)))
    balance = Decimal(str(user.balancePassive or 0))

    # Check minimum balance
    if balance < min_amount:
        logger.info(f"User {user.userID} insufficient balance: {balance} < {min_amount}")
        await message_manager.send_template(
            user=user,
            template_key='withdrawal/insufficient_balance',
            update=callback_query,
            variables={
                'balance': float(balance),
                'min_amount': float(min_amount)
            },
            delete_original=True
        )
        return

    # Show withdrawal info
    await message_manager.send_template(
        user=user,
        template_key='withdrawal/info',
        update=callback_query,
        variables={
            'balance': float(balance),
            'fee': float(fee),
            'min_amount': float(min_amount)
        },
        delete_original=True
    )


@payments_out_router.callback_query(F.data == "withdrawal_continue")
async def withdrawal_enter_wallet_prompt(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    User clicked 'Continue' - ask for wallet address.
    """
    logger.info(f"User {user.userID} proceeding to wallet input")

    # Set state
    await state.set_state(WithdrawalState.waiting_for_wallet)
    await state.update_data(user_id=user.userID)

    # Show wallet input prompt
    await message_manager.send_template(
        user=user,
        template_key='withdrawal/enter_wallet',
        update=callback_query,
        delete_original=True
    )


# =============================================================================
# STEP 1: Wallet Input
# =============================================================================

@payments_out_router.message(
    WithdrawalState.waiting_for_wallet,
    F.content_type == "text"
)
async def withdrawal_process_wallet(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Process wallet address input.
    Validate TRC20 format and proceed to amount input.
    """
    wallet = message.text.strip()

    logger.info(f"User {user.userID} entered wallet: {wallet[:10]}...")

    # Validate TRC20 address
    validation = validate_trc20_address(wallet)

    if not validation.is_valid:
        logger.info(f"Invalid wallet from user {user.userID}: {validation.code}")
        await message_manager.send_template(
            user=user,
            template_key='withdrawal/invalid_wallet',
            update=message,
            variables={
                'details': validation.details or ''
            }
        )
        # Stay in same state - user can retry
        return

    # Save wallet and proceed to amount
    await state.update_data(wallet=wallet)
    await state.set_state(WithdrawalState.waiting_for_amount)

    # Get balance for display
    min_amount = Decimal(str(Config.get(Config.WITHDRAWAL_MIN, 10)))
    fee = Decimal(str(Config.get(Config.WITHDRAWAL_FEE, 1)))
    balance = Decimal(str(user.balancePassive or 0))

    # Show amount input prompt
    await message_manager.send_template(
        user=user,
        template_key='withdrawal/enter_amount',
        update=message,
        variables={
            'wallet': wallet,
            'wallet_short': f"{wallet[:8]}...{wallet[-6:]}",
            'min_amount': float(min_amount),
            'max_amount': float(balance),
            'fee': float(fee)
        }
    )


# =============================================================================
# STEP 2: Amount Input
# =============================================================================

@payments_out_router.message(
    WithdrawalState.waiting_for_amount,
    F.content_type == "text"
)
async def withdrawal_process_amount(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Process amount input.
    Validate range and proceed to confirmation.
    """
    amount_text = message.text.strip()

    # Parse amount
    try:
        # Handle comma as decimal separator
        amount_text = amount_text.replace(',', '.').replace('$', '').strip()
        amount = Decimal(amount_text)
    except Exception:
        logger.info(f"Invalid amount format from user {user.userID}: {message.text}")
        min_amount = Decimal(str(Config.get(Config.WITHDRAWAL_MIN, 10)))
        balance = Decimal(str(user.balancePassive or 0))

        await message_manager.send_template(
            user=user,
            template_key='withdrawal/invalid_amount',
            update=message,
            variables={
                'min_amount': float(min_amount),
                'max_amount': float(balance)
            }
        )
        return

    # Get limits
    min_amount = Decimal(str(Config.get(Config.WITHDRAWAL_MIN, 10)))
    fee = Decimal(str(Config.get(Config.WITHDRAWAL_FEE, 1)))

    # Re-fetch user to get fresh balance (prevent race condition)
    session.refresh(user)
    balance = Decimal(str(user.balancePassive or 0))

    # Validate amount
    if amount < min_amount or amount > balance:
        logger.info(f"Amount out of range: {amount}, min={min_amount}, max={balance}")
        await message_manager.send_template(
            user=user,
            template_key='withdrawal/invalid_amount',
            update=message,
            variables={
                'min_amount': float(min_amount),
                'max_amount': float(balance)
            }
        )
        return

    # Calculate total to receive
    total_to_receive = amount - fee

    # Save amount and proceed to confirmation
    state_data = await state.get_data()
    wallet = state_data.get('wallet')

    await state.update_data(amount=float(amount))
    await state.set_state(WithdrawalState.confirm_withdrawal)

    # Show confirmation
    await message_manager.send_template(
        user=user,
        template_key='withdrawal/confirm',
        update=message,
        variables={
            'wallet': wallet,
            'wallet_short': f"{wallet[:8]}...{wallet[-6:]}",
            'amount': float(amount),
            'fee': float(fee),
            'total': float(total_to_receive)
        }
    )


# =============================================================================
# STEP 3: Confirmation
# =============================================================================

@payments_out_router.callback_query(
    F.data == "withdrawal_confirm",
    WithdrawalState.confirm_withdrawal
)
async def withdrawal_execute(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    User confirmed withdrawal.
    Create Payment record and notify admins.
    """
    state_data = await state.get_data()
    wallet = state_data.get('wallet')
    amount = Decimal(str(state_data.get('amount', 0)))

    logger.info(f"User {user.userID} confirming withdrawal: {amount} to {wallet[:10]}...")

    # Re-verify balance (race condition protection)
    session.refresh(user)
    balance = Decimal(str(user.balancePassive or 0))

    if amount > balance:
        logger.warning(f"Balance changed during withdrawal! User {user.userID}, requested {amount}, has {balance}")
        await message_manager.send_template(
            user=user,
            template_key='withdrawal/insufficient_balance',
            update=callback_query,
            variables={
                'balance': float(balance),
                'min_amount': float(Config.get(Config.WITHDRAWAL_MIN, 10))
            },
            edit=True
        )
        await state.clear()
        return

    # Get our wallet for fromWallet field
    our_wallet = Config.get(Config.WALLET_TRC) or ''
    fee = Decimal(str(Config.get(Config.WITHDRAWAL_FEE, 1)))
    total_to_send = amount - fee

    try:
        # Create Payment record
        payment = Payment(
            userID=user.userID,
            firstname=user.firstname,
            surname=user.surname,
            direction='out',
            status='check',  # Immediately goes to admin review
            amount=amount,
            method=WITHDRAWAL_METHOD,
            sumCurrency=float(total_to_send),  # Amount user will receive
            fromWallet=our_wallet,  # Our wallet (source)
            toWallet=wallet,  # User's wallet (destination)
            ownerTelegramID=user.telegramID,
            ownerEmail=user.email or '',
            notes=f'Withdrawal request, fee=${fee}'
        )
        session.add(payment)
        session.flush()  # Get payment ID

        payment_id = payment.paymentID
        logger.info(f"Created withdrawal payment {payment_id} for user {user.userID}")

        # Create admin notifications
        try:
            await create_outgoing_check_notification(payment, user, session)
        except Exception as e:
            logger.error(f"Failed to create admin notifications: {e}", exc_info=True)
            # Don't fail the whole operation

        session.commit()

        # Clear state
        await state.clear()

        # Show success message
        await message_manager.send_template(
            user=user,
            template_key='withdrawal/created',
            update=callback_query,
            variables={
                'payment_id': payment_id,
                'amount': float(amount),
                'total': float(total_to_send)
            },
            edit=True
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Error creating withdrawal: {e}", exc_info=True)

        await message_manager.send_template(
            user=user,
            template_key='withdrawal/error',
            update=callback_query,
            variables={'error': str(e)},
            edit=True
        )
        await state.clear()


# =============================================================================
# CANCEL
# =============================================================================

@payments_out_router.callback_query(F.data == "withdrawal_cancel")
async def withdrawal_cancel(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Cancel withdrawal at any step.
    Clear state and return to finances.
    """
    logger.info(f"User {user.userID} cancelled withdrawal")

    await state.clear()

    # Return to finances menu
    await message_manager.send_template(
        user=user,
        template_key='withdrawal/cancelled',
        update=callback_query,
        edit=True
    )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'payments_out_router',
    'create_outgoing_check_notification',
]