# handlers/admin/__init__.py
"""
Admin commands module.
Modular structure with specialized sub-routers.
"""
import logging
from typing import Any, Callable, Dict, Awaitable

from aiogram import Router, Bot, Dispatcher
from aiogram.types import Message, CallbackQuery, TelegramObject
from aiogram.dispatcher.middlewares.base import BaseMiddleware

from config import Config

logger = logging.getLogger(__name__)


# =============================================================================
# ADMIN MIDDLEWARE
# =============================================================================

class AdminMiddleware(BaseMiddleware):
    """
    Middleware to check admin access for all admin router handlers.
    """

    def __init__(self, bot: Bot):
        self.bot = bot
        super().__init__()

    async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any]
    ) -> Any:
        # Get user_id from event
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        else:
            return await handler(event, data)

        # Check admin access
        admin_ids = Config.get(Config.ADMIN_USER_IDS) or []

        if user_id not in admin_ids:
            logger.warning(f"Non-admin {user_id} tried to access admin command")

            if isinstance(event, Message):
                await event.answer("⛔ Access denied")
            elif isinstance(event, CallbackQuery):
                await event.answer("⛔ Access denied", show_alert=True)

            return None

        # Log admin action
        if isinstance(event, Message) and event.text:
            logger.info(f"Admin {user_id} executed: {event.text}")
        elif isinstance(event, CallbackQuery):
            logger.info(f"Admin {user_id} callback: {event.data}")

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
#from .balance_commands import balance_router
from .legacy_commands import legacy_router
from .misc_commands import misc_router

# Include sub-routers (ORDER MATTERS - misc_router LAST for fallback)
admin_router.include_router(config_router)
admin_router.include_router(import_router)
admin_router.include_router(payment_router)
#admin_router.include_router(balance_router)
admin_router.include_router(legacy_router)
admin_router.include_router(misc_router)  # LAST - has fallback handler


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
    logger.info("Setting up admin handlers")

    # Apply AdminMiddleware
    admin_router.message.middleware(AdminMiddleware(bot))
    admin_router.callback_query.middleware(AdminMiddleware(bot))

    # Include in dispatcher
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