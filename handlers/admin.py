# jetup/handlers/admin.py
"""
Administrative commands for Jetup bot.
"""
import logging
from typing import Any, Callable, Awaitable
from aiogram import Router, Bot, F, Dispatcher
from aiogram.types import Message, TelegramObject, CallbackQuery
from aiogram import BaseMiddleware

from core.message_manager import MessageManager
from core.user_decorator import with_user
from models.user import User
from services.imports import import_projects_and_options
from services.stats_service import StatsService
from core.di import get_service
from config import Config

logger = logging.getLogger(__name__)

admin_router = Router(name="admin_router")


class AdminMiddleware(BaseMiddleware):
    """Middleware to check admin permissions."""

    def __init__(self, bot: Bot):
        self.bot = bot
        super().__init__()

    async def __call__(
            self,
            handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: dict[str, Any]
    ) -> Any:
        data["bot"] = self.bot

        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id

            if isinstance(event, Message) and event.text and event.text.startswith('&'):
                logger.info(f"AdminMiddleware: processing command '{event.text}' from user {user_id}")

            # Get user from data (injected by UserMiddleware)
            user = data.get('user')

            if not user:
                logger.warning(f"User object not found for {user_id}")
                return None

            # Check if user is ADMIN
            admin_ids = Config.get(Config.ADMIN_USER_IDS, [])
            if user_id not in admin_ids:
                logger.warning(f"Non-admin user {user_id} attempted to access admin command")
                if isinstance(event, Message) and event.text:
                    await event.answer("⛔ You don't have permission to use admin commands.")
                return None

            if isinstance(event, Message) and event.text:
                logger.info(f"Admin {user_id} executed command: {event.text}")

        return await handler(event, data)


# ============================================================================
# CONFIGURATION COMMANDS
# ============================================================================

@admin_router.message(F.text == '&upconfig')
async def cmd_upconfig(
        message: Message,
        user: User,
        session,
        message_manager: MessageManager
):
    """
    Update configuration: reload Projects, Options, and refresh statistics.
    Admin-only command.
    """
    logger.info(f"Admin {message.from_user.id} triggered &upconfig")

    status_msg = await message.answer("🔄 Updating configuration...")

    try:
        # Import Projects and Options
        import_result = await import_projects_and_options()

        if import_result["success"]:
            result_text = (
                "✅ Configuration updated!\n\n"
                f"📦 Projects:\n"
                f"  • Added: {import_result['projects']['added']}\n"
                f"  • Updated: {import_result['projects']['updated']}\n"
                f"  • Errors: {import_result['projects']['errors']}\n\n"
                f"🎯 Options:\n"
                f"  • Added: {import_result['options']['added']}\n"
                f"  • Updated: {import_result['options']['updated']}\n"
                f"  • Errors: {import_result['options']['errors']}\n"
            )

            # Show errors if any
            if import_result["error_messages"]:
                error_summary = "\n".join(import_result["error_messages"][:5])
                result_text += f"\n⚠️ Errors:\n{error_summary}"
                if len(import_result["error_messages"]) > 5:
                    result_text += f"\n...and {len(import_result['error_messages']) - 5} more"
        else:
            result_text = "❌ Configuration update failed!"
            if import_result["error_messages"]:
                error_summary = "\n".join(import_result["error_messages"][:3])
                result_text += f"\n\nErrors:\n{error_summary}"

        # Refresh statistics
        stats_service = get_service(StatsService)
        if stats_service:
            await stats_service.refresh_all()
            result_text += "\n\n📊 Statistics refreshed"

        await status_msg.edit_text(result_text)

    except Exception as e:
        logger.error(f"Error in &upconfig: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


@admin_router.message(F.text == '&stats')
async def cmd_stats(message: Message, user: User, session, message_manager: MessageManager):
    """Show bot statistics."""
    stats_service = get_service(StatsService)
    if not stats_service:
        await message.answer("❌ Stats service not available")
        return

    try:
        users_count = await stats_service.get_users_count()
        projects_count = await stats_service.get_projects_count()
        purchases_total = await stats_service.get_purchases_total()

        stats_text = (
            "📊 <b>Bot Statistics</b>\n\n"
            f"👥 Users: {users_count:,}\n"
            f"🚀 Projects: {projects_count}\n"
            f"💰 Total Investments: ${purchases_total:,.2f}\n"
        )

        await message.answer(stats_text, parse_mode="HTML")

    except Exception as e:
        logger.error(f"Error in &stats: {e}", exc_info=True)
        await message.answer(f"❌ Error: {str(e)}")


# ============================================================================
# HELP COMMAND
# ============================================================================

@admin_router.message(F.text.startswith('&'))
async def cmd_unknown(message: Message, user: User, session, message_manager: MessageManager):
    """Handle unknown admin commands - show help."""
    command = message.text.strip()
    logger.info(f"Admin {message.from_user.id} requested unknown command: {command}")

    help_text = (
        "📋 <b>Available Admin Commands</b>\n\n"
        "&upconfig - Update Projects/Options from Google Sheets\n"
        "&stats - Show bot statistics\n"
    )

    await message.answer(help_text, parse_mode="HTML")


# ============================================================================
# SETUP FUNCTION
# ============================================================================

def setup_admin_handlers(dp: Dispatcher, bot: Bot):
    """Register admin handlers with middleware."""
    logger.info("Setting up admin handlers")
    admin_router.message.middleware(AdminMiddleware(bot))
    dp.include_router(admin_router)
    logger.info("Admin handlers have been set up")