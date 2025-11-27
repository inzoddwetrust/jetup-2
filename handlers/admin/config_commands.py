# handlers/admin/config_commands.py
"""
Configuration management commands for admins.

Commands:
    &upconfig - Reload configuration from Google Sheets "Config" tab
    &upro     - Reload Projects + Options + clear BookStack cache
    &ut       - Reload message templates from Google Sheets "Templates" tab
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
    1. ConfigImporter.import_config() - loads all key-value pairs
    2. Config.set() for each variable
    3. EmailService.reload_secure_domains() - refresh email routing
    4. Show report with loaded variables
    """
    logger.info(f"Admin {message.from_user.id} triggered &upconfig")

    status_msg = await message.answer("🔄 Loading configuration from Google Sheets...")

    try:
        # 1. Load configuration from Google Sheets
        from services.data_importer import ConfigImporter

        config_dict = await ConfigImporter.import_config(
            sheet_id=Config.get(Config.GOOGLE_SHEET_ID),
            sheet_name="Config"
        )

        if not config_dict:
            await status_msg.edit_text("⚠️ Config sheet is empty or failed to load.")
            return

        # 2. Update Config with loaded values
        for key, value in config_dict.items():
            Config.set(key, value)

        # 3. Reload EmailService secure domains (if service available)
        email_service = get_service(EmailService)
        email_reloaded = False
        if email_service:
            try:
                email_service.reload_secure_domains()
                email_reloaded = True
                logger.info("Email secure domains reloaded")
            except Exception as e:
                logger.warning(f"Could not reload email secure domains: {e}")

        # 4. Format report
        config_items = []
        for key, value in config_dict.items():
            # Truncate long values for display
            if isinstance(value, (dict, list)):
                value_str = f"<{type(value).__name__}>"
            else:
                value_str = str(value)
                if len(value_str) > 40:
                    value_str = value_str[:37] + "..."
            config_items.append(f"• {key}: {value_str}")

        report_text = (
            f"✅ Configuration updated!\n\n"
            f"📋 Loaded {len(config_dict)} variables:\n"
            f"{chr(10).join(config_items)}"
        )

        if email_reloaded:
            report_text += "\n\n📧 Email secure domains refreshed"

        await status_msg.edit_text(report_text)
        logger.info(f"Config updated by admin {message.from_user.id}: {len(config_dict)} variables")

    except Exception as e:
        logger.error(f"Error in &upconfig: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


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
    1. TemplateCache.clear() - clear BookStack HTML cache
    2. import_projects_and_options() - import from GS
    3. Config.refresh_all_dynamic() - recalculate statistics
    4. Show report
    """
    logger.info(f"Admin {message.from_user.id} triggered &upro")

    status_msg = await message.answer("🔄 Updating Projects and Options...")

    try:
        # 1. Clear BookStack cache
        from services.document.bookstack_service import TemplateCache
        TemplateCache.clear()
        logger.info("BookStack template cache cleared")

        # 2. Import Projects and Options
        from services.imports import import_projects_and_options
        import_result = await import_projects_and_options()

        if not import_result["success"]:
            error_summary = "\n".join(import_result["error_messages"][:3])
            await status_msg.edit_text(f"❌ Import failed!\n\n{error_summary}")
            return

        # 3. Refresh dynamic statistics
        await Config.refresh_all_dynamic()
        logger.info("Dynamic statistics refreshed")

        # 4. Format report
        result_text = (
            "✅ Projects and Options updated!\n\n"
            f"📦 Projects:\n"
            f"  • Added: {import_result['projects']['added']}\n"
            f"  • Updated: {import_result['projects']['updated']}\n"
            f"  • Errors: {import_result['projects']['errors']}\n\n"
            f"🎯 Options:\n"
            f"  • Added: {import_result['options']['added']}\n"
            f"  • Updated: {import_result['options']['updated']}\n"
            f"  • Errors: {import_result['options']['errors']}\n\n"
            f"🗑 BookStack cache cleared\n"
            f"📊 Statistics refreshed"
        )

        # Show errors if any
        if import_result["error_messages"]:
            error_summary = "\n".join(import_result["error_messages"][:5])
            result_text += f"\n\n⚠️ Errors:\n{error_summary}"
            if len(import_result["error_messages"]) > 5:
                result_text += f"\n...and {len(import_result['error_messages']) - 5} more"

        await status_msg.edit_text(result_text)
        logger.info(f"Projects/Options updated by admin {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error in &upro: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


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
    1. MessageTemplates.load_templates() - reload from GS
    2. Show count of loaded templates
    """
    logger.info(f"Admin {message.from_user.id} triggered &ut")

    status_msg = await message.answer("🔄 Reloading templates...")

    try:
        from core.templates import MessageTemplates

        # Load templates from Google Sheets
        await MessageTemplates.load_templates()

        # Get count
        templates_count = len(MessageTemplates._cache)

        await status_msg.edit_text(
            f"✅ Templates reloaded!\n\n"
            f"📝 Loaded {templates_count} templates"
        )
        logger.info(f"Templates reloaded by admin {message.from_user.id}: {templates_count} templates")

    except Exception as e:
        logger.error(f"Error in &ut: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = ['config_router']