# handlers/admin/legacy_commands.py
"""
Legacy user migration commands.

Commands:
    &legacy       - Run original V1 migration (default)
    &legacy v2    - Run V2 migration only

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
        &legacy       - Run original V1 migration (default)
        &legacy v2    - Run V2 migration only

    This command triggers the legacy processor to:

    V1 (Original - Default):
    1. Read users from LEGACY_SHEET_ID Google Sheet
    2. Match them with existing users by email
    3. Assign uplines and create purchases
    4. Mark records as processed

    V2 (Return of Jedi - requires "v2" argument):
    1. Read users from LEGACY_V2_SHEET_ID Google Sheet
    2. Match them with existing users by email
    3. Assign uplines
    4. Grant double gifts (JETUP + AQUIX options)
    5. Mark records as processed
    """
    if not is_admin(message.from_user.id):
        return

    # Parse command argument
    args = message.text.split()
    migration_filter = None

    if len(args) > 1:
        arg = args[1].lower()
        if arg in ['v2', '2']:
            migration_filter = 'v2'
        # No v1 filter - default behavior is V1 anyway

    logger.info(f"Admin {message.from_user.id} triggered &legacy (filter: {migration_filter or 'default'})")

    # Show loading
    status_msg = await message_manager.send_template(
        user=user,
        template_key='admin/legacy/loading',
        variables={'migration': migration_filter or 'default'},
        update=message
    )

    try:
        # Run migration
        stats = await legacy_processor.run_once(migration=migration_filter)

        # Determine status message
        if migration_filter == 'v2':
            # V2 migration
            if stats.v2_users_found == 0 and stats.v2_upliners_assigned == 0 and stats.v2_gifts_granted == 0:
                status_message = "🔍 No new V2 legacy users found to process."
            else:
                status_message = "🎯 V2 Legacy migration processing completed!"
        else:
            # V1 migration (default)
            if stats.users_found == 0 and stats.upliners_assigned == 0 and stats.purchases_created == 0:
                status_message = "🔍 No new legacy users found to process."
            else:
                status_message = "🎯 Legacy migration processing completed!"

        # Build detailed report
        report_lines = [status_message, ""]

        # V1 stats (shown by default, not shown for v2 filter)
        if migration_filter != 'v2':
            if stats.total_records > 0:
                report_lines.append("📊 **Migration V1 (Original):**")
                report_lines.append(f"• Total processed: {stats.total_records}")
                report_lines.append(f"• Users found: {stats.users_found}")
                report_lines.append(f"• Upliners assigned: {stats.upliners_assigned}")
                report_lines.append(f"• Purchases created: {stats.purchases_created}")
                report_lines.append(f"• Completed: {stats.completed}")
                if stats.errors > 0:
                    report_lines.append(f"• ⚠️ Errors: {stats.errors}")
                report_lines.append("")

        # V2 stats (shown only when v2 filter is used)
        if migration_filter == 'v2':
            if stats.v2_total > 0:
                report_lines.append("📊 **Migration V2 (Return of Jedi):**")
                report_lines.append(f"• Total processed: {stats.v2_total}")
                report_lines.append(f"• Users found: {stats.v2_users_found}")
                report_lines.append(f"• Upliners assigned: {stats.v2_upliners_assigned}")
                report_lines.append(f"• Gifts granted: {stats.v2_gifts_granted}")
                report_lines.append(f"• Completed: {stats.v2_completed}")
                if stats.v2_errors > 0:
                    report_lines.append(f"• ⚠️ Errors: {stats.v2_errors}")
                report_lines.append("")

        # Error details
        total_errors = stats.errors if migration_filter != 'v2' else stats.v2_errors
        if total_errors > 0:
            report_lines.append("❌ **Errors:**")
            for email, error in stats.error_details[:5]:  # Show first 5
                report_lines.append(f"• {email}: {error[:50]}...")

            if len(stats.error_details) > 5:
                report_lines.append(f"• ... and {len(stats.error_details) - 5} more")

        report_text = "\n".join(report_lines)

        # Send report
        await message_manager.send_template(
            user=user,
            template_key='admin/legacy/report',
            variables={
                'report': report_text,
                'total_records': stats.total_records if migration_filter != 'v2' else stats.v2_total,
                'users_found': stats.users_found if migration_filter != 'v2' else stats.v2_users_found,
                'upliners_assigned': stats.upliners_assigned if migration_filter != 'v2' else stats.v2_upliners_assigned,
                'purchases_created': stats.purchases_created if migration_filter != 'v2' else stats.v2_gifts_granted,
                'completed': stats.completed if migration_filter != 'v2' else stats.v2_completed,
                'errors': stats.errors if migration_filter != 'v2' else stats.v2_errors,
                'status_message': status_message
            },
            update=message,
            edit=True
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