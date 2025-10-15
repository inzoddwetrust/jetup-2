# jetup/handlers/settings.py
"""
Settings handler for user preferences and account management.
Handles language selection and user data status display.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from core.user_decorator import with_user
from models.user import User

logger = logging.getLogger(__name__)

settings_router = Router(name="settings_router")


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_settings_template_keys(user: User) -> list:
    """
    Get list of template keys for settings screen based on user data status.

    Args:
        user: User object

    Returns:
        List of template keys to display
    """
    template_keys = ['settings_main']

    # Add warning if user data not filled
    if not user.isFilled:
        template_keys.append('settings_unfilled_data')
    # Or if filled but email not confirmed
    elif user.isFilled and not user.emailConfirmed:
        template_keys.append('settings_filled_unconfirmed')

    # Always add language selection
    template_keys.append('settings_language')

    return template_keys


# ============================================================================
# HANDLERS
# ============================================================================

@settings_router.callback_query(F.data == "settings")
@with_user
async def handle_settings(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Show settings screen with language selection and user data status.

    Displays:
    - Current language
    - User data fill status (filled/unfilled)
    - Email confirmation status (if filled)
    - Language selection buttons
    """
    logger.info(f"User {user.telegramID} opened settings")

    template_keys = get_settings_template_keys(user)

    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        variables={'current_lang': user.lang or 'en'},
        update=callback_query
    )


@settings_router.callback_query(F.data.startswith('settings_lang_'))
@with_user
async def handle_settings_language_select(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Handle language selection from settings screen.

    Updates user's language preference and refreshes settings screen.
    """
    # Extract language from callback_data: settings_lang_en -> en
    lang = callback_query.data.split('_')[2]

    # If same language - do nothing
    if user.lang == lang:
        await callback_query.answer()
        return

    logger.info(f"User {user.telegramID} changed language from {user.lang} to {lang}")

    # Update user language
    user.lang = lang
    session.commit()

    # Refresh settings screen with new language
    template_keys = get_settings_template_keys(user)

    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        variables={'current_lang': lang},
        update=callback_query,
        edit=True
    )

    await callback_query.answer(f"Language changed to {lang.upper()}")