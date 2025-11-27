# handlers/admin/__init__.py
"""
Administrative commands module for Jetup bot.
Modular architecture with specialized sub-modules.

Structure:
    __init__.py          - Router setup, middleware, exports
    config_commands.py   - &upconfig, &upro, &ut
    import_commands.py   - &import, &restore
    payment_commands.py  - Payment approval/rejection callbacks
    legacy_commands.py   - Temporary: &stats, &testmail (to be split later)
"""
import logging
from typing import Any, Callable, Awaitable

from aiogram import Router, Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram import BaseMiddleware

from config import Config

logger = logging.getLogger(__name__)


# =============================================================================
# ADMIN MIDDLEWARE
# =============================================================================

class AdminMiddleware(BaseMiddleware):
    """
    Middleware to check admin permissions.

    Applied to admin router - blocks non-admin users from:
    - Commands starting with '&'
    - Admin-specific callbacks
    """

    def __init__(self, bot: Bot):
        self.bot = bot
        super().__init__()

    async def __call__(
            self,
            handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: dict[str, Any]
    ) -> Any:
        # Inject bot into data
        data["bot"] = self.bot

        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id

            # Log admin command attempts
            if isinstance(event, Message) and event.text and event.text.startswith('&'):
                logger.info(f"AdminMiddleware: processing command '{event.text}' from user {user_id}")

            # Get user from data (injected by UserMiddleware)
            user = data.get('user')
            if not user:
                logger.warning(f"User object not found for {user_id}")
                return None

            # Check if user is ADMIN
            admin_ids = Config.get(Config.ADMIN_USER_IDS, [])
            if user_id not in admin_ids:
                logger.warning(f"Non-admin user {user_id} attempted to access admin function")

                if isinstance(event, Message) and event.text:
                    await event.answer("⛔ You don't have permission to use admin commands.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("⛔ Access denied", show_alert=True)

                return None

            # Log successful admin action
            if isinstance(event, Message) and event.text:
                logger.info(f"Admin {user_id} executed command: {event.text}")
            elif isinstance(event, CallbackQuery):
                logger.info(f"Admin {user_id} triggered callback: {event.data}")

        return await handler(event, data)


# =============================================================================
# MAIN ADMIN ROUTER
# =============================================================================

admin_router = Router(name="admin")

# =============================================================================
# IMPORT SUB-ROUTERS
# =============================================================================

from .config_commands import config_router
from .import_commands import import_router
from .payment_commands import payment_router
from .legacy_commands import legacy_router

# Include sub-routers (order matters for command matching)
admin_router.include_router(config_router)
admin_router.include_router(import_router)
admin_router.include_router(payment_router)
admin_router.include_router(legacy_router)  # Temporary: &stats, &testmail, unknown handler


# =============================================================================
# SETUP FUNCTION
# =============================================================================

def setup_admin_handlers(dp: Dispatcher, bot: Bot):
    """
    Register admin handlers with middleware.

    Args:
        dp: Dispatcher instance
        bot: Bot instance
    """
    logger.info("Setting up admin handlers (modular)")

    # Apply AdminMiddleware to both message and callback handlers
    admin_router.message.middleware(AdminMiddleware(bot))
    admin_router.callback_query.middleware(AdminMiddleware(bot))

    # Include admin router in dispatcher
    dp.include_router(admin_router)

    logger.info("Admin handlers setup complete")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = [
    'admin_router',
    'setup_admin_handlers',
    'AdminMiddleware',
]