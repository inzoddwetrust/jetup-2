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
import os
import re
import glob
from typing import Set, Tuple

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
# &ut - Reload Templates + Validation
# =============================================================================

@config_router.message(F.text.regexp(r'^&ut(\s+--validate)?$'))
async def cmd_ut(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Reload message templates from Google Sheets "Templates" tab.

    Usage:
        &ut           - Just reload templates
        &ut --validate - Reload + validate against code

    Validation checks:
        1. Templates used in code but missing in Google Sheets
        2. Templates in Google Sheets but never used in code
        3. Callbacks in Google Sheets but no handler in code
    """
    logger.info(f"Admin {message.from_user.id} triggered &ut")

    do_validate = '--validate' in message.text

    status_msg = await message.answer("🔄 Reloading templates...")

    try:
        from core.templates import MessageTemplates

        # Load templates from Google Sheets
        await MessageTemplates.load_templates()

        # Get count
        templates_count = len(MessageTemplates._cache)
        unique_keys = len(set(k[0] for k in MessageTemplates._cache.keys()))

        result_text = (
            f"✅ Templates reloaded!\n\n"
            f"📝 Total: {templates_count} templates\n"
            f"🔑 Unique keys: {unique_keys}"
        )

        if not do_validate:
            result_text += "\n\n💡 Use <code>&ut --validate</code> to check consistency"
            await status_msg.edit_text(result_text, parse_mode="HTML")
            return

        # Run validation
        await status_msg.edit_text("🔄 Validating templates against code...")

        validation_result = await validate_templates_consistency(MessageTemplates._cache)

        result_text = format_validation_report(validation_result, unique_keys)

        await status_msg.edit_text(result_text, parse_mode="HTML")
        logger.info(f"Templates validated by admin {message.from_user.id}")

    except Exception as e:
        logger.error(f"Error in &ut: {e}", exc_info=True)
        await status_msg.edit_text(f"❌ Error: {str(e)}")


# =============================================================================
# TEMPLATE VALIDATION LOGIC
# =============================================================================

# Directories to scan for template usage
SCAN_DIRECTORIES = [
    'handlers',
    'mlm_system',
    'core',
    'services',
    'email_system',
    'background',
    'actions',
]

# File extensions to scan
FILE_EXTENSIONS = ['*.py']

# Regex patterns to find template keys in code
TEMPLATE_KEY_PATTERNS = [
    # template_key='...' or template_key="..."
    r'template_key\s*=\s*[\'"]([^\'"]+)[\'"]',
    # template_key=['...', '...']
    r'template_key\s*=\s*\[([^\]]+)\]',
    # state_key='...' or state_key="..."
    r'state_key\s*=\s*[\'"]([^\'"]+)[\'"]',
    # get_raw_template('...'
    r'get_raw_template\s*\(\s*[\'"]([^\'"]+)[\'"]',
    # get_template('...'
    r'get_template\s*\(\s*[\'"]([^\'"]+)[\'"]',
    # generate_screen(...state_keys='...'
    r'state_keys\s*=\s*[\'"]([^\'"]+)[\'"]',
    # INFO_SCREENS dict keys and template_key values
    r'"template_key"\s*:\s*[\'"]([^\'"]+)[\'"]',
]

# Regex patterns to find callback handlers in code
CALLBACK_PATTERNS = [
    # F.data == "exact"
    r'F\.data\s*==\s*[\'"]([^\'"]+)[\'"]',
    # F.data.startswith("prefix")
    r'F\.data\.startswith\s*\(\s*[\'"]([^\'"]+)[\'"]',
    # F.data.in_([...])
    r'F\.data\.in_\s*\(\s*\[([^\]]+)\]',
    # F.data.regexp(r"pattern")
    r'F\.data\.regexp\s*\(\s*r?[\'"]([^\'"]+)[\'"]',
    # lambda c: c.data == "..."
    r'lambda\s+\w+\s*:\s*\w+\.data\s*==\s*[\'"]([^\'"]+)[\'"]',
    # lambda c: c.data.startswith("...")
    r'lambda\s+\w+\s*:\s*\w+\.data\.startswith\s*\(\s*[\'"]([^\'"]+)[\'"]',
    # lambda c: "..." in c.data
    r'lambda\s+\w+\s*:\s*[\'"]([^\'"]+)[\'"]\s+in\s+\w+\.data',
]


async def validate_templates_consistency(cache: dict) -> dict:
    """
    Validate template consistency between code and Google Sheets.

    Returns:
        dict with validation results
    """
    # Extract unique template keys from cache (without lang)
    cached_keys = set(k[0] for k in cache.keys())

    # Extract callbacks from templates
    cached_callbacks = extract_callbacks_from_templates(cache)

    # Scan code for template usage
    code_templates, code_callbacks, dynamic_templates = scan_code_for_templates()

    # Find mismatches
    missing_in_sheets = code_templates - cached_keys - dynamic_templates
    unused_in_code = cached_keys - code_templates

    # For callbacks, we need smarter matching (prefix/regex patterns)
    unhandled_callbacks = find_unhandled_callbacks(cached_callbacks, code_callbacks)

    return {
        'cached_keys': len(cached_keys),
        'code_templates': len(code_templates),
        'dynamic_templates': dynamic_templates,
        'missing_in_sheets': sorted(missing_in_sheets),
        'unused_in_code': sorted(unused_in_code),
        'cached_callbacks': len(cached_callbacks),
        'unhandled_callbacks': sorted(unhandled_callbacks)[:20],  # Limit to 20
        'unhandled_callbacks_total': len(unhandled_callbacks),
    }


def scan_code_for_templates() -> Tuple[Set[str], Set[str], Set[str]]:
    """
    Scan code files for template keys and callback patterns.

    Returns:
        Tuple of (template_keys, callback_patterns, dynamic_templates)
    """
    template_keys = set()
    callback_patterns = set()
    dynamic_templates = set()

    # Get project root (assuming we're running from project root)
    project_root = os.getcwd()

    for directory in SCAN_DIRECTORIES:
        dir_path = os.path.join(project_root, directory)
        if not os.path.exists(dir_path):
            continue

        for ext in FILE_EXTENSIONS:
            pattern = os.path.join(dir_path, '**', ext)
            for filepath in glob.glob(pattern, recursive=True):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()

                    # Find template keys
                    for pattern_re in TEMPLATE_KEY_PATTERNS:
                        matches = re.findall(pattern_re, content)
                        for match in matches:
                            # Check if it's a list pattern
                            if ',' in match and '[' not in match:
                                # Parse list items
                                items = re.findall(r'[\'"]([^\'"]+)[\'"]', match)
                                template_keys.update(items)
                            else:
                                # Check for f-string / dynamic
                                if '{' in match or '+' in match:
                                    dynamic_templates.add(f"[DYNAMIC] {match}")
                                else:
                                    template_keys.add(match)

                    # Find callback patterns
                    for pattern_re in CALLBACK_PATTERNS:
                        matches = re.findall(pattern_re, content)
                        for match in matches:
                            if ',' in match:
                                # List of callbacks
                                items = re.findall(r'[\'"]([^\'"]+)[\'"]', match)
                                callback_patterns.update(items)
                            else:
                                callback_patterns.add(match)

                except Exception as e:
                    logger.warning(f"Error scanning {filepath}: {e}")

    return template_keys, callback_patterns, dynamic_templates


def extract_callbacks_from_templates(cache: dict) -> Set[str]:
    """
    Extract callback_data values from template buttons.

    Buttons format examples:
        "Buy|callback:buy_123"
        "Confirm|callback:confirm_{id}"
    """
    callbacks = set()

    for (key, lang), template in cache.items():
        buttons = template.get('buttons', '')
        if not buttons:
            continue

        # Find callback patterns in buttons
        # Format: text|callback:callback_data
        matches = re.findall(r'callback:([^|;\n\]]+)', str(buttons))
        for match in matches:
            match = match.strip()
            if match:
                callbacks.add(match)

    return callbacks


def find_unhandled_callbacks(template_callbacks: Set[str], code_callbacks: Set[str]) -> Set[str]:
    """
    Find callbacks defined in templates but not handled in code.

    Uses smart matching:
    - Exact match
    - Prefix match (code has startswith pattern)
    - Regex match
    """
    unhandled = set()

    for callback in template_callbacks:
        # Skip dynamic callbacks (with {variables})
        if '{' in callback:
            continue

        is_handled = False

        # Check exact match
        if callback in code_callbacks:
            is_handled = True
        else:
            # Check prefix match
            for code_cb in code_callbacks:
                # If code callback is a prefix
                if callback.startswith(code_cb):
                    is_handled = True
                    break
                # If code callback is a regex pattern
                try:
                    if re.match(code_cb, callback):
                        is_handled = True
                        break
                except re.error:
                    pass

        if not is_handled:
            unhandled.add(callback)

    return unhandled


def format_validation_report(result: dict, total_keys: int) -> str:
    """Format validation results as HTML report."""

    lines = [
        f"✅ <b>Templates reloaded!</b>\n",
        f"📝 Total: {result['cached_keys']} unique keys",
        f"🔍 Found in code: {result['code_templates']} keys",
        ""
    ]

    # Missing in sheets (critical)
    if result['missing_in_sheets']:
        lines.append(f"❌ <b>Missing in Google Sheets ({len(result['missing_in_sheets'])}):</b>")
        for key in result['missing_in_sheets'][:10]:
            lines.append(f"  • <code>{key}</code>")
        if len(result['missing_in_sheets']) > 10:
            lines.append(f"  ... and {len(result['missing_in_sheets']) - 10} more")
        lines.append("")
    else:
        lines.append("✅ All code templates exist in Sheets")
        lines.append("")

    # Dynamic templates (info)
    if result['dynamic_templates']:
        lines.append(f"ℹ️ <b>Dynamic templates ({len(result['dynamic_templates'])}):</b>")
        for key in list(result['dynamic_templates'])[:5]:
            lines.append(f"  • <code>{key}</code>")
        if len(result['dynamic_templates']) > 5:
            lines.append(f"  ... and {len(result['dynamic_templates']) - 5} more")
        lines.append("")

    # Unused in code (warning)
    if result['unused_in_code']:
        lines.append(f"⚠️ <b>Possibly unused ({len(result['unused_in_code'])}):</b>")
        for key in result['unused_in_code'][:10]:
            lines.append(f"  • <code>{key}</code>")
        if len(result['unused_in_code']) > 10:
            lines.append(f"  ... and {len(result['unused_in_code']) - 10} more")
        lines.append("")
    else:
        lines.append("✅ No obviously unused templates")
        lines.append("")

    # Unhandled callbacks
    if result['unhandled_callbacks']:
        lines.append(f"⚠️ <b>Unhandled callbacks ({result['unhandled_callbacks_total']}):</b>")
        for cb in result['unhandled_callbacks'][:10]:
            lines.append(f"  • <code>{cb}</code>")
        if result['unhandled_callbacks_total'] > 10:
            lines.append(f"  ... and {result['unhandled_callbacks_total'] - 10} more")
    else:
        lines.append("✅ All callbacks have handlers")

    return "\n".join(lines)


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = ['config_router']