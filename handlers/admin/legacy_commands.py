# handlers/admin/legacy_commands.py
"""
Legacy user migration command.

Commands:
    &legacy - Run legacy user migration from Google Sheets
"""
import logging

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from models.user import User

logger = logging.getLogger(__name__)

legacy_router = Router(name="admin_legacy")


@legacy_router.message(F.text == '&legacy')
async def cmd_legacy(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Run legacy user migration manually."""
    from background.legacy_processor import legacy_processor

    logger.info(f"Admin {message.from_user.id} triggered &legacy")

    reply = await message.reply("🔄 Запускаю legacy миграцию...")

    try:
        stats = await legacy_processor._process_legacy_users()

        report = (
            f"📊 Legacy Migration Report:\n\n"
            f"📋 Total records: {stats.total_records}\n"
            f"👤 Users found: {stats.users_found}\n"
            f"👥 Upliners assigned: {stats.upliners_assigned}\n"
            f"📈 Purchases created: {stats.purchases_created}\n"
            f"✅ Completed: {stats.completed}\n"
            f"❌ Errors: {stats.errors}\n"
        )

        if stats.users_found == 0 and stats.upliners_assigned == 0 and stats.purchases_created == 0:
            report += "\n🔍 No new legacy users found to process."
        else:
            report += "\n🎯 Legacy migration processing completed!"

        if stats.errors > 0 and stats.error_details:
            report += "\n\n⚠️ Error details (first 10):\n"
            for email, error in stats.error_details[:10]:
                report += f"• {email}: {error}\n"

        await reply.edit_text(report)

    except RuntimeError as e:
        if "already in progress" in str(e):
            await reply.edit_text(
                "⚠️ Миграция уже запущена.\n"
                "Автоматический запуск каждые 10 минут."
            )
        else:
            raise

    except Exception as e:
        logger.error(f"Error in &legacy: {e}", exc_info=True)
        await reply.edit_text(f"❌ Ошибка: {str(e)}")


__all__ = ['legacy_router']