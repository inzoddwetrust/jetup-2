# handlers/admin/legacy_commands.py
"""
Legacy user migration commands.

Commands:
    &legacy    - Run migration batch (processes both V1 and V2)
    &export_v2 - One-time V2 export DB → GS (TEMPORARY)
"""
import asyncio
import logging

from aiogram import Router, F, Bot
from aiogram.types import Message
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from models.user import User

logger = logging.getLogger(__name__)

legacy_router = Router(name="admin_legacy")

# =============================================================================
# DOUBLE-RUN PROTECTION
# =============================================================================

_legacy_running = False
_legacy_lock = asyncio.Lock()


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    from config import Config
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    if not admins:
        logger.warning("ADMIN_USER_IDS not configured")
    return user_id in admins


async def _run_legacy_background(bot: Bot, chat_id: int):
    """
    Background task for legacy migration.

    Args:
        bot: Bot instance for sending report
        chat_id: Chat ID to send report to
    """
    global _legacy_running

    sync_stats = {}
    process_stats = {}
    error_message = None

    try:
        from services.legacy_sync import LegacySyncService
        from services.legacy_processor import LegacyProcessor

        # Sync first
        logger.info("Legacy: syncing with Google Sheets...")
        sync_stats = await LegacySyncService.sync_all()
        logger.info(f"Legacy: sync complete: {sync_stats}")

        # Then process
        logger.info("Legacy: processing batch...")
        process_stats = await LegacyProcessor.process_batch()
        logger.info(f"Legacy: migration complete: {process_stats}")

    except Exception as e:
        logger.error(f"Legacy migration error: {e}", exc_info=True)
        error_message = str(e)

    finally:
        # Always release the lock
        _legacy_running = False

        # Send report to chat
        try:
            report = _format_legacy_report(sync_stats, process_stats, error_message)
            await bot.send_message(chat_id, report, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Failed to send legacy report: {e}")


def _format_legacy_report(
        sync_stats: dict,
        process_stats: dict,
        error_message: str | None
) -> str:
    """
    Format legacy migration report for chat.

    Args:
        sync_stats: Stats from LegacySyncService.sync_all()
        process_stats: Stats from LegacyProcessor.process_batch()
        error_message: Error message if any

    Returns:
        Formatted HTML report string
    """
    lines = ["<b>📊 Legacy Migration Report</b>", ""]

    # Sync stats
    v1 = sync_stats.get('v1', {})
    v2 = sync_stats.get('v2', {})

    lines.append("<b>Sync (GS ↔ DB):</b>")
    lines.append(f"  V1: imported={v1.get('imported', 0)}, "
                 f"updated={v1.get('updated', 0)}, "
                 f"exported={v1.get('exported', 0)}")
    lines.append(f"  V2: imported={v2.get('imported', 0)}, "
                 f"updated={v2.get('updated', 0)}, "
                 f"exported={v2.get('exported', 0)}")
    lines.append("")

    # Process stats
    lines.append("<b>Processing:</b>")
    lines.append(f"  V1 processed: {process_stats.get('v1_processed', 0)}")
    lines.append(f"  V2 processed: {process_stats.get('v2_processed', 0)}")
    lines.append(f"  Uplines assigned: {process_stats.get('uplines_assigned', 0)}")
    lines.append(f"  Errors: {process_stats.get('errors', 0)}")

    # Error if any
    if error_message:
        lines.append("")
        lines.append(f"<b>❌ Error:</b> <code>{error_message[:200]}</code>")

    # Status
    lines.append("")
    if error_message or process_stats.get('errors', 0) > 0:
        lines.append("⚠️ Completed with errors")
    else:
        lines.append("✅ Completed successfully")

    return "\n".join(lines)


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
    global _legacy_running

    if not is_admin(message.from_user.id):
        return

    # Check if already running
    async with _legacy_lock:
        if _legacy_running:
            await message.answer(
                "⚠️ Legacy migration уже запущена. Дождитесь завершения."
            )
            return
        _legacy_running = True

    logger.info(f"Admin {message.from_user.id} triggered &legacy")

    # Run in background, don't block bot
    asyncio.create_task(
        _run_legacy_background(message.bot, message.chat.id)
    )
    await message.answer("⏳ Legacy migration запущена в фоне. Отчёт будет отправлен по завершении.")


# =============================================================================
# &export_v2 - One-time V2 export (TEMPORARY - delete after use)
# =============================================================================

@legacy_router.message(F.text == '&export_v2')
async def cmd_export_v2(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    One-time V2 export: DB → Google Sheets.
    TEMPORARY COMMAND - delete after migration cleanup.
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &export_v2")

    await message.answer("⏳ Exporting V2 to Google Sheets...")

    try:
        from services.legacy_sync import LegacySyncService

        exported = await LegacySyncService._export_v2()

        await message.answer(
            f"✅ V2 Export complete!\n\n"
            f"Exported: <b>{exported}</b> records",
            parse_mode="HTML"
        )
        logger.info(f"V2 export complete: {exported} records")

    except Exception as e:
        logger.error(f"V2 export error: {e}", exc_info=True)
        await message.answer(
            f"❌ Export failed:\n<code>{str(e)[:200]}</code>",
            parse_mode="HTML"
        )