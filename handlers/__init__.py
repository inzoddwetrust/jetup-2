# jetup/handlers/__init__.py
"""
Handlers registration for Jetup bot.
All routers are registered here.
"""
import logging
from aiogram import Dispatcher, Bot

logger = logging.getLogger(__name__)


def register_all_handlers(dp: Dispatcher, bot: Bot) -> None:
    """
    Register all handler routers with the dispatcher.

    Args:
        dp: Dispatcher instance
        bot: Bot instance
    """
    # Import routers
    from handlers.start import start_router

    # Register routers in order of priority
    dp.include_router(start_router)

    logger.info("Registered handler routers:")
    logger.info("  - start_router")

    # TODO: Add more routers as they are created:
    # from handlers.dashboard import dashboard_router
    # from handlers.portfolio import portfolio_router
    # from handlers.team import team_router
    # from handlers.settings import settings_router
    # from handlers.admin import admin_router
    # dp.include_router(dashboard_router)
    # dp.include_router(portfolio_router)
    # dp.include_router(team_router)
    # dp.include_router(settings_router)
    # dp.include_router(admin_router)