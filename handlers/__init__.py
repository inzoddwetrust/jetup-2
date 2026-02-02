# jetup/handlers/__init__.py
"""
Handlers initialization.
"""
import logging
from aiogram import Dispatcher, Bot

from handlers.start import start_router
from handlers.projects import projects_router
from handlers.finances import finances_router
from handlers.payments_in import payments_in_router
from handlers.payments_out import payments_out_router
from handlers.transfers import transfers_router
from handlers.portfolio import portfolio_router
from handlers.team import team_router
from handlers.admin import setup_admin_handlers
from handlers.user_data import user_data_router
from handlers.help import help_router
from handlers.settings import settings_router
from handlers.fallback import fallback_router

logger = logging.getLogger(__name__)


def register_all_handlers(dp: Dispatcher, bot: Bot):
    """Register all handlers."""
    # Register user handlers
    dp.include_router(start_router)
    dp.include_router(projects_router)
    dp.include_router(finances_router)
    dp.include_router(payments_in_router)
    dp.include_router(payments_out_router)
    dp.include_router(transfers_router)
    dp.include_router(portfolio_router)
    dp.include_router(team_router)
    dp.include_router(user_data_router)
    dp.include_router(settings_router)
    dp.include_router(help_router)

    # Register admin handlers with middleware
    setup_admin_handlers(dp, bot)
    dp.include_router(fallback_router)

    logger.info("All handlers registered")