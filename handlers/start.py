# jetup/handlers/start.py
"""
Start command handler and welcome flow.
Handles user registration, EULA acceptance, and channel subscription checks.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.user import User
from models.payment import Payment
from models.purchase import Purchase
from services.document.pdf_generator import generate_document
from services.user_domain.auth_service import AuthService
from services.stats_service import StatsService
from mlm_system.services.rank_service import RankService
from mlm_system.config.ranks import RANK_CONFIG, Rank
from core.message_manager import MessageManager
from core.di import get_service
from config import Config

logger = logging.getLogger(__name__)

start_router = Router(name="start_router")


@start_router.message(CommandStart())
async def cmd_start(
        message: Message,
        user: User,  # Can be None for new users (injected by middleware)
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

    # If user doesn't exist - register with referral
    if not user:
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

        # Handle old email verification (DARWIN migration)
        if start_payload and start_payload.startswith('oldemailverif_'):
            token = start_payload.replace('oldemailverif_', '')
            await handle_old_email_verification(message, user, session, message_manager, token)
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
    3. If existing user → show dashboard with stats
    4. If new user → show welcome screen
    """
    logger.info(f"show_welcome_screen for user {user.userID}")

    # ========================================================================
    # EULA CHECK
    # ========================================================================
    if not auth_service.is_eula_accepted(user):
        logger.info(f"User {user.userID} needs to accept EULA")
        await message_manager.send_template(
            user=user,
            template_key='eula_screen',
            update=message_or_callback,
            variables={'firstname': user.firstname or 'User'}
        )
        return

    # ========================================================================
    # CHANNEL SUBSCRIPTION CHECK
    # ========================================================================
    subscribed, not_subscribed_channels = await auth_service.check_channel_subscriptions(bot, user)

    if not subscribed:
        logger.info(f"User {user.userID} not subscribed to {len(not_subscribed_channels)} channels")

        channels = [c['title'] for c in not_subscribed_channels]
        urls = [c['url'] for c in not_subscribed_channels]

        await message_manager.send_template(
            user=user,
            template_key='channel_missing',
            update=message_or_callback,
            variables={
                'firstname': user.firstname or 'User',
                'rgroup': {
                    'channel': channels,
                    'url': urls,
                    'langChannel': channels
                }
            }
        )
        return

    # ========================================================================
    # GET GLOBAL STATISTICS (from Config dynamic values)
    # ========================================================================
    projects_count = await Config.get_dynamic(Config.PROJECTS_COUNT) or 0
    users_count = await Config.get_dynamic(Config.USERS_COUNT) or 0
    invested_total = await Config.get_dynamic(Config.INVESTED_TOTAL) or Decimal("0")

    # Convert Decimal to float for template
    purchases_total = float(invested_total)

    # ========================================================================
    # GET USER-SPECIFIC STATISTICS
    # ========================================================================
    stats_service = get_service(StatsService)

    upline_count = 0
    upline_total = 0
    user_purchases_total = Decimal("0")

    if stats_service:
        try:
            # Direct referrals
            upline_count = await stats_service.get_user_referrals_count(
                user.telegramID,
                direct_only=True
            )

            # All referrals (recursive)
            upline_total = await stats_service.get_user_referrals_count(
                user.telegramID,
                direct_only=False
            )

            # User's total purchases
            user_purchases_total = await stats_service.get_user_purchases_total(user.userID)

        except Exception as e:
            logger.error(f"Error getting user stats: {e}")

    # ========================================================================
    # MLM DATA
    # ========================================================================
    rank_display = "Старт"
    monthly_pv = Decimal("0")

    try:
        rank_service = RankService(session)
        active_rank = await rank_service.getUserActiveRank(user.userID)

        # Get rank display name
        try:
            rank_enum = Rank(active_rank)
            rank_config = RANK_CONFIG()
            rank_display = rank_config.get(rank_enum, {}).get("displayName", active_rank)
        except (ValueError, KeyError):
            rank_display = active_rank

        # Get monthly PV
        if user.mlmVolumes:
            monthly_pv = Decimal(str(user.mlmVolumes.get("monthlyPV", "0")))

    except Exception as e:
        logger.error(f"Error getting MLM data: {e}")

    # ========================================================================
    # DETERMINE TEMPLATE KEYS
    # ========================================================================
    template_keys = ['/dashboard/existingUser']

    # Add additional template if user data not filled
    if not user.isFilled:
        template_keys.append('settings_unfilled_data')
    elif user.isFilled and not user.emailConfirmed:
        template_keys.append('settings_filled_unconfirmed')

    # ========================================================================
    # SEND DASHBOARD
    # ========================================================================
    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        update=message_or_callback,
        variables={
            # User info
            'firstname': user.firstname or 'User',
            'language': user.lang or 'en',
            'email': user.email or '',

            # Balances
            'balanceActive': float(user.balanceActive or 0),
            'balancePassive': float(user.balancePassive or 0),
            'balance': float((user.balanceActive or 0) + (user.balancePassive or 0)),

            # Global statistics
            'projectsCount': projects_count,
            'usersCount': users_count,
            'purchasesTotal': purchases_total,

            # User statistics
            'userPurchasesTotal': float(user_purchases_total),
            'uplineCount': upline_count,
            'uplineTotal': upline_total,

            # MLM data
            'rank': rank_display,
            'isActive': user.isActive,
            'monthlyPV': float(monthly_pv),
            'teamVolumeTotal': float(user.teamVolumeTotal or 0)
        },
        delete_original=isinstance(message_or_callback, CallbackQuery)
    )


async def show_eula_screen(
        user: User,
        message_or_callback: Message | CallbackQuery,
        message_manager: MessageManager
):
    """Show EULA acceptance screen for new users."""
    await message_manager.send_template(
        user=user,
        template_key='/dashboard/newUser',
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
        template_key='/dashboard/noSubscribe',
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
    """Show main dashboard screen with full statistics."""
    # ========================================================================
    # GET SERVICES
    # ========================================================================
    stats_service = get_service(StatsService)

    # ========================================================================
    # GLOBAL STATISTICS
    # ========================================================================
    projects_count = 0
    users_count = 0
    purchases_total = 0

    if stats_service:
        try:
            projects_count = await stats_service.get_projects_count()
            users_count = await stats_service.get_users_count()
            purchases_total = await stats_service.get_purchases_total()
        except Exception as e:
            logger.error(f"Error getting global stats: {e}")

    # ========================================================================
    # USER STATISTICS
    # ========================================================================
    upline_count = 0
    upline_total = 0
    user_purchases_total = Decimal("0")

    if stats_service:
        try:
            # Direct referrals
            upline_count = await stats_service.get_user_referrals_count(
                user.telegramID,
                direct_only=True
            )

            # All referrals (recursive)
            upline_total = await stats_service.get_user_referrals_count(
                user.telegramID,
                direct_only=False
            )

            # User's total purchases
            user_purchases_total = await stats_service.get_user_purchases_total(user.userID)

        except Exception as e:
            logger.error(f"Error getting user stats: {e}")

    # ========================================================================
    # MLM DATA
    # ========================================================================
    rank_display = "Старт"
    monthly_pv = Decimal("0")

    try:
        rank_service = RankService(session)
        active_rank = await rank_service.getUserActiveRank(user.userID)

        # Get rank display name
        try:
            rank_enum = Rank(active_rank)
            rank_config = RANK_CONFIG()
            rank_display = rank_config.get(rank_enum, {}).get("displayName", active_rank)
        except (ValueError, KeyError):
            rank_display = active_rank

        # Get monthly PV
        if user.mlmVolumes:
            monthly_pv = Decimal(str(user.mlmVolumes.get("monthlyPV", "0")))

    except Exception as e:
        logger.error(f"Error getting MLM data: {e}")

    # ========================================================================
    # DETERMINE TEMPLATE KEYS
    # ========================================================================
    template_keys = ['/dashboard/existingUser']

    # Add additional template if user data not filled
    if not user.isFilled:
        template_keys.append('settings_unfilled_data')
    elif user.isFilled and not user.emailConfirmed:
        template_keys.append('settings_filled_unconfirmed')

    # ========================================================================
    # SEND DASHBOARD
    # ========================================================================
    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        update=message_or_callback,
        variables={
            # User info
            'firstname': user.firstname or 'User',
            'language': user.lang or 'en',
            'email': user.email or '',

            # Balances
            'balanceActive': float(user.balanceActive or 0),
            'balancePassive': float(user.balancePassive or 0),
            'balance': float((user.balanceActive or 0) + (user.balancePassive or 0)),

            # Global statistics
            'projectsCount': projects_count,
            'usersCount': users_count,
            'purchasesTotal': purchases_total,

            # User statistics
            'userPurchasesTotal': float(user_purchases_total),
            'uplineCount': upline_count,
            'uplineTotal': upline_total,

            # MLM data
            'rank': rank_display,
            'isActive': user.isActive,
            'monthlyPV': float(monthly_pv),
            'teamVolumeTotal': float(user.teamVolumeTotal or 0)
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
    Generates purchase agreement document.

    Flow:
    1. Get purchase_id from deep link
    2. Call generate_document() with purchase_id
    3. Send PDF to user
    """
    logger.info(f"Purchase document deep link: user={user.telegramID}, purchase={purchase_id}")

    try:
        # Convert purchase_id to int
        purchase_id_int = int(purchase_id)
    except ValueError:
        logger.error(f"Invalid purchase_id: {purchase_id}")
        await message.answer("❌ Invalid purchase ID")
        return

    # Verify purchase belongs to user (security check)
    purchase = session.query(Purchase).filter_by(
        purchaseID=purchase_id_int,
        userID=user.userID
    ).first()

    if not purchase:
        logger.warning(f"Purchase {purchase_id_int} not found for user {user.userID}")
        await message.answer("❌ Purchase not found or does not belong to you")
        return

    # Generate PDF
    # document_type='purchase' tells it to generate purchase agreement
    pdf_bytes = generate_document(
        session=session,
        user=user,
        document_type='purchase',
        document_id=purchase_id_int
    )

    if not pdf_bytes:
        logger.error(f"Failed to generate purchase document for purchase {purchase_id_int}")
        await message.answer("❌ Failed to generate document. Please try again later.")
        return

    # Create file from bytes and send
    # Filename format: purchase_{purchase_id}.pdf (as in old Talentir)
    file = BufferedInputFile(
        file=pdf_bytes,
        filename=f"purchase_{purchase_id}.pdf"
    )

    try:
        await message.answer_document(
            document=file,
            caption=f"📄 Purchase agreement #{purchase_id}"
        )
        logger.info(f"Purchase document sent to user {user.userID} for purchase {purchase_id_int}")
    except Exception as e:
        logger.error(f"Error sending purchase document: {e}", exc_info=True)
        await message.answer("❌ Failed to send document. Please try again later.")


async def handle_certificate_deep_link(
        message: Message,
        user: User,
        session: Session,
        project_id: str
):
    """
    Handle /start certificate_ID deep link.
    Generates certificate for project.

    Flow (as in old Talentir):
    1. Get project_id from deep link
    2. Find ANY purchase for this project by user
    3. Call generate_document() with purchase_id (it accepts purchaseID, not projectID)
    4. Send PDF to user
    """
    logger.info(f"Certificate deep link: user={user.telegramID}, project={project_id}")

    try:
        # Convert project_id to int
        project_id_int = int(project_id)
    except ValueError:
        logger.error(f"Invalid project_id: {project_id}")
        await message.answer("❌ Invalid project ID")
        return

    # Find ANY purchase for this project by user
    # generate_document() needs purchaseID, but certificate is for whole project
    purchase = session.query(Purchase).filter_by(
        userID=user.userID,
        projectID=project_id_int
    ).first()

    if not purchase:
        logger.warning(f"No purchases found for user {user.userID} in project {project_id_int}")
        await message.answer("❌ No purchases found for this project")
        return

    # Generate PDF using purchase_id (generate_document needs it to find project/option)
    # document_type='certificate' tells it to generate certificate, not purchase agreement
    pdf_bytes = generate_document(
        session=session,
        user=user,
        document_type='certificate',
        document_id=purchase.purchaseID  # <-- Pass purchase_id, function will find project from it
    )

    if not pdf_bytes:
        logger.error(f"Failed to generate certificate for project {project_id_int}")
        await message.answer("❌ Failed to generate certificate. Please try again later.")
        return

    # Create file from bytes and send
    # Filename format: certificate_{project_id}.pdf (as in old Talentir)
    file = BufferedInputFile(
        file=pdf_bytes,
        filename=f"certificate_{project_id}.pdf"
    )

    try:
        await message.answer_document(
            document=file,
            caption=f"📜 Certificate for project #{project_id}"
        )
        logger.info(f"Certificate sent to user {user.userID} for project {project_id_int}")
    except Exception as e:
        logger.error(f"Error sending certificate document: {e}", exc_info=True)
        await message.answer("❌ Failed to send certificate. Please try again later.")


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
        if not user.emailVerification:
            user.emailVerification = {}

        user.emailVerification['confirmed'] = True
        user.emailVerification['confirmedAt'] = datetime.now(timezone.utc).isoformat()

        # CRITICAL: Flag JSON field as modified for SQLAlchemy to track changes
        flag_modified(user, 'emailVerification')

        session.commit()
        session.refresh(user)

        logger.info(f"Email verified successfully for user {user.telegramID}")

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


async def handle_old_email_verification(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        token: str
):
    """
    Handle /start oldemailverif_TOKEN deep link.
    Verifies old email address for DARWIN migrated users.
    """
    logger.info(f"Old email verification deep link: user={user.telegramID}, token={token}")

    # Check if old email already verified
    if user.emailVerification and user.emailVerification.get('old_email_confirmed'):
        logger.info(f"Old email already verified for user {user.telegramID}")
        old_email = user.emailVerification.get('old_email', 'Unknown')
        await message_manager.send_template(
            user=user,
            template_key='/dashboard/oldemailverif_already',
            update=message,
            variables={'email': old_email}
        )
        return

    # Check token
    stored_token = user.emailVerification.get('old_email_token') if user.emailVerification else None

    if stored_token and stored_token == token:
        # Token valid - mark as confirmed
        if not user.emailVerification:
            user.emailVerification = {}

        user.emailVerification['old_email_confirmed'] = True
        user.emailVerification['old_email_confirmedAt'] = datetime.now(timezone.utc).isoformat()

        flag_modified(user, 'emailVerification')

        session.commit()
        session.refresh(user)

        logger.info(f"Old email verified successfully for user {user.telegramID}")

        old_email = user.emailVerification.get('old_email', 'Unknown')
        await message_manager.send_template(
            user=user,
            template_key='/dashboard/oldemailverif',
            update=message,
            variables={'email': old_email}
        )
    else:
        # Token invalid
        logger.warning(f"Invalid old email verification token for user {user.telegramID}")
        await message_manager.send_template(
            user=user,
            template_key='/dashboard/oldemailverif_invalid',
            update=message
        )


@start_router.callback_query(F.data == "/dashboard/existingUser")
async def back_to_dashboard(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        bot: Bot,
        message_manager: MessageManager,
        state: FSMContext
):
    """Return to main dashboard from any screen."""
    logger.info(f"User {user.telegramID} returning to dashboard")

    # Delete current message
    try:
        await callback_query.message.delete()
    except Exception as e:
        logger.warning(f"Failed to delete message: {e}")

    # Clear FSM state (safe even if state=None after restart)
    await state.clear()

    # Show welcome screen (handles EULA, subscriptions, dashboard)
    auth_service = AuthService(session)
    await show_welcome_screen(
        user=user,
        message_or_callback=callback_query,
        session=session,
        bot=bot,
        message_manager=message_manager,
        auth_service=auth_service
    )