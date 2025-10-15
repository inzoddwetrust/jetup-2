# jetup/jetup.py
"""
Jetup Bot - Main entry point.
Talentir investment platform bot on aiogram 3.x.
"""
import asyncio
import logging
import sys
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import Config, ConfigurationError
from core.db import setup_database
from core.di import register_service
from core.user_decorator import UserMiddleware
from core.system_services import (
    ServiceManager,
    setup_resources,
    get_bot_info,
    start_bot_polling,
    setup_signal_handlers
)
from handlers import register_all_handlers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('jetup.log')
    ]
)

logger = logging.getLogger(__name__)


async def initialize_bot():
    """
    Initialize bot with all services and configurations.

    Returns:
        Tuple[Bot, Dispatcher, ServiceManager]: Initialized instances
    """
    try:
        logger.info("=" * 60)
        logger.info("JETUP BOT INITIALIZATION")
        logger.info("=" * 60)

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 1: Load configuration from .env
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("📋 Loading configuration from .env...")
        Config.initialize_from_env()
        logger.info("✓ Configuration loaded")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 2: Setup database
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("💾 Setting up database...")
        setup_database()
        logger.info("✓ Database ready")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 3: Validate critical configuration
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("🔍 Validating critical configuration keys...")
        await Config.validate_critical_keys()
        logger.info("✓ Configuration validated")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 3.5: Load dynamic configuration from Google Sheets
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("📥 Loading dynamic configuration from Google Sheets...")
        await Config.initialize_dynamic_from_sheets()

        # ========================================================================
        # STEP 3.5: Initialize EmailService
        # ========================================================================
        logger.info("Initializing email service...")
        from email_system import EmailService
        email_service = EmailService()
        await email_service.initialize()
        register_service(EmailService, email_service)
        logger.info("✓ EmailService initialized and registered")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 4: Initialize bot and dispatcher
        # ═══════════════════════════════════════════════════════════════════════
        api_token = Config.get(Config.API_TOKEN)
        if not api_token:
            raise ConfigurationError("Bot API token not configured")

        bot = Bot(token=api_token)
        storage = MemoryStorage()
        dp = Dispatcher(storage=storage)

        # Get bot info
        bot_info = await get_bot_info(bot)
        bot_username = bot_info.get('username', 'unknown')
        Config.set(Config.BOT_USERNAME, bot_username)

        logger.info(f"🤖 Bot initialized: @{bot_username}")
        logger.info(f"   ID: {bot_info.get('id')}")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 5: Setup middleware
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("🔧 Setting up middleware...")
        dp.message.middleware(UserMiddleware(bot))
        dp.callback_query.middleware(UserMiddleware(bot))
        logger.info("✓ Middleware configured")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 6: Setup resources (templates, actions)
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("📚 Loading resources (templates, actions)...")
        message_manager = await setup_resources(bot)
        logger.info("✓ Resources loaded")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 7: Register handlers
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("🎯 Registering handlers...")
        register_all_handlers(dp, bot)
        logger.info("✓ Handlers registered")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 7.5: Setup MLM event handlers
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("🎲 Setting up MLM event handlers...")
        from mlm_system.events.setup import setup_mlm_event_handlers
        setup_mlm_event_handlers()
        logger.info("✓ MLM event handlers registered")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 8: Initialize service manager
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("⚙️ Initializing service manager...")
        service_manager = ServiceManager(bot)
        register_service(ServiceManager, service_manager)
        logger.info("✓ Service manager ready")

        # ═══════════════════════════════════════════════════════════════════════
        # STEP 9: Start background services
        # ═══════════════════════════════════════════════════════════════════════
        logger.info("🚀 Starting background services...")
        await service_manager.start_services()
        logger.info("✓ Background services started")

        # Mark system as ready
        Config.set(Config.SYSTEM_READY, True)

        logger.info("=" * 60)
        logger.info("✅ INITIALIZATION COMPLETE")
        logger.info("=" * 60)

        return bot, dp, service_manager

    except Exception as e:
        logger.critical(f"❌ Initialization failed: {e}", exc_info=True)
        raise


async def main():
    """Main entry point."""
    try:
        # Initialize bot
        bot, dp, service_manager = await initialize_bot()

        # Setup signal handlers for graceful shutdown
        loop = asyncio.get_event_loop()
        setup_signal_handlers(loop, bot, dp)

        # Start polling
        logger.info("🔄 Starting bot polling...")
        await start_bot_polling(bot, dp)

    except KeyboardInterrupt:
        logger.info("⚠️ Bot stopped by user")
    except Exception as e:
        logger.critical(f"❌ Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("👋 Bot shutdown complete")


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped")