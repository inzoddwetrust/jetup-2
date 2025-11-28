# handlers/admin/config_commands.py
"""
Configuration management commands for admins.

Commands:
    &upconfig - Reload configuration from Google Sheets "Config" tab
    &upro     - Reload Projects + Options + clear BookStack cache
    &ut       - Reload message templates from Google Sheets "Templates" tab

Templates used:
    admin/upconfig/loading, admin/upconfig/success, admin/upconfig/empty, admin/upconfig/error
    admin/upro/loading, admin/upro/success, admin/upro/error
    admin/ut/loading, admin/ut/success, admin/ut/error
"""
import logging

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from config import Config
from core.di import get_service
from core.message_manager import MessageManager
from models.user import User
from email_system import EmailService

logger = logging.getLogger(__name__)

# =============================================================================
# ROUTER SETUP
# =============================================================================

config_router = Router(name="admin_config")


# =============================================================================
# ADMIN CHECK
# =============================================================================

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    return user_id in admins


# =============================================================================
# &upconfig - Reload Config from Google Sheets
# =============================================================================

@config_router.message(F.text == '&upconfig')
async def cmd_upconfig(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Reload configuration variables from Google Sheets "Config" tab.

    Flow:
    1. Show loading message
    2. ConfigImporter.import_config() - loads all key-value pairs
    3. Config.set() for each variable
    4. EmailService.reload_secure_domains() - refresh email routing
    5. Show success/error via template
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &upconfig")

    # 1. Show loading
    status_msg = await message_manager.send_template(
        user=user,
        template_key='admin/upconfig/loading',
        update=message
    )

    try:
        # 2. Load configuration from Google Sheets
        from services.data_importer import ConfigImporter

        config_dict = await ConfigImporter.import_config(
            sheet_id=Config.get(Config.GOOGLE_SHEET_ID),
            sheet_name="Config"
        )

        if not config_dict:
            await message_manager.send_template(
                user=user,
                template_key='admin/upconfig/empty',
                update=status_msg,
                edit=True
            )
            return

        # 3. Update Config with loaded values
        for key, value in config_dict.items():
            Config.set(key, value)

        # 4. Reload EmailService secure domains (if service available)
        email_service = get_service(EmailService)
        email_status = ""
        if email_service:
            try:
                email_service.reload_secure_domains()
                email_status = "📧 Email secure domains refreshed"
                logger.info("Email secure domains reloaded")
            except Exception as e:
                email_status = f"⚠️ Email reload failed: {e}"
                logger.warning(f"Could not reload email secure domains: {e}")

        # 5. Format items list for display
        items_list = []
        for key, value in config_dict.items():
            if isinstance(value, (dict, list)):
                value_str = f"<{type(value).__name__}>"
            else:
                value_str = str(value)
                if len(value_str) > 40:
                    value_str = value_str[:37] + "..."
            items_list.append(f"• {key}: {value_str}")

        # 6. Show success
        await message_manager.send_template(
            user=user,
            template_key='admin/upconfig/success',
            variables={
                'count': len(config_dict),
                'items': '\n'.join(items_list),
                'email_status': email_status
            },
            update=status_msg,
            edit=True
        )

        logger.info(f"Config updated by admin {message.from_user.id}: {len(config_dict)} variables")

    except Exception as e:
        logger.error(f"Error in &upconfig: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/upconfig/error',
            variables={'error': str(e)},
            update=status_msg,
            edit=True
        )


# =============================================================================
# &upro - Reload Projects + Options + BookStack cache
# =============================================================================

@config_router.message(F.text == '&upro')
async def cmd_upro(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Reload Projects and Options from Google Sheets.

    Flow:
    1. Show loading message
    2. TemplateCache.clear() - clear BookStack HTML cache
    3. import_projects_and_options() - import from GS
    4. Config.refresh_all_dynamic() - recalculate statistics
    5. Show success/error via template
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &upro")

    # 1. Show loading
    status_msg = await message_manager.send_template(
        user=user,
        template_key='admin/upro/loading',
        update=message
    )

    try:
        # 2. Clear BookStack cache
        from services.document.bookstack_service import TemplateCache
        TemplateCache.clear()
        logger.info("BookStack template cache cleared")

        # 3. Import Projects and Options
        from services.imports import import_projects_and_options
        import_result = await import_projects_and_options()

        if not import_result["success"]:
            errors = "\n".join(import_result["error_messages"][:5])
            await message_manager.send_template(
                user=user,
                template_key='admin/upro/error',
                variables={'errors': errors},
                update=status_msg,
                edit=True
            )
            return

        # 4. Refresh dynamic statistics
        await Config.refresh_all_dynamic()
        logger.info("Dynamic statistics refreshed")

        # 5. Show success
        await message_manager.send_template(
            user=user,
            template_key='admin/upro/success',
            variables={
                'projects_added': import_result['projects']['added'],
                'projects_updated': import_result['projects']['updated'],
                'projects_errors': import_result['projects']['errors'],
                'options_added': import_result['options']['added'],
                'options_updated': import_result['options']['updated'],
                'options_errors': import_result['options']['errors']
            },
            update=status_msg,
            edit=True
        )

        logger.info(f"Projects/Options updated by admin {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error in &upro: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/upro/error',
            variables={'errors': str(e)},
            update=status_msg,
            edit=True
        )


# =============================================================================
# &ut - Reload Templates from Google Sheets
# =============================================================================

@config_router.message(F.text == '&ut')
async def cmd_ut(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Reload message templates from Google Sheets "Templates" tab.

    Flow:
    1. Show loading message
    2. MessageTemplates.load_templates() - reload from GS
    3. Show success with count
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &ut")

    # 1. Show loading
    status_msg = await message_manager.send_template(
        user=user,
        template_key='admin/ut/loading',
        update=message
    )

    try:
        # 2. Load templates from Google Sheets
        from core.templates import MessageTemplates
        await MessageTemplates.load_templates()

        # 3. Get count and show success
        templates_count = len(MessageTemplates._cache)

        await message_manager.send_template(
            user=user,
            template_key='admin/ut/success',
            variables={'count': templates_count},
            update=status_msg,
            edit=True
        )

        logger.info(f"Templates reloaded by admin {message.from_user.id}: {templates_count} templates")

    except Exception as e:
        logger.error(f"Error in &ut: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/ut/error',
            variables={'error': str(e)},
            update=status_msg,
            edit=True
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = ['config_router']