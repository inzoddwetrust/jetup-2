# jetup/core/system_services.py
"""
System services management for Jetup bot.
Handles service lifecycle, graceful shutdown, and resource initialization.
"""
import asyncio
import logging
import signal
import traceback
from typing import Dict, Any, List
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


class ServiceManager:
    """
    Manager for background services and tasks.
    Handles service lifecycle and graceful shutdown.
    """

    def __init__(self, bot: Bot):
        """
        Initialize service manager.

        Args:
            bot: Bot instance
        """
        self.bot = bot
        self.services: List[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def start_services(self) -> None:
        """
        Start all background services.

        Services to start:
        - MLM scheduler (monthly calculations)
        - Invoice cleaner (old unpaid invoices)
        - Notification processor (pending notifications)
        - Legacy user processor (migration)
        - Sync system webhook (if enabled)
        """
        logger.info("Starting background services...")

        # Start Notification Processor
        from background.notification_processor import NotificationProcessor
        notification_processor = NotificationProcessor(polling_interval=10)
        task = asyncio.create_task(notification_processor.run(), name="notification_processor")
        self.services.append(task)
        logger.info("✓ Notification processor started")

        # Start Transfer Bonus Processor
        from background.transfer_bonus_processor import TransferBonusProcessor
        transfer_bonus_processor = TransferBonusProcessor(polling_interval=10)
        task = asyncio.create_task(transfer_bonus_processor.run(), name="transfer_bonus_processor")
        self.services.append(task)
        logger.info("✓ Transfer Bonus Processor started")

        # TODO: Import and start services when ready
        # Example:
        # from background.mlm_scheduler import MLMScheduler
        # mlm_scheduler = MLMScheduler()
        # task = asyncio.create_task(mlm_scheduler.run())
        # self.services.append(task)

        logger.info(f"Started {len(self.services)} background services")

    async def stop_services(self) -> None:
        """Stop all background services gracefully."""
        logger.info("Stopping background services...")

        # Cancel all service tasks
        for task in self.services:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete
        if self.services:
            await asyncio.gather(*self.services, return_exceptions=True)

        logger.info("All background services stopped")

    def signal_shutdown(self) -> None:
        """Signal that shutdown has been requested."""
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()


async def setup_resources(bot: Bot) -> 'MessageManager':
    """
    Setup resources: templates, actions, message manager.

    Args:
        bot: Bot instance

    Returns:
        MessageManager: Initialized message manager
    """
    import traceback

    # Import here to avoid circular dependencies
    from core.templates import MessageTemplates
    from core.message_manager import MessageManager
    from core.di import register_service

    # Load templates from Google Sheets
    try:
        logger.info("Loading message templates from Google Sheets...")
        await MessageTemplates.load_templates()
        logger.info("✓ Message templates loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load templates: {e}")
        traceback.print_exc()
        raise

    # Initialize action system (stubs for compatibility)
    try:
        logger.info("Initializing action system...")
        from actions import initialize_registries
        initialize_registries()
        logger.info("✓ Action system initialized")
    except ImportError:
        logger.warning("Actions module not found, skipping action initialization")
    except Exception as e:
        logger.error(f"Failed to initialize action system: {e}")

    # Create message manager
    logger.info("Creating message manager...")
    message_manager = MessageManager(bot)

    # Register in DI container
    register_service(MessageManager, message_manager)
    logger.info("✓ Message manager registered in DI")

    logger.info("✓ Resources setup complete")
    return message_manager


async def get_bot_info(bot: Bot) -> Dict[str, Any]:
    """
    Get bot information from Telegram.

    Args:
        bot: Bot instance

    Returns:
        Dictionary with bot information
    """
    try:
        me = await bot.get_me()
        return {
            'id': me.id,
            'username': me.username,
            'first_name': me.first_name,
            'is_bot': me.is_bot,
            'can_join_groups': me.can_join_groups,
            'can_read_all_group_messages': me.can_read_all_group_messages,
            'supports_inline_queries': me.supports_inline_queries
        }
    except Exception as e:
        logger.error(f"Error getting bot info: {e}")
        return {'error': str(e)}


async def start_bot_polling(
        bot: Bot,
        dp: Dispatcher,
        timeout: int = 20,
        retry_interval: int = 5
) -> None:
    """
    Start bot polling with error handling and auto-retry.

    Args:
        bot: Bot instance
        dp: Dispatcher
        timeout: Polling timeout in seconds
        retry_interval: Retry interval in seconds if connection fails
    """
    logger.info("Starting bot polling...")

    while True:
        try:
            await dp.start_polling(
                bot,
                timeout=timeout,
                skip_updates=True
            )
        except TelegramAPIError as e:
            logger.error(f"Telegram API error: {e}. Retrying in {retry_interval}s...")
            await asyncio.sleep(retry_interval)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Bot polling stopped by user")
            break
        except Exception as e:
            logger.error(
                f"Unexpected error in bot polling: {e}. "
                f"Retrying in {retry_interval * 2}s..."
            )
            traceback.print_exc()
            await asyncio.sleep(retry_interval * 2)

    logger.info("Bot polling terminated")


async def shutdown(signal_type: signal.Signals, bot: Bot, dp: Dispatcher) -> None:
    """
    Graceful shutdown handler.

    Args:
        signal_type: Signal that triggered shutdown
        bot: Bot instance
        dp: Dispatcher instance
    """
    logger.info(f"Received exit signal {signal_type.name}...")

    # Stop polling
    logger.info("Stopping bot polling...")
    await dp.stop_polling()

    # Close bot session
    logger.info("Closing bot session...")
    if bot.session:
        await bot.session.close()

    logger.info("✓ Shutdown complete")


def setup_signal_handlers(loop: asyncio.AbstractEventLoop, bot: Bot, dp: Dispatcher) -> None:
    """
    Setup signal handlers for graceful shutdown.

    Args:
        loop: Event loop
        bot: Bot instance
        dp: Dispatcher instance
    """
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig,
                lambda s=sig: asyncio.create_task(shutdown(s, bot, dp))
            )
        except NotImplementedError:
            # Signal handlers not available on Windows
            logger.warning(f"Signal handler for {sig} not available on this platform")


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    'ServiceManager',
    'setup_resources',
    'get_bot_info',
    'start_bot_polling',
    'shutdown',
    'setup_signal_handlers',
]