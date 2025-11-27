# handlers/admin/legacy_commands.py
"""
TEMPORARY: Existing admin commands migrated from old admin.py

These commands should be split into proper modules later:
- &upconfig → config_commands.py (needs fixing - currently does wrong thing)
- &stats    → stats_commands.py
- &testmail → stats_commands.py

For now, they are grouped here to preserve functionality during migration.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from config import Config
from core.message_manager import MessageManager
from core.di import get_service
from models.user import User
from email_system import EmailService

logger = logging.getLogger(__name__)

# =============================================================================
# ROUTER SETUP
# =============================================================================

legacy_router = Router(name="admin_legacy")

# =============================================================================
# STATS COMMAND
# =============================================================================

@legacy_router.message(F.text == '&stats')
async def cmd_stats(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Show bot statistics.

    Uses Config.get_dynamic() for global statistics.
    StatsService is for user-specific stats only.
    """
    logger.info(f"Admin {message.from_user.id} triggered &stats")

    try:
        # Get global statistics from Config dynamic values
        users_count = await Config.get_dynamic(Config.USERS_COUNT) or 0
        projects_count = await Config.get_dynamic(Config.PROJECTS_COUNT) or 0
        invested_total = await Config.get_dynamic(Config.INVESTED_TOTAL) or Decimal("0")

        # Convert to float for display
        purchases_total = float(invested_total)

        # Check Time Machine status
        from mlm_system.utils.time_machine import timeMachine
        time_status = ""
        if timeMachine._isTestMode:
            time_status = (
                f"\n\n⚠️ <b>TIME MACHINE ACTIVE</b>\n"
                f"Virtual: {timeMachine.now.strftime('%Y-%m-%d %H:%M')}"
            )

        stats_text = (
            "📊 <b>Bot Statistics</b>\n\n"
            f"👥 Users: {users_count:,}\n"
            f"🚀 Projects: {projects_count}\n"
            f"💰 Total Investments: ${purchases_total:,.2f}"
            f"{time_status}"
        )

        await message.answer(stats_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in &stats: {e}", exc_info=True)
        await message.answer(f"❌ Error: {str(e)}")


# =============================================================================
# TESTMAIL COMMAND
# =============================================================================

@legacy_router.message(F.text.startswith('&testmail'))
async def cmd_testmail(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Test email functionality.

    Usage:
        &testmail                    - Send to admin's own email
        &testmail user@example.com   - Send to specific email
        &testmail user@example.com smtp    - Force SMTP provider
        &testmail user@example.com mailgun - Force Mailgun provider
    """
    email_service = get_service(EmailService)
    if not email_service:
        await message.answer("❌ Email service not available")
        return

    reply = await message.answer("🔄 Testing email...")

    try:
        # Parse command
        parts = message.text.split()
        target_email = user.email if len(parts) == 1 else parts[1]
        forced_provider = parts[2].lower() if len(parts) > 2 else None

        if not target_email:
            await reply.edit_text("❌ No email address. Set your email or provide one.")
            return

        if forced_provider and forced_provider not in ['smtp', 'mailgun']:
            await reply.edit_text("❌ Invalid provider. Use: smtp or mailgun")
            return

        # Select provider
        if forced_provider:
            selected_provider = forced_provider
        else:
            provider_order = email_service._select_provider_for_email(target_email)
            if not provider_order:
                await reply.edit_text("❌ No available email providers")
                return
            selected_provider = provider_order[0]

        # Send test email
        provider = email_service.providers.get(selected_provider)
        if not provider:
            await reply.edit_text(f"❌ Provider {selected_provider} not available")
            return

        success = await provider.send_email(
            to=target_email,
            subject=f"[JetUp Test] Email from {selected_provider.upper()}",
            html_body=f"""
                <h2>Test Email</h2>
                <p>This is a test email sent via <b>{selected_provider.upper()}</b>.</p>
                <p>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
                <p>Requested by: {user.firstname} (ID: {user.userID})</p>
            """,
            text_body=None
        )

        if success:
            await reply.edit_text(
                f"✅ Test email sent!\n\n"
                f"📧 To: {target_email}\n"
                f"📤 Provider: {selected_provider.upper()}"
            )
        else:
            await reply.edit_text(
                f"❌ Failed to send email\n\n"
                f"📧 To: {target_email}\n"
                f"📤 Provider: {selected_provider.upper()}"
            )

    except Exception as e:
        logger.error(f"Error in &testmail: {e}", exc_info=True)
        await reply.edit_text(f"❌ Error: {str(e)}")


# =============================================================================
# UNKNOWN COMMAND HANDLER
# =============================================================================

@legacy_router.message(F.text.startswith('&'))
async def cmd_unknown(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Handle unknown admin commands - show help."""
    command = message.text.strip()
    logger.info(f"Admin {message.from_user.id} requested unknown command: {command}")

    help_text = """
<b>📋 Available Admin Commands:</b>

<b>Configuration:</b>
• <code>&upconfig</code> - Update Projects/Options
• <code>&stats</code> - Show bot statistics
• <code>&testmail [email] [provider]</code> - Test email

<b>Coming soon:</b>
• <code>&upro</code> - Update Projects + BookStack
• <code>&ut</code> - Update Templates
• <code>&import</code> - Sync from Google Sheets
• <code>&addbalance</code> - Adjust user balance
• <code>&time</code> - Time Machine control
"""

    await message.answer(help_text, parse_mode="HTML")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = ['legacy_router']