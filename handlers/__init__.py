# jetup/handlers/__init__.py
"""
Handlers registration for Jetup bot.
"""
import logging
from aiogram import Dispatcher, Bot

logger = logging.getLogger(__name__)


def register_all_handlers(dp: Dispatcher, bot: Bot) -> None:
    """
    Register all bot handlers.

    Args:
        dp: Dispatcher instance
        bot: Bot instance
    """
    logger.info("Registering handlers...")

    # TODO: Import and register handlers as they are created
    # Example:
    # from .start import start_router
    # dp.include_router(start_router)

    # from .profile import profile_router
    # dp.include_router(profile_router)

    # from .projects import projects_router
    # dp.include_router(projects_router)

    logger.info("✓ Handlers registered (currently empty - ready for Stage 3)")


__all__ = ['register_all_handlers']