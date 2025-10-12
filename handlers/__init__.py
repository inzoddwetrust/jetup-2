# jetup/handlers/__init__.py
"""
Handlers initialization.
"""
import logging
from aiogram import Dispatcher, Bot

from handlers.start import start_router
from handlers.projects import projects_router
from handlers.admin import setup_admin_handlers

logger = logging.getLogger(__name__)


def register_all_handlers(dp: Dispatcher, bot: Bot):
    """Register all handlers."""
    # Register user handlers
    dp.include_router(start_router)
    dp.include_router(projects_router)

    # Register admin handlers with middleware
    setup_admin_handlers(dp, bot)

    logger.info("All handlers registered")

    # TODO: Add more routers as they are created:
    # from handlers.portfolio import portfolio_router
    # from handlers.team import team_router
    # from handlers.settings import settings_router
    # dp.include_router(portfolio_router)
    # dp.include_router(team_router)
    # dp.include_router(settings_router)