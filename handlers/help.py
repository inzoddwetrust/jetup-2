# jetup/handlers/help.py
"""
Help and information screens handler.
Displays FAQ, contacts, and social links.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery

from core.message_manager import MessageManager
from core.user_decorator import with_user
from models.user import User
from config import Config

logger = logging.getLogger(__name__)

help_router = Router(name="help_router")

# ============================================================================
# INFO SCREENS CONFIGURATION
# ============================================================================

INFO_SCREENS = {
    "/help": {
        "template_key": "/help",
        "variables": lambda: {
            "faq_url": Config.get(Config.FAQ_URL, "")
        }
    },
    "/help/contacts": {
        "template_key": "/help/contacts",
        "variables": lambda: {
            "rgroup": {
                "admin_link": Config.get(Config.ADMIN_LINKS, [])
            }
        }
    },
    "/help/social": {
        "template_key": "/help/social",
        "variables": lambda: Config.get(Config.SOCIAL_LINKS, {})
    }
}


# ============================================================================
# HANDLERS
# ============================================================================

@help_router.callback_query(F.data.in_(INFO_SCREENS.keys()))
@with_user
async def handle_info_screen(
        callback_query: CallbackQuery,
        user: User,
        session,
        message_manager: MessageManager
):
    """
    Handle info screen callbacks (/help, /help/contacts, /help/social).

    Displays static information screens with dynamic content from Config.
    """
    callback_data = callback_query.data
    screen_config = INFO_SCREENS[callback_data]

    template_key = screen_config["template_key"]
    variables = screen_config["variables"]()

    logger.info(f"User {user.telegramID} opened info screen: {callback_data}")

    await message_manager.send_template(
        user=user,
        template_key=template_key,
        variables=variables,
        update=callback_query,
        delete_original=True
    )