# handlers/admin/legacy_commands.py
"""
Legacy user migration commands - SIMPLIFIED FOR NEW ARCHITECTURE

Commands:
    &legacy  - Run migration batch (processes both V1 and V2)

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


@legacy_router.message(F.text.startswith('&legacy'))
async def cmd_legacy(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Run legacy user migration manually.

    Usage:
        &legacy  - Process pending migrations (both V1 and V2)

    Architecture:
    - Most processing happens automatically on email verification
    - This command is a FALLBACK for:
      1. Users who registered before migration system deployed
      2. Retry failed migrations
      3. Manual testing

    Process:
    1. Check PostgreSQL for pending migrations
    2. Process users who verified email
    3. Assign upliners when they verify
    4. Create purchases/gifts as needed
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &legacy")

    # Show loading
    await message_manager.send_template(
        user=user,
        template_key='admin/legacy/loading',
        update=message
    )

    try:
        # Run migration batch
        stats = await legacy_processor.run_once()

        # Calculate totals
        total_v1 = stats.get('v1_processed', 0)
        total_v2 = stats.get('v2_processed', 0)
        total_uplines = stats.get('uplines_assigned', 0)
        total_errors = stats.get('errors', 0)
        total_processed = total_v1 + total_v2

        # Determine status message
        if total_processed == 0:
            status_message = "🔍 No pending legacy migrations found."
        else:
            status_message = "🎯 Legacy migration batch completed!"

        # Build errors line
        errors_line = ""
        if total_errors > 0:
            errors_line = f"❌ Errors: {total_errors}"

        # Send report
        await message_manager.send_template(
            user=user,
            template_key='admin/legacy/report',
            variables={
                'status_message': status_message,
                'v1_processed': total_v1,
                'v2_processed': total_v2,
                'upliners_assigned': total_uplines,
                'errors_line': errors_line
            },
            update=message
        )

    except RuntimeError as e:
        if "already in progress" in str(e):
            await message_manager.send_template(
                user=user,
                template_key='admin/legacy/in_progress',
                update=message,
                edit=True
            )
        else:
            raise

    except Exception as e:
        logger.error(f"Error in &legacy command: {e}", exc_info=True)

        await message_manager.send_template(
            user=user,
            template_key='admin/legacy/error',
            variables={'error': str(e)},
            update=message,
            edit=True
        )