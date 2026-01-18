# handlers/admin/legacy_commands.py
"""
Legacy user migration commands.

Commands:
    &legacy  - Run migration batch (processes both V1 and V2)
"""
import asyncio
import logging

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from models.user import User

logger = logging.getLogger(__name__)

legacy_router = Router(name="admin_legacy")


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    from config import Config
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    if not admins:
        logger.warning("ADMIN_USER_IDS not configured")
    return user_id in admins


async def _run_legacy_background():
    """Background task for legacy migration."""
    try:
        from services.legacy_sync import LegacySyncService
        from services.legacy_processor import LegacyProcessor

        # Sync first
        logger.info("Legacy: syncing with Google Sheets...")
        sync_stats = await LegacySyncService.sync_all()
        logger.info(f"Legacy: sync complete: {sync_stats}")

        # Then process
        logger.info("Legacy: processing batch...")
        stats = await LegacyProcessor.process_batch()
        logger.info(f"Legacy: migration complete: {stats}")

    except Exception as e:
        logger.error(f"Legacy migration error: {e}", exc_info=True)


@legacy_router.message(F.text.startswith('&legacy'))
async def cmd_legacy(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Run legacy user migration manually.
    Runs in background to avoid blocking bot.
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &legacy")

    # Run in background, don't block bot
    asyncio.create_task(_run_legacy_background())
    await message.answer("⏳ Legacy migration запущена в фоне. Проверьте логи.")