# jetup/handlers/start.py
"""
Start command handler and welcome flow.
Handles user registration, EULA acceptance, and channel subscription checks.
"""
import logging
from datetime import datetime, timezone
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy.orm import Session

from models.user import User
from models.payment import Payment
from services.user_domain.auth_service import AuthService
from core.message_manager import MessageManager
from config import Config

logger = logging.getLogger(__name__)

start_router = Router(name="start_router")


@start_router.message(CommandStart())
async def cmd_start(
        message: Message,
        user: User,
        session: Session,
        bot: Bot,
        message_manager: MessageManager
):
    """
    Handle /start command with optional deep link payload.

    Supported payloads:
    - REFERRER_ID: Referral registration
    - invoice_ID: Show pending invoice details
    - purchase_ID: Generate purchase document
    - certificate_ID: Generate certificate
    - emailverif_TOKEN: Email verification

    Flow for new users:
    1. Register user with referral support
    2. Check EULA acceptance
    3. Check channel subscriptions
    4. Show dashboard
    """
    logger.info(f"Start command from user {message.from_user.id}")

    # Extract payload from /start command
    start_payload = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else None

    # Check if user exists
    existing_user = session.query(User).filter_by(telegramID=message.from_user.id).first()

    # If user doesn't exist - register with referral
    if not existing_user:
        referrer_id = None

        if start_payload and start_payload.isdigit():
            referrer_id = int(start_payload)

            # Prevent self-referral
            if referrer_id == message.from_user.id:
                logger.warning(f"User {message.from_user.id} tried to refer themselves")
                referrer_id = None

        # Register user
        auth_service = AuthService(session)
        try:
            user, is_new = await auth_service.register_user(message.from_user, referrer_id=referrer_id)
            logger.info(f"New user registered: {user.telegramID} (upline: {user.upline})")
        except ValueError as e:
            logger.error(f"User registration failed: {e}")
            await message.answer("⚠️ System configuration error. Please contact support.")
            return

        # Refresh user object after commit
        user = session.query(User).filter_by(telegramID=message.from_user.id).first()

    # ========================================================================
    # DEEP LINK PAYLOADS - Process before welcome flow
    # ========================================================================

    if start_payload:
        # Invoice deep link: /start invoice_12345
        if start_payload.startswith("invoice_"):
            invoice_id = start_payload.split("_")[1]
            await handle_invoice_deep_link(message, user, session, message_manager, invoice_id)
            return

        # Purchase document: /start purchase_12345
        if start_payload.startswith("purchase_"):
            purchase_id = start_payload.split("_")[1]
            await handle_purchase_deep_link(message, user, session, purchase_id)
            return

        # Certificate: /start certificate_12345
        if start_payload.startswith("certificate_"):
            project_id = start_payload.split("_")[1]
            await handle_certificate_deep_link(message, user, session, project_id)
            return

        # Email verification: /start emailverif_TOKEN123
        if start_payload.startswith("emailverif_"):
            token = start_payload.split("_")[1]
            await handle_email_verification(message, user, session, message_manager, token)
            return

    # ========================================================================
    # STANDARD WELCOME FLOW
    # ========================================================================

    auth_service = AuthService(session)
    await show_welcome_screen(user, message, session, bot, message_manager, auth_service)


async def show_welcome_screen(
        user: User,
        message_or_callback: Message | CallbackQuery,
        session: Session,
        bot: Bot,
        message_manager: MessageManager,
        auth_service: AuthService
):
    """
    Show appropriate welcome screen based on user state.

    Flow:
    1. If EULA not accepted → show EULA screen
    2. If not subscribed to channels → show subscription prompt
    3. Otherwise → show dashboard
    """
    # Check EULA acceptance
    eula_accepted = auth_service.check_eula_accepted(user)

    if not eula_accepted:
        logger.info(f"User {user.telegramID} needs to accept EULA")
        await show_eula_screen(user, message_or_callback, message_manager)
        return

    # Check channel subscriptions
    required_channels = Config.get(Config.REQUIRED_CHANNELS)

    if required_channels:
        subscribed, not_subscribed_channels = await auth_service.check_channel_subscriptions(bot, user)

        if not subscribed:
            logger.info(f"User {user.telegramID} not subscribed to {len(not_subscribed_channels)} channels")
            await show_subscription_prompt(
                user,
                message_or_callback,
                message_manager,
                not_subscribed_channels
            )
            return

    # All checks passed - show dashboard
    logger.info(f"User {user.telegramID} passed all checks, showing dashboard")
    await show_dashboard(user, message_or_callback, message_manager, session)


async def show_eula_screen(
        user: User,
        message_or_callback: Message | CallbackQuery,
        message_manager: MessageManager
):
    """Show EULA acceptance screen for new users."""
    await message_manager.send_template(
        user=user,
        template_key='welcome_screen',
        update=message_or_callback,
        variables={
            'firstname': user.firstname or 'User'
        }
    )


async def show_subscription_prompt(
        user: User,
        message_or_callback: Message | CallbackQuery,
        message_manager: MessageManager,
        not_subscribed_channels: list
):
    """Show channel subscription prompt with list of required channels."""
    # Prepare channel data for template
    channels = [c['title'] for c in not_subscribed_channels]
    urls = [c['url'] for c in not_subscribed_channels]

    await message_manager.send_template(
        user=user,
        template_key='channels_check',
        update=message_or_callback,
        variables={
            'firstname': user.firstname or 'User',
            'rgroup': {
                'channel': channels,
                'url': urls,
                'langChannel': channels
            }
        },
        delete_original=isinstance(message_or_callback, CallbackQuery)
    )


async def show_dashboard(
        user: User,
        message_or_callback: Message | CallbackQuery,
        message_manager: MessageManager,
        session: Session
):
    """Show main dashboard screen."""
    # Determine dashboard template based on user state
    template_keys = ['dashboard']

    # Add additional template if user data not filled
    if not user.isFilled:
        template_keys.append('settings_unfilled_data')
    elif user.isFilled and not user.emailConfirmed:
        template_keys.append('settings_filled_unconfirmed')

    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        update=message_or_callback,
        variables={
            'firstname': user.firstname or 'User'
        },
        delete_original=isinstance(message_or_callback, CallbackQuery)
    )


@start_router.callback_query(F.data == '/acceptEula')
async def handle_eula_accept(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        bot: Bot,
        message_manager: MessageManager
):
    """Handle EULA acceptance button click."""
    logger.info(f"User {user.telegramID} accepted EULA")

    auth_service = AuthService(session)
    auth_service.accept_eula(user)

    # Delete EULA message
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete EULA message: {e}")

    # Continue with welcome flow
    await show_welcome_screen(user, callback_query, session, bot, message_manager, auth_service)


@start_router.callback_query(F.data == '/check/subscription')
async def handle_check_subscription(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        bot: Bot,
        message_manager: MessageManager
):
    """Handle subscription check button click."""
    logger.info(f"Checking subscriptions for user {user.telegramID}")

    auth_service = AuthService(session)
    subscribed, not_subscribed_channels = await auth_service.check_channel_subscriptions(bot, user)

    if subscribed:
        # All subscribed - continue to dashboard
        logger.info(f"User {user.telegramID} now subscribed to all channels")
        await show_welcome_screen(user, callback_query, session, bot, message_manager, auth_service)
    else:
        # Still not subscribed - show prompt again
        logger.info(f"User {user.telegramID} still missing {len(not_subscribed_channels)} subscriptions")

        channels = [c['title'] for c in not_subscribed_channels]
        urls = [c['url'] for c in not_subscribed_channels]

        await message_manager.send_template(
            user=user,
            template_key='channel_missing',
            update=callback_query,
            variables={
                'firstname': user.firstname or 'User',
                'rgroup': {
                    'channel': channels,
                    'url': urls,
                    'langChannel': channels
                }
            },
            delete_original=True
        )


@start_router.callback_query(F.data.startswith('lang_'))
async def handle_language_select(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        bot: Bot,
        message_manager: MessageManager
):
    """Handle language selection from EULA screen."""
    lang = callback_query.data.split('_')[1]

    if user.lang == lang:
        await callback_query.answer()
        return

    logger.info(f"User {user.telegramID} changed language from {user.lang} to {lang}")
    user.lang = lang
    session.commit()

    # Refresh screen with new language
    try:
        await callback_query.message.delete()
    except Exception:
        pass

    auth_service = AuthService(session)
    await show_welcome_screen(user, callback_query, session, bot, message_manager, auth_service)


# ============================================================================
# DEEP LINK HANDLERS
# ============================================================================

async def handle_invoice_deep_link(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        invoice_id: str
):
    """
    Handle /start invoice_ID deep link.
    Shows pending invoice details if it belongs to user.
    """
    logger.info(f"Invoice deep link: user={user.telegramID}, invoice={invoice_id}")

    payment = session.query(Payment).filter_by(
        paymentID=invoice_id,
        status="pending"
    ).first()

    if not payment:
        logger.warning(f"Invoice {invoice_id} not found or not pending")
        await message.answer("❌ Invoice not found or already processed.")
        return

    if payment.userID != user.userID:
        logger.warning(f"User {user.telegramID} tried to access invoice {invoice_id} of user {payment.userID}")
        await message.answer("❌ This invoice does not belong to you.")
        return

    # Get wallet from config (loaded from Google Sheets)
    wallets = Config.get('WALLETS') or {}
    wallet = payment.toWallet or wallets.get(payment.method)

    await message_manager.send_template(
        user=user,
        template_key='pending_invoice_details',
        update=message,
        variables={
            'amount': payment.amount,
            'method': payment.method,
            'sumCurrency': payment.sumCurrency,
            'wallet': wallet,
            'payment_id': payment.paymentID
        }
    )


async def handle_purchase_deep_link(
        message: Message,
        user: User,
        session: Session,
        purchase_id: str
):
    """
    Handle /start purchase_ID deep link.
    Generates purchase document.
    """
    logger.info(f"Purchase document deep link: user={user.telegramID}, purchase={purchase_id}")

    # TODO: Import and call generate_document when ready
    # from services.document_generator import generate_document
    # await generate_document(message, "purchase", purchase_id)

    await message.answer(f"📄 Generating purchase document #{purchase_id}...")


async def handle_certificate_deep_link(
        message: Message,
        user: User,
        session: Session,
        project_id: str
):
    """
    Handle /start certificate_ID deep link.
    Generates certificate for project.
    """
    logger.info(f"Certificate deep link: user={user.telegramID}, project={project_id}")

    # TODO: Import and call generate_document when ready
    # from services.document_generator import generate_document
    # await generate_document(message, "certificate", project_id)

    await message.answer(f"📜 Generating certificate for project #{project_id}...")


async def handle_email_verification(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        token: str
):
    """
    Handle /start emailverif_TOKEN deep link.
    Verifies user's email address.
    """
    logger.info(f"Email verification deep link: user={user.telegramID}, token={token}")

    # Check if already verified
    if user.emailVerification and user.emailVerification.get('confirmed'):
        logger.info(f"Email already verified for user {user.telegramID}")
        await message_manager.send_template(
            user=user,
            template_key='/dashboard/emailverif_already',
            update=message,
            variables={'email': user.email}
        )
        return

    # Check token
    stored_token = user.emailVerification.get('token') if user.emailVerification else None

    if stored_token and stored_token == token:
        # Token valid - mark as confirmed
        logger.info(f"Email verified successfully for user {user.telegramID}")

        if not user.emailVerification:
            user.emailVerification = {}

        user.emailVerification['confirmed'] = True
        user.emailVerification['confirmedAt'] = datetime.now(timezone.utc).isoformat()
        session.commit()

        await message_manager.send_template(
            user=user,
            template_key='/dashboard/emailverif',
            update=message,
            variables={'email': user.email}
        )
    else:
        # Token invalid
        logger.warning(f"Invalid email verification token for user {user.telegramID}")
        await message_manager.send_template(
            user=user,
            template_key='/dashboard/emailverif_invalid',
            update=message
        )