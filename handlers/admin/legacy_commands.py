# handlers/admin/legacy_commands.py
"""
Legacy user migration command.

Commands:
    &legacy - Run legacy user migration from Google Sheets

Templates used:
    admin/legacy/loading
    admin/legacy/report
    admin/legacy/in_progress
    admin/legacy/error
"""
import logging

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from core.message_manager import MessageManager
from models.user import User
from background.legacy_processor import legacy_processor

logger = logging.getLogger(__name__)

legacy_router = Router(name="admin_legacy")


def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    from config import Config
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    return user_id in admins


@legacy_router.message(F.text == '&legacy')
async def cmd_legacy(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Run legacy user migration manually.

    This command triggers the legacy processor to:
    1. Read users from LEGACY_SHEET_ID Google Sheet
    2. Match them with existing users by email
    3. Assign uplines and create purchases
    4. Mark records as processed
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &legacy")

    # Show loading
    status_msg = await message_manager.send_template(
        user=user,
        template_key='admin/legacy/loading',
        update=message
    )

    try:
        # Run migration
        if hasattr(legacy_processor, 'run_once'):
            stats = await legacy_processor.run_once()
        else:
            stats = await legacy_processor._process_legacy_users()

        # Determine status message
        if stats.users_found == 0 and stats.upliners_assigned == 0 and stats.purchases_created == 0:
            status_message = "🔍 No new legacy users found to process."
        else:
            status_message = "🎯 Legacy migration processing completed!"

        # Show report
        await message_manager.send_template(
            user=user,
            template_key='admin/legacy/report',
            variables={
                'total_records': stats.total_records,
                'users_found': stats.users_found,
                'upliners_assigned': stats.upliners_assigned,
                'purchases_created': stats.purchases_created,
                'completed': stats.completed,
                'errors': stats.errors,
                'status_message': status_message
            },
            update=status_msg,
            edit=True
        )

    except RuntimeError as e:
        if "already in progress" in str(e):
            await message_manager.send_template(
                user=user,
                template_key='admin/legacy/in_progress',
                update=status_msg,
                edit=True
            )
        else:
            raise

    except Exception as e:
        logger.error(f"Error in &legacy: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/legacy/error',
            variables={'error': str(e)},
            update=status_msg,
            edit=True
        )


__all__ = ['legacy_router']