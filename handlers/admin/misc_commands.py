# handlers/admin/misc_commands.py
"""
Miscellaneous admin commands.

Commands:
    &stats    - Bot statistics
    &testmail - Test email sending
    &help     - Show available commands
    fallback  - Unknown command handler
"""
import logging
from datetime import datetime, timezone

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from config import Config
from core.message_manager import MessageManager
from core.di import get_service
from models.user import User
from services.stats_service import StatsService
from email_system import EmailService

logger = logging.getLogger(__name__)

misc_router = Router(name="admin_misc")


@misc_router.message(F.text == '&stats')
async def cmd_stats(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show bot statistics."""
    logger.info(f"Admin {message.from_user.id} requested &stats")

    reply = await message.reply("📊 Собираю статистику...")

    try:
        stats_service = get_service(StatsService)
        stats = await stats_service.get_full_stats()

        report = (
            f"📊 <b>Bot Statistics</b>\n\n"
            f"👥 <b>Users:</b>\n"
            f"  Total: {stats.get('total_users', 0)}\n"
            f"  Active (30d): {stats.get('active_users_30d', 0)}\n"
            f"  Active Partners: {stats.get('active_partners', 0)}\n\n"
            f"💰 <b>Finances:</b>\n"
            f"  Total deposits: ${stats.get('total_deposits', 0):.2f}\n"
            f"  Pending payments: {stats.get('pending_payments', 0)}\n\n"
            f"📈 <b>Purchases:</b>\n"
            f"  Total: {stats.get('total_purchases', 0)}\n"
            f"  Total volume: ${stats.get('total_volume', 0):.2f}\n\n"
            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
        )

        await reply.edit_text(report, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in &stats: {e}", exc_info=True)
        await reply.edit_text(f"❌ Error: {str(e)}")


@misc_router.message(F.text.startswith('&testmail'))
async def cmd_testmail(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Test email sending."""
    logger.info(f"Admin {message.from_user.id} requested &testmail")

    parts = message.text.strip().split()

    if len(parts) < 2:
        await message.reply(
            "Usage: <code>&testmail email@example.com [provider]</code>\n"
            "Provider: smtp (default) or mailgun",
            parse_mode="HTML"
        )
        return

    test_email = parts[1]
    provider = parts[2] if len(parts) > 2 else "smtp"

    reply = await message.reply(f"📧 Sending to {test_email} via {provider}...")

    try:
        email_service = EmailService()
        success = await email_service.send_email(
            to_email=test_email,
            subject="Test Email from Jetup Bot",
            html_content="<h1>Test</h1><p>This is a test email.</p>",
            provider=provider
        )

        if success:
            await reply.edit_text(f"✅ Sent to {test_email} via {provider}")
        else:
            await reply.edit_text(f"❌ Failed to send to {test_email}")

    except Exception as e:
        logger.error(f"Error in &testmail: {e}", exc_info=True)
        await reply.edit_text(f"❌ Error: {str(e)}")


@misc_router.message(F.text.regexp(r'^&h(elp)?$'))
async def cmd_help(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show available admin commands."""
    help_text = """
<b>📋 Admin Commands</b>

<b>Configuration:</b>
• <code>&upconfig</code> - Update config
• <code>&upro</code> - Update Projects + Options
• <code>&ut</code> - Update Templates

<b>Data:</b>
• <code>&import [table] [mode]</code> - Sync from Sheets
• <code>&restore [file]</code> - Restore backup
• <code>&legacy</code> - Legacy migration

<b>Payments:</b>
• <code>&check</code> - Pending payments
• <code>&addbalance --u ID --$ amt --confirm</code>

<b>Other:</b>
• <code>&stats</code> - Statistics
• <code>&testmail email [provider]</code>
"""
    await message.answer(help_text, parse_mode="HTML")


@misc_router.message(F.text.startswith('&'))
async def cmd_fallback(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Handle unknown admin commands."""
    cmd = message.text.split()[0]
    logger.info(f"Admin {message.from_user.id} unknown command: {cmd}")

    await message.reply(
        f"❓ Unknown: <code>{cmd}</code>\n"
        f"Use <code>&help</code>",
        parse_mode="HTML"
    )


__all__ = ['misc_router']