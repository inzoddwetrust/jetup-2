# jetup/core/system_services.py
"""
System services management for Jetup bot.
Handles service lifecycle, graceful shutdown, and resource initialization.
"""
import asyncio
import logging
import signal
import traceback
from typing import Dict, Any, List, Optional
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

        # Service instances for graceful shutdown
        self.notification_processor: Optional['NotificationProcessor'] = None
        self.transfer_bonus_processor: Optional['TransferBonusProcessor'] = None
        self.invoice_cleaner: Optional['InvoiceCleaner'] = None
        self.mlm_scheduler: Optional['MLMScheduler'] = None

        self._shutdown_event = asyncio.Event()

    async def start_services(self) -> None:
        """
        Start all background services.

        Services to start:
        - Notification processor (pending notifications)
        - Transfer bonus processor (transfer bonuses)
        - Invoice cleaner (old unpaid invoices)
        - MLM scheduler (monthly calculations, volume queue)
        """
        logger.info("=" * 60)
        logger.info("STARTING BACKGROUND SERVICES")
        logger.info("=" * 60)

        # ═══════════════════════════════════════════════════════════════
        # SERVICE 1: Notification Processor
        # ═══════════════════════════════════════════════════════════════
        from background.notification_processor import NotificationProcessor

        self.notification_processor = NotificationProcessor(polling_interval=10)
        task = asyncio.create_task(
            self.notification_processor.run(),
            name="notification_processor"
        )
        self.services.append(task)
        logger.info("✓ Notification processor started (10s interval)")

        # ═══════════════════════════════════════════════════════════════
        # SERVICE 2: Transfer Bonus Processor
        # ═══════════════════════════════════════════════════════════════
        from background.transfer_bonus_processor import TransferBonusProcessor

        self.transfer_bonus_processor = TransferBonusProcessor(polling_interval=10)
        task = asyncio.create_task(
            self.transfer_bonus_processor.run(),
            name="transfer_bonus_processor"
        )
        self.services.append(task)
        logger.info("✓ Transfer Bonus Processor started (10s interval)")

        # ═══════════════════════════════════════════════════════════════
        # SERVICE 3: Invoice Cleaner
        # ═══════════════════════════════════════════════════════════════
        from background.invoice_cleaner import InvoiceCleaner

        self.invoice_cleaner = InvoiceCleaner(check_interval=300)
        task = asyncio.create_task(
            self.invoice_cleaner.run(),
            name="invoice_cleaner"
        )
        self.services.append(task)
        logger.info("✓ Invoice cleaner started (300s interval)")

        # ═══════════════════════════════════════════════════════════════
        # SERVICE 4: MLM Scheduler (NEW!)
        # ═══════════════════════════════════════════════════════════════
        from background.mlm_scheduler import MLMScheduler

        self.mlm_scheduler = MLMScheduler(self.bot)

        # Start the scheduler (APScheduler will handle jobs)
        await self.mlm_scheduler.start()

        logger.info("✓ MLM Scheduler started (APScheduler)")
        logger.info("  → Volume Queue: every 30 seconds")
        logger.info("  → Scheduled Tasks: every 1 hour")
        logger.info("  → Daily Tasks: 00:00 UTC")

        logger.info("=" * 60)
        logger.info(f"✅ STARTED {len(self.services)} background services + MLM Scheduler")
        logger.info("=" * 60)

    async def stop_services(self) -> None:
        """Stop all background services gracefully."""
        logger.info("=" * 60)
        logger.info("STOPPING BACKGROUND SERVICES")
        logger.info("=" * 60)

        # ═══════════════════════════════════════════════════════════════
        # Stop each service gracefully
        # ═══════════════════════════════════════════════════════════════

        if self.notification_processor:
            logger.info("Stopping notification processor...")
            await self.notification_processor.stop()

        if self.transfer_bonus_processor:
            logger.info("Stopping transfer bonus processor...")
            await self.transfer_bonus_processor.stop()

        if self.invoice_cleaner:
            logger.info("Stopping invoice cleaner...")
            await self.invoice_cleaner.stop()

        if self.mlm_scheduler:
            logger.info("Stopping MLM scheduler...")
            await self.mlm_scheduler.stop()

        # ═══════════════════════════════════════════════════════════════
        # Cancel all asyncio tasks
        # ═══════════════════════════════════════════════════════════════
        logger.info(f"Cancelling {len(self.services)} background tasks...")

        for task in self.services:
            if not task.done():
                task.cancel()

        # Wait for all tasks to complete
        if self.services:
            await asyncio.gather(*self.services, return_exceptions=True)

        logger.info("=" * 60)
        logger.info("✅ ALL BACKGROUND SERVICES STOPPED")
        logger.info("=" * 60)

    def signal_shutdown(self) -> None:
        """Signal that shutdown has been requested."""
        self._shutdown_event.set()

    async def wait_for_shutdown(self) -> None:
        """Wait for shutdown signal."""
        await self._shutdown_event.wait()


# ═══════════════════════════════════════════════════════════════════════════
# RESOURCE SETUP
# ═══════════════════════════════════════════════════════════════════════════

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
        Dict with bot info (id, username, first_name, etc.)
    """
    try:
        me = await bot.get_me()
        return {
            "id": me.id,
            "username": me.username,
            "first_name": me.first_name,
            "can_join_groups": me.can_join_groups,
            "can_read_all_group_messages": me.can_read_all_group_messages,
            "supports_inline_queries": me.supports_inline_queries
        }
    except TelegramAPIError as e:
        logger.error(f"Failed to get bot info: {e}")
        return {}


async def start_bot_polling(bot: Bot, dp: Dispatcher) -> None:
    """
    Start bot polling.

    Args:
        bot: Bot instance
        dp: Dispatcher instance
    """
    try:
        logger.info("Starting bot polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Error during polling: {e}", exc_info=True)
        raise


# ═══════════════════════════════════════════════════════════════════════════
# GRACEFUL SHUTDOWN
# ═══════════════════════════════════════════════════════════════════════════

async def shutdown(signal_type: signal.Signals, bot: Bot, dp: Dispatcher) -> None:
    """
    Cleanup tasks on shutdown.

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