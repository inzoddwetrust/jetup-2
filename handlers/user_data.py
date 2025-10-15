# jetup/handlers/user_data.py
"""
User data collection handler.
Manages FSM flow for collecting personal information.
"""
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.user import User
from states.fsm_states import UserDataDialog
from services.user_domain.user_data_service import (
    UserDataService,
    FIELD_CONFIG,
    FieldValidator,
    get_state_name,
    find_previous_state
)
from email_system import EmailService
from core.message_manager import MessageManager
from core.user_decorator import with_user
from core.di import get_service
from config import Config

logger = logging.getLogger(__name__)

user_data_router = Router(name="user_data_router")


# ============================================================================
# START USER DATA DIALOG
# ============================================================================

@user_data_router.callback_query(F.data == "fill_user_data")
@with_user
async def start_user_data_dialog(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Start user data collection dialog.
    Shows first input screen (firstname).
    """
    logger.info(f"User {user.userID} starting user data dialog")

    # Delete current message
    try:
        await callback_query.message.delete()
    except Exception:
        pass

    # Show first input screen
    await message_manager.send_template(
        user=user,
        template_key='user_data_firstname',
        update=callback_query
    )

    # Set FSM state
    await state.set_state(UserDataDialog.waiting_for_firstname)
    logger.info(f"User {user.userID} entered state: waiting_for_firstname")


# ============================================================================
# HANDLE TEXT INPUT (ALL FIELDS)
# ============================================================================

@user_data_router.message(UserDataDialog.waiting_for_firstname)
@user_data_router.message(UserDataDialog.waiting_for_surname)
@user_data_router.message(UserDataDialog.waiting_for_birthday)
@user_data_router.message(UserDataDialog.waiting_for_passport)
@user_data_router.message(UserDataDialog.waiting_for_country)
@user_data_router.message(UserDataDialog.waiting_for_city)
@user_data_router.message(UserDataDialog.waiting_for_address)
@user_data_router.message(UserDataDialog.waiting_for_phone)
@user_data_router.message(UserDataDialog.waiting_for_email)
@with_user
async def handle_user_input(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Handle user text input for any field.
    Validates input and moves to next state if valid.
    """
    # Get current state
    current_state = await state.get_state()
    if not current_state:
        logger.warning(f"User {user.userID} sent input but no FSM state set")
        return

    state_name = get_state_name(current_state)
    logger.info(f"User {user.userID} input for state: {state_name}")

    # Get field config
    field_config = FIELD_CONFIG.get(state_name)
    if not field_config:
        logger.error(f"No field config found for state: {state_name}")
        await state.clear()
        return

    # Validate input
    is_valid, processed_value = UserDataService.validate_input(
        message.text,
        field_config['validator']
    )

    if not is_valid:
        # Show error message
        logger.info(f"User {user.userID} input invalid for {field_config['field']}")

        await message_manager.send_template(
            user=user,
            template_key=field_config['template_error'],
            update=message
        )
        return

    # Save valid value to FSM storage
    await state.update_data({field_config['field']: processed_value})
    logger.info(f"User {user.userID} input accepted for {field_config['field']}")

    # Get next state
    next_state_name = field_config['next_state']

    if next_state_name == 'waiting_for_confirmation':
        # Show confirmation screen
        await show_confirmation_screen(message, user, session, message_manager, state)
    else:
        # Move to next input field
        next_config = FIELD_CONFIG.get(next_state_name)
        if not next_config:
            logger.error(f"No config found for next state: {next_state_name}")
            await state.clear()
            return

        await message_manager.send_template(
            user=user,
            template_key=next_config['template_request'],
            update=message
        )

        # Set next FSM state
        next_state = getattr(UserDataDialog, next_state_name)
        await state.set_state(next_state)
        logger.info(f"User {user.userID} moved to state: {next_state_name}")


# ============================================================================
# CONFIRMATION SCREEN
# ============================================================================

async def show_confirmation_screen(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Show confirmation screen with all collected data."""
    logger.info(f"Showing confirmation screen for user {user.userID}")

    # Get all collected data
    user_data = await state.get_data()

    # Format birthday for display
    birthday = user_data.get('birthday')
    if birthday:
        birthday_str = UserDataService.format_birthday(birthday)
    else:
        birthday_str = 'N/A'

    # Prepare variables for template
    variables = {
        'firstname': user_data.get('firstname', 'N/A'),
        'surname': user_data.get('surname', 'N/A'),
        'birthday': birthday_str,
        'passport': user_data.get('passport', 'N/A'),
        'country': user_data.get('country', 'N/A'),
        'city': user_data.get('city', 'N/A'),
        'address': user_data.get('address', 'N/A'),
        'phone': user_data.get('phoneNumber', 'N/A'),
        'email': user_data.get('email', 'N/A')
    }

    # Check if old email already added
    old_email = user_data.get('old_email')

    if old_email:
        # Show with old email info
        variables['old_email'] = old_email
        await message_manager.send_template(
            user=user,
            template_key=['user_data_confirmation', 'user_data_old_email_added'],
            variables=variables,
            update=message
        )
    else:
        # Show with DARWIN migration option
        await message_manager.send_template(
            user=user,
            template_key=['user_data_confirmation', 'user_data_darwin_migration'],
            variables=variables,
            update=message
        )

    # Set confirmation state
    await state.set_state(UserDataDialog.waiting_for_confirmation)


# ============================================================================
# CONFIRM USER DATA
# ============================================================================

@user_data_router.callback_query(F.data == "confirm_user_data")
@with_user
async def confirm_user_data(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Confirm and save user data.
    Generate verification token and send email.
    """
    # Check if in correct state
    current_state = await state.get_state()
    if not current_state or get_state_name(current_state) != 'waiting_for_confirmation':
        await callback_query.answer("Invalid state", show_alert=True)
        return

    logger.info(f"User {user.userID} confirming user data")

    # Get collected data
    user_data = await state.get_data()

    # Save to database
    success = await UserDataService.save_user_data(user, user_data, session)

    if not success:
        logger.error(f"Failed to save user data for user {user.userID}")

        await message_manager.send_template(
            user=user,
            template_key='user_data_save_error',
            update=callback_query,
            edit=True
        )
        await state.clear()
        return

    # Initialize email verification
    token = UserDataService.initialize_email_verification(user, session)

    # Generate verification link
    bot_username = Config.get(Config.BOT_USERNAME)
    verification_link = f"https://t.me/{bot_username}?start=emailverif_{token}"

    # Send verification email
    email_service = get_service(EmailService)

    if email_service:
        # Send to main email
        email_sent = await email_service.send_email(
            to=user.email,
            subject_template_key='email_verification_subject',
            body_template_key='email_verification_body',
            variables={
                'firstname': user.firstname or 'User',
                'email': user.email,
                'verification_link': verification_link,
                'projectName': 'JETUP'
            },
            lang=user.lang or 'en'
        )

        # Check if old email provided (DARWIN migration)
        old_email = user_data.get('old_email')
        old_email_sent = False

        if old_email:
            # Initialize old email verification
            old_token = UserDataService.initialize_old_email_verification(user, old_email, session)
            old_verification_link = f"https://t.me/{bot_username}?start=oldemailverif_{old_token}"

            # Send to old email
            old_email_sent = await email_service.send_email(
                to=old_email,
                subject_template_key='email_verification_subject',
                body_template_key='email_verification_body',
                variables={
                    'firstname': user.firstname or 'User',
                    'email': old_email,
                    'verification_link': old_verification_link,
                    'projectName': 'JETUP'
                },
                lang=user.lang or 'en'
            )

            if old_email_sent:
                logger.info(f"Old email verification sent to {old_email}")

        if email_sent:
            logger.info(f"Verification email sent to {user.email}")

            # Prepare template variables
            template_vars = {'email': user.email}
            if old_email and old_email_sent:
                template_vars['old_email'] = old_email

            await message_manager.send_template(
                user=user,
                template_key='user_data_saved_email_sent' if not old_email else 'user_data_saved_two_emails_sent',
                variables=template_vars,
                update=callback_query,
                edit=True
            )
        else:
            logger.error(f"Failed to send verification email to {user.email}")

            await message_manager.send_template(
                user=user,
                template_key='user_data_saved_email_failed',
                update=callback_query,
                edit=True
            )
    else:
        logger.error("EmailService not available")

        await message_manager.send_template(
            user=user,
            template_key='user_data_saved_email_failed',
            update=callback_query,
            edit=True
        )

    # Clear FSM state
    await state.clear()
    logger.info(f"User data dialog completed for user {user.userID}")


# ============================================================================
# NAVIGATION HANDLERS
# ============================================================================

@user_data_router.callback_query(F.data == "back")
@with_user
async def go_back(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Go back to previous input field."""
    current_state = await state.get_state()
    if not current_state:
        await callback_query.answer("No active dialog", show_alert=True)
        return

    # Check if we're in UserDataDialog
    if not current_state.startswith('UserDataDialog:'):
        await callback_query.answer("Invalid state", show_alert=True)
        return

    current_state_name = get_state_name(current_state)
    logger.info(f"User {user.userID} going back from {current_state_name}")

    # Find previous state
    previous_state_name = find_previous_state(current_state_name)

    if not previous_state_name:
        # First state - just show it again
        previous_state_name = 'waiting_for_firstname'

    # Get config for previous state
    previous_config = FIELD_CONFIG.get(previous_state_name)
    if not previous_config:
        logger.error(f"No config found for previous state: {previous_state_name}")
        return

    # Show previous input screen
    await message_manager.send_template(
        user=user,
        template_key=previous_config['template_request'],
        update=callback_query,
        edit=True
    )

    # Set previous FSM state
    previous_state = getattr(UserDataDialog, previous_state_name)
    await state.set_state(previous_state)
    logger.info(f"User {user.userID} moved back to state: {previous_state_name}")


@user_data_router.callback_query(F.data == "restart_user_data")
@with_user
async def restart_user_data(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Restart user data collection from beginning."""
    current_state = await state.get_state()
    if not current_state or not current_state.startswith('UserDataDialog:'):
        await callback_query.answer("No active dialog", show_alert=True)
        return

    logger.info(f"User {user.userID} restarting user data dialog")

    # Clear FSM data
    await state.clear()

    # Start from beginning
    await start_user_data_dialog(callback_query, user, session, message_manager, state)


@user_data_router.callback_query(F.data == "cancel_user_data")
@with_user
async def cancel_user_data(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Cancel user data collection."""
    current_state = await state.get_state()
    if not current_state or not current_state.startswith('UserDataDialog:'):
        await callback_query.answer("No active dialog", show_alert=True)
        return

    logger.info(f"User {user.userID} cancelling user data dialog")

    # Clear FSM state
    await state.clear()

    # Show cancellation message
    await message_manager.send_template(
        user=user,
        template_key='user_data_cancelled',
        update=callback_query,
        edit=True
    )


# ============================================================================
# EDIT USER DATA
# ============================================================================

@user_data_router.callback_query(F.data == "edit_user_data")
@with_user
async def edit_user_data(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Edit user data - restart collection dialog.
    Only available if data filled but email not confirmed.
    """
    logger.info(f"User {user.userID} requesting to edit user data")

    # Check if user can edit (data filled but email not confirmed)
    personal_data = user.personalData or {}
    email_verification = user.emailVerification or {}

    data_filled = personal_data.get('dataFilled', False)
    email_confirmed = email_verification.get('confirmed', False)

    if not data_filled or email_confirmed:
        await callback_query.answer("Invalid request", show_alert=True)
        return

    # Start user data dialog from beginning
    await start_user_data_dialog(callback_query, user, session, message_manager, state)


# ============================================================================
# RESEND VERIFICATION EMAIL
# ============================================================================

@user_data_router.callback_query(F.data == "resend_verification_email")
@with_user
async def resend_verification_email(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Resend verification email with cooldown check (5 minutes).
    """
    logger.info(f"User {user.userID} requesting to resend verification email")

    # Check if user can resend (data filled but email not confirmed)
    personal_data = user.personalData or {}
    email_verification = user.emailVerification or {}

    data_filled = personal_data.get('dataFilled', False)
    email_confirmed = email_verification.get('confirmed', False)

    if not data_filled or email_confirmed:
        await callback_query.answer("Invalid request", show_alert=True)
        return

    # Check cooldown
    email_service = get_service(EmailService)
    if not email_service:
        await message_manager.send_template(
            user=user,
            template_key='email_resend_failed',
            update=callback_query,
            delete_original=True
        )
        return

    can_send, remaining_seconds = email_service.can_resend_email(user, cooldown_minutes=5)

    if not can_send:
        remaining_minutes = remaining_seconds // 60 + (1 if remaining_seconds % 60 else 0)

        await message_manager.send_template(
            user=user,
            template_key='email_resend_cooldown',
            variables={'remaining_minutes': remaining_minutes},
            update=callback_query,
            delete_original=True
        )
        return

    # Get or regenerate verification token
    token = email_verification.get('token')

    if not token:
        # Generate new token
        token = UserDataService.initialize_email_verification(user, session)

    # Generate verification link
    bot_username = Config.get(Config.BOT_USERNAME)
    verification_link = f"https://t.me/{bot_username}?start=emailverif_{token}"

    # Send verification email
    email_sent = await email_service.send_email(
        to=user.email,
        subject_template_key='email_verification_subject',
        body_template_key='email_verification_body',
        variables={
            'firstname': user.firstname or 'User',
            'email': user.email,
            'verification_link': verification_link,
            'projectName': 'JETUP'
        },
        lang=user.lang or 'en'
    )

    if email_sent:
        # Update sent timestamp
        if not user.emailVerification:
            user.emailVerification = {}

        from datetime import datetime, timezone
        user.emailVerification['sentAt'] = datetime.now(timezone.utc).isoformat()
        user.emailVerification['attempts'] = user.emailVerification.get('attempts', 0) + 1

        flag_modified(user, 'emailVerification')

        session.commit()

        logger.info(f"Verification email resent to {user.email}")

        await message_manager.send_template(
            user=user,
            template_key='email_resend_success',
            variables={'email': user.email},
            update=callback_query,
            delete_original=True
        )
    else:
        logger.error(f"Failed to resend verification email to {user.email}")

        await message_manager.send_template(
            user=user,
            template_key='email_resend_failed',
            update=callback_query,
            delete_original=True

        )


# ============================================================================
# OLD EMAIL FOR DARWIN MIGRATION
# ============================================================================

@user_data_router.callback_query(F.data == "enter_old_email")
@with_user
async def enter_old_email(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Request old email address for DARWIN migrated users.
    """
    # Check if in confirmation state
    current_state = await state.get_state()
    if not current_state or get_state_name(current_state) != 'waiting_for_confirmation':
        await callback_query.answer("Invalid state", show_alert=True)
        return

    logger.info(f"User {user.userID} entering old email for DARWIN migration")

    await message_manager.send_template(
        user=user,
        template_key='user_data_old_email_request',
        update=callback_query,
        edit=True
    )

    await state.set_state(UserDataDialog.waiting_for_old_email)


@user_data_router.message(UserDataDialog.waiting_for_old_email)
@with_user
async def handle_old_email_input(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """Handle old email input from DARWIN migrated users."""
    logger.info(f"User {user.userID} provided old email")

    # Validate email
    is_valid, old_email = FieldValidator.validate_email(message.text)

    if not is_valid:
        logger.info(f"User {user.userID} provided invalid old email")
        await message_manager.send_template(
            user=user,
            template_key='user_data_old_email_error',
            update=message
        )
        return

    # Check if old email is same as new email
    user_data = await state.get_data()
    new_email = user_data.get('email')

    if old_email.lower() == new_email.lower():
        logger.warning(f"User {user.userID} entered same email as new one")
        await message_manager.send_template(
            user=user,
            template_key='user_data_old_email_same',
            update=message
        )
        return

    # Save old email to FSM storage
    await state.update_data({'old_email': old_email})
    logger.info(f"User {user.userID} old email accepted: {old_email}")

    # Return to confirmation screen WITH additional template
    user_data = await state.get_data()

    # Format birthday for display
    birthday = user_data.get('birthday')
    if birthday:
        birthday_str = UserDataService.format_birthday(birthday)
    else:
        birthday_str = 'N/A'

    # Prepare variables
    variables = {
        'firstname': user_data.get('firstname', 'N/A'),
        'surname': user_data.get('surname', 'N/A'),
        'birthday': birthday_str,
        'passport': user_data.get('passport', 'N/A'),
        'country': user_data.get('country', 'N/A'),
        'city': user_data.get('city', 'N/A'),
        'address': user_data.get('address', 'N/A'),
        'phone': user_data.get('phoneNumber', 'N/A'),
        'email': user_data.get('email', 'N/A'),
        'old_email': old_email
    }

    # Show confirmation WITH old email info (combine templates!)
    await message_manager.send_template(
        user=user,
        template_key=['user_data_confirmation', 'user_data_old_email_added'],
        variables=variables,
        update=message
    )

    # Set confirmation state
    await state.set_state(UserDataDialog.waiting_for_confirmation)