# jetup-2/handlers/payments.py
"""
Payment handlers - balance replenishment flow.
Ported from Talentir main.py.
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
from states.fsm_states import PurchaseFlow, TxidInputState
from utils.txid_checker import (
    validate_txid,
    verify_transaction,
    TxidValidationCode,
    TXID_TEMPLATE_MAPPING
)
from config import Config

logger = logging.getLogger(__name__)

payments_router = Router(name="payments_router")


# ============================================================================
# PAYMENT FLOW - USER SIDE
# ============================================================================

@payments_router.callback_query(F.data == "add_balance")
async def add_balance_start(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Start balance replenishment flow.
    Shows step 1 - amount selection.
    """
    logger.info(f"User {user.userID} started add_balance flow")

    await state.update_data(db_user_id=user.userID)

    await message_manager.send_template(
        user=user,
        template_key='add_balance_step1',
        update=callback_query,
        delete_original=True
    )

    await state.set_state(PurchaseFlow.waiting_for_payment)


@payments_router.callback_query(
    F.data.startswith("amount_"),
    PurchaseFlow.waiting_for_payment
)
async def select_amount(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Handle amount selection (predefined or custom).
    """
    amount = callback_query.data.split("_")[1]

    if amount == "custom":
        await message_manager.send_template(
            user=user,
            template_key='add_balance_custom',
            update=callback_query,
            edit=True
        )
        return

    await state.update_data(amount=float(amount))

    await message_manager.send_template(
        user=user,
        template_key='add_balance_currency',
        update=callback_query,
        variables={'amount': float(amount)},
        edit=True
    )


@payments_router.message(
    PurchaseFlow.waiting_for_payment,
    F.content_type == "text"
)
async def custom_amount_input(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Handle custom amount input from user.
    """
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError()

        await state.update_data(amount=amount)

        await message_manager.send_template(
            user=user,
            template_key='add_balance_currency',
            update=message,
            variables={'amount': amount}
        )

    except ValueError:
        await message_manager.send_template(
            user=user,
            template_key='add_balance_amount_error',
            update=message
        )


@payments_router.callback_query(
    F.data.startswith("currency_"),
    PurchaseFlow.waiting_for_payment
)
async def confirm_invoice(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Currency selected - calculate sumCurrency and show confirmation.
    """
    currency = callback_query.data.split("_")[1]
    user_data = await state.get_data()

    # Get stablecoins list
    stablecoins = Config.get(Config.STABLECOINS, ["USDT-ERC20", "USDT-BSC20", "USDT-TRC20"])

    if currency in stablecoins:
        currency_rate = 1.0
    else:
        # Get crypto rates (auto-updates if TTL expired)
        crypto_rates = await Config.get_dynamic(Config.CRYPTO_RATES)

        if not crypto_rates:
            # Both APIs unavailable - block payments
            logger.error("Crypto rates unavailable - both APIs failed")
            await message_manager.send_template(
                user=user,
                template_key='add_balance_rate_error',
                update=callback_query,
                variables={'currency': currency},
                edit=True
            )
            return

        currency_rate = crypto_rates.get(currency)

        if not currency_rate:
            # Currency not in rates
            await message_manager.send_template(
                user=user,
                template_key='add_balance_rate_error',
                update=callback_query,
                variables={'currency': currency},
                edit=True
            )
            return

    amount_usd = user_data["amount"]
    amount_currency = round(amount_usd / currency_rate, 2)

    await state.update_data(currency=currency, amount_currency=amount_currency)

    await message_manager.send_template(
        user=user,
        template_key='add_balance_confirm',
        update=callback_query,
        variables={
            'amount_usd': amount_usd,
            'currency': currency,
            'amount_currency': amount_currency
        },
        edit=True
    )


@payments_router.callback_query(
    F.data == "confirm_payment",
    PurchaseFlow.waiting_for_payment
)
async def create_payment_record(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Create Payment record in DB with status='pending'.
    Show invoice details with wallet address.
    """
    payment_data = await state.get_data()

    try:
        # Get wallet address from Config
        wallets = Config.get(Config.WALLETS) or {}
        wallet_address = wallets.get(payment_data["currency"])

        if not wallet_address:
            logger.error(f"No wallet configured for {payment_data['currency']}")
            await message_manager.send_template(
                user=user,
                template_key='add_balance_creation_error',
                update=callback_query,
                edit=True
            )
            return

        # Create Payment record
        payment = Payment(
            userID=user.userID,
            firstname=user.firstname,
            surname=user.surname,
            direction='in',  # incoming
            amount=Decimal(str(payment_data["amount"])),
            method=payment_data["currency"],
            fromWallet=None,
            toWallet=wallet_address,
            txid=None,
            sumCurrency=Decimal(str(payment_data["amount_currency"])),
            status="pending",
            ownerTelegramID=user.telegramID,
            ownerEmail=user.email
        )
        session.add(payment)
        session.commit()
        session.refresh(payment)

        logger.info(f"Created payment {payment.paymentID} for user {user.userID}")

        # Show invoice details
        await message_manager.send_template(
            user=user,
            template_key=['add_balance_created', 'pending_invoice_details'],
            update=callback_query,
            variables={
                'amount': payment.amount,
                'method': payment.method,
                'sumCurrency': payment.sumCurrency,
                'wallet': payment.toWallet,
                'payment_id': payment.paymentID
            },
            edit=True
        )

        await state.clear()

    except Exception as e:
        logger.error(f"Error creating payment: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='add_balance_creation_error',
            update=callback_query,
            edit=True
        )


@payments_router.callback_query(F.data == "cancel_payment")
async def cancel_payment(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Cancel payment creation and return to finances."""
    await callback_query.answer("Operation cancelled")
    await state.clear()

    # Return to finances screen
    await message_manager.send_template(
        user=user,
        template_key='/finances',
        update=callback_query,
        delete_original=True
    )


# ============================================================================
# TXID INPUT FLOW
# ============================================================================

@payments_router.callback_query(F.data.startswith("enter_txid_"))
async def request_txid(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    User clicks 'Enter TXID' button.
    Start TXID input flow.
    """
    payment_id = int(callback_query.data.split("_")[2])

    logger.info(f"User {user.userID} entering TXID for payment {payment_id}")

    await state.update_data(payment_id=payment_id)

    await message_manager.send_template(
        user=user,
        template_key='add_balance_enter_txid',
        update=callback_query,
        variables={}
    )

    await state.set_state(TxidInputState.waiting_for_txid)


@payments_router.message(
    TxidInputState.waiting_for_txid,
    F.content_type == "text"
)
async def process_txid_input(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Process TXID input from user.
    Validate format → Verify transaction → Update payment status.
    """
    txid = message.text.strip()
    state_data = await state.get_data()
    payment_id = state_data.get('payment_id')

    logger.info(f"Processing TXID {txid} for payment {payment_id}")

    # Check payment exists and belongs to user
    payment = session.query(Payment).filter_by(
        paymentID=payment_id,
        status="pending",
        userID=user.userID
    ).first()

    if not payment:
        await message_manager.send_template(
            user=user,
            template_key='txid_payment_not_found',
            update=message,
            variables={}
        )
        await state.clear()
        return

    # Check if TXID is already used
    existing_payment = session.query(Payment).filter_by(txid=txid).first()
    if existing_payment:
        await message_manager.send_template(
            user=user,
            template_key='txid_already_used',
            update=message,
            variables={}
        )
        await state.clear()
        return

    try:
        # Step 1: Validate TXID format
        validation_result = validate_txid(txid, payment.method)
        if validation_result.code != TxidValidationCode.VALID_TRANSACTION:
            template_key = TXID_TEMPLATE_MAPPING.get(
                validation_result.code,
                'txid_invalid_format'
            )

            await message_manager.send_template(
                user=user,
                template_key=template_key,
                update=message,
                variables={'details': validation_result.details} if validation_result.details else {}
            )
            return

        # Step 2: Verify transaction on blockchain
        wallets = Config.get(Config.WALLETS) or {}
        expected_wallet = payment.toWallet or wallets.get(payment.method)

        verification_result = await verify_transaction(
            txid,
            payment.method,
            expected_wallet
        )

        if verification_result.code != TxidValidationCode.VALID_TRANSACTION:
            template_key = TXID_TEMPLATE_MAPPING.get(
                verification_result.code,
                'txid_error'
            )

            await message_manager.send_template(
                user=user,
                template_key=template_key,
                update=message,
                variables={
                    'details': verification_result.details,
                    'from_address': verification_result.from_address,
                    'to_address': verification_result.to_address,
                    'expected_address': expected_wallet
                }
            )
            return

        # Step 3: Update payment record
        try:
            payment.txid = txid
            payment.status = "check"
            payment.fromWallet = verification_result.from_address

            session.commit()

            logger.info(f"Payment {payment_id} updated with TXID, status=check")

            # Step 4: Notify admins
            try:
                await create_payment_check_notification(payment, user, session)
                template_key = 'txid_success'
            except Exception as e:
                logger.error(f"Error creating admin notification: {e}", exc_info=True)
                template_key = 'txid_success_no_notify'

            await message_manager.send_template(
                user=user,
                template_key=template_key,
                update=message,
                variables={}
            )

            await state.clear()

        except Exception as e:
            session.rollback()
            logger.error(f"Error updating payment {payment_id} with txid {txid}: {e}", exc_info=True)

            await message_manager.send_template(
                user=user,
                template_key='txid_save_error',
                update=message,
                variables={}
            )

    except Exception as e:
        logger.error(f"Error processing TXID {txid}: {e}", exc_info=True)

        await message_manager.send_template(
            user=user,
            template_key='txid_error',
            update=message,
            variables={'error': str(e)}
        )


# ============================================================================
# PENDING/PAID INVOICES
# ============================================================================

@payments_router.callback_query(F.data == "pending_invoices")
async def pending_invoices_handler(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show list of pending/check invoices."""
    logger.info(f"User {user.userID} viewing pending invoices")

    # Get invoices with status 'check' and 'pending'
    check_invoices = session.query(Payment).filter(
        Payment.userID == user.userID,
        Payment.status == 'check'
    ).order_by(Payment.createdAt.desc()).all()

    pending_invoices = session.query(Payment).filter(
        Payment.userID == user.userID,
        Payment.status == 'pending'
    ).order_by(Payment.createdAt.desc()).all()

    invoices = check_invoices + pending_invoices
    invoices = invoices[:10]  # Limit to 10

    if invoices:
        # Get bot username for deep links
        bot_username = Config.get(Config.BOT_USERNAME) or 'jetup_bot'

        amounts = []
        info_list = []

        for invoice in invoices:
            # Format amount with link for pending invoices
            if invoice.status == 'pending':
                link = f"https://t.me/{bot_username}?start=invoice_{invoice.paymentID}"
                amounts.append(f"<a href='{link}'>${invoice.amount:.2f}</a>")
            else:
                amounts.append(f"${invoice.amount:.2f}")

            # Status info
            if invoice.status == 'check':
                info_list.append("💰<b>UNDER REVIEW</b>💰")
            else:
                info_list.append(invoice.createdAt.strftime('%Y-%m-%d %H:%M'))

        context = {
            "rgroup": {
                'i': list(range(1, len(invoices) + 1)),
                'amount_str': amounts,
                'method': [inv.method for inv in invoices],
                'sumCurrency': [inv.sumCurrency for inv in invoices],
                'info': info_list
            }
        }
        template_key = 'pending_invoices_list'
    else:
        context = {}
        template_key = 'pending_invoices_empty'

    await message_manager.send_template(
        user=user,
        template_key=template_key,
        update=callback_query,
        variables=context,
        delete_original=True
    )


@payments_router.callback_query(F.data == "paid_invoices")
async def paid_invoices_handler(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show list of paid invoices."""
    logger.info(f"User {user.userID} viewing paid invoices")

    paid_invoices = session.query(Payment).filter(
        Payment.userID == user.userID,
        Payment.status == 'paid'
    ).order_by(Payment.createdAt.desc()).limit(10).all()

    if paid_invoices:
        info_list = []

        for invoice in paid_invoices:
            if invoice.confirmationTime:
                info_list.append(invoice.confirmationTime.strftime('%Y-%m-%d %H:%M'))
            else:
                info_list.append(invoice.createdAt.strftime('%Y-%m-%d %H:%M'))

        context = {
            "rgroup": {
                'i': list(range(1, len(paid_invoices) + 1)),
                'amount': [inv.amount for inv in paid_invoices],
                'method': [inv.method for inv in paid_invoices],
                'sumCurrency': [inv.sumCurrency for inv in paid_invoices],
                'info': info_list
            }
        }
        template_key = 'paid_invoices_list'
    else:
        context = {}
        template_key = 'paid_invoices_empty'

    await message_manager.send_template(
        user=user,
        template_key=template_key,
        update=callback_query,
        variables=context,
        delete_original=True
    )


# ============================================================================
# NOTIFICATION HELPERS
# ============================================================================

async def create_payment_check_notification(
        payment: Payment,
        user: User,
        session: Session
):
    """
    Create notification for admins about new payment waiting for approval.
    """
    admin_user_ids = Config.get(Config.ADMIN_USER_IDS) or []

    if not admin_user_ids:
        logger.error("No admin users found in Config!")
        raise ValueError("No admin users found in database!")

    # Get TX browser URL
    tx_browsers = Config.get(Config.TX_BROWSERS) or {}

    from core.templates import MessageTemplates

    text, buttons = await MessageTemplates.get_raw_template(
        'admin_new_payment_notification',
        {
            'user_name': user.firstname,
            'user_id': user.userID,
            'payment_id': payment.paymentID,
            'payment_date': payment.createdAt,
            'amount': payment.amount,
            'method': payment.method,
            'sum_currency': payment.sumCurrency,
            'txid': payment.txid,
            'wallet': payment.toWallet,
            'tx_browser_url': tx_browsers.get(payment.method, '')
        }
    )

    for admin_id in admin_user_ids:
        notification = Notification(
            source="payment_checker",
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
    logger.info(f"Created notifications for {len(admin_user_ids)} admins about payment {payment.paymentID}")


async def create_user_payment_notification(
        payment: Payment,
        payer: User,
        is_approved: bool,
        session: Session
) -> Notification:
    """
    Create notification for user about payment approval/rejection.
    """
    from core.templates import MessageTemplates

    text, buttons = await MessageTemplates.get_raw_template(
        'user_payment_approved' if is_approved else 'user_payment_rejected',
        {
            'payment_id': payment.paymentID,
            'payment_date': payment.createdAt.strftime('%Y-%m-%d %H:%M:%S'),
            'amount': payment.amount,
            'balance': payer.balanceActive,
            'txid': payment.txid
        }
    )

    return Notification(
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