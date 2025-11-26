# jetup/handlers/admin.py
"""
Administrative commands for Jetup bot.
"""
import logging
from typing import Any, Callable, Awaitable
from aiogram import Router, Bot, F, Dispatcher
from aiogram.types import Message, TelegramObject, CallbackQuery
from aiogram import BaseMiddleware
import re
from datetime import datetime, timezone
from email_system import EmailService

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
            await Config.refresh_all_dynamic()
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
# TESTMAIL COMMAND
# ============================================================================

@admin_router.message(F.text.startswith('&testmail'))
async def cmd_testmail(
        message: Message,
        user: User,
        session,
        bot: Bot,
        message_manager: MessageManager
):
    """
    Test email functionality with smart provider selection.

    Usage:
        &testmail                    - Send to admin's own email
        &testmail user@example.com   - Send to specific email
        &testmail user@example.com smtp    - Force SMTP provider
        &testmail user@example.com mailgun - Force Mailgun provider

    Admin-only command.
    """
    from core.di import get_service

    email_service = get_service(EmailService)
    if not email_service:
        await message.answer("❌ Email service not available")
        return

    reply = await message.answer("🔄 Loading...")

    try:
        # Parse command: &testmail [email] [provider]
        parts = message.text.split()
        custom_email = None
        forced_provider = None

        if len(parts) > 1:
            custom_email = parts[1]
        if len(parts) > 2:
            forced_provider = parts[2].lower()
            if forced_provider not in ['smtp', 'mailgun']:
                await message_manager.send_template(
                    user=user,
                    template_key='admin/testmail/invalid_provider',
                    variables={'provider': forced_provider},
                    update=reply,
                    edit=True
                )
                return

        # Validate custom email if provided
        if custom_email:
            if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', custom_email):
                await message_manager.send_template(
                    user=user,
                    template_key='admin/testmail/invalid_email',
                    variables={'email': custom_email},
                    update=reply,
                    edit=True
                )
                return

        # Check if providers configured
        if not email_service.providers:
            await message_manager.send_template(
                user=user,
                template_key='admin/testmail/no_providers',
                update=reply,
                edit=True
            )
            return

        # Show checking status
        await message_manager.send_template(
            user=user,
            template_key='admin/testmail/checking',
            update=reply,
            edit=True
        )

        # Test all providers
        providers_status = await email_service.get_providers_status()
        working_providers = [name for name, status in providers_status.items() if status]

        # Get config info
        config_info = email_service.get_config_info()

        # Build status report using modular templates
        template_keys = ['admin/testmail/header']

        for provider_name in providers_status.keys():
            if provider_name == 'smtp':
                template_keys.append('admin/testmail/status_smtp')
            elif provider_name == 'mailgun':
                template_keys.append('admin/testmail/status_mailgun')

        # Add secure domains info
        if email_service.secure_domains:
            template_keys.append('admin/testmail/secure_domains')
        else:
            template_keys.append('admin/testmail/no_secure_domains')

        # Determine target email
        if custom_email:
            target_email = custom_email
            # If admin tests their own email - use their name
            if user.email == custom_email:
                firstname = user.firstname or "Admin"
            else:
                firstname = "Test User"
        else:
            # Use admin's email
            if not user.email:
                template_keys.append('admin/testmail/no_user_email')

                await message_manager.send_template(
                    user=user,
                    template_key=template_keys,
                    variables={
                        'smtp_host': config_info['smtp']['host'],
                        'smtp_port': config_info['smtp']['port'],
                        'smtp_status': '✅ OK' if providers_status.get('smtp', False) else '❌ FAIL',
                        'mailgun_domain': config_info['mailgun']['domain'],
                        'mailgun_region': config_info['mailgun']['region'],
                        'mailgun_status': '✅ OK' if providers_status.get('mailgun', False) else '❌ FAIL',
                        'domains': ', '.join(email_service.secure_domains) if email_service.secure_domains else ''
                    },
                    update=reply,
                    edit=True
                )
                return

            target_email = user.email
            firstname = user.firstname or "Admin"

        # Determine which provider will be used
        if forced_provider:
            if forced_provider not in working_providers:
                template_keys.append('admin/testmail/provider_not_working')
                await message_manager.send_template(
                    user=user,
                    template_key=template_keys,
                    variables={
                        'smtp_host': config_info['smtp']['host'],
                        'smtp_port': config_info['smtp']['port'],
                        'smtp_status': '✅ OK' if providers_status.get('smtp', False) else '❌ FAIL',
                        'mailgun_domain': config_info['mailgun']['domain'],
                        'mailgun_region': config_info['mailgun']['region'],
                        'mailgun_status': '✅ OK' if providers_status.get('mailgun', False) else '❌ FAIL',
                        'domains': ', '.join(email_service.secure_domains) if email_service.secure_domains else '',
                        'provider': forced_provider.upper()
                    },
                    update=reply,
                    edit=True
                )
                return

            selected_provider = forced_provider
            template_keys.append('admin/testmail/reason_forced')
        else:
            provider_order = email_service._select_provider_for_email(target_email)
            if not provider_order:
                template_keys.append('admin/testmail/no_available_providers')
                await message_manager.send_template(
                    user=user,
                    template_key=template_keys,
                    variables={
                        'smtp_host': config_info['smtp']['host'],
                        'smtp_port': config_info['smtp']['port'],
                        'smtp_status': '✅ OK' if providers_status.get('smtp', False) else '❌ FAIL',
                        'mailgun_domain': config_info['mailgun']['domain'],
                        'mailgun_region': config_info['mailgun']['region'],
                        'mailgun_status': '✅ OK' if providers_status.get('mailgun', False) else '❌ FAIL',
                        'domains': ', '.join(email_service.secure_domains) if email_service.secure_domains else ''
                    },
                    update=reply,
                    edit=True
                )
                return

            selected_provider = provider_order[0]
            domain = email_service._get_email_domain(target_email)

            if domain in email_service.secure_domains:
                template_keys.append('admin/testmail/reason_secure')
            else:
                template_keys.append('admin/testmail/reason_regular')

        # Add sending status
        template_keys.append('admin/testmail/sending')

        # Send status message
        await message_manager.send_template(
            user=user,
            template_key=template_keys,
            variables={
                'smtp_host': config_info['smtp']['host'],
                'smtp_port': config_info['smtp']['port'],
                'smtp_status': '✅ OK' if providers_status.get('smtp', False) else '❌ FAIL',
                'mailgun_domain': config_info['mailgun']['domain'],
                'mailgun_region': config_info['mailgun']['region'],
                'mailgun_status': '✅ OK' if providers_status.get('mailgun', False) else '❌ FAIL',
                'domains': ', '.join(email_service.secure_domains) if email_service.secure_domains else '',
                'target_email': target_email,
                'provider': selected_provider.upper(),
                'domain': email_service._get_email_domain(target_email)
            },
            update=reply,
            edit=True
        )

        # Get email templates from Google Sheets
        from core.templates import MessageTemplates

        email_subject, _ = await MessageTemplates.get_raw_template(
            'admin/testmail/email_subject',
            {'provider': selected_provider.upper()},
            lang=user.lang or 'en'
        )

        email_body, _ = await MessageTemplates.get_raw_template(
            'admin/testmail/email_body',
            {
                'firstname': firstname,
                'target_email': target_email,
                'provider': selected_provider.upper(),
                'time': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            },
            lang=user.lang or 'en'
        )

        # Send test email
        provider = email_service.providers[selected_provider]
        success = await provider.send_email(
            to=target_email,
            subject=email_subject,
            html_body=email_body,
            text_body=None
        )

        # Build final status message
        if success:
            final_templates = ['admin/testmail/header']

            # Add provider statuses
            for provider_name in providers_status.keys():
                if provider_name == 'smtp':
                    final_templates.append('admin/testmail/status_smtp')
                elif provider_name == 'mailgun':
                    final_templates.append('admin/testmail/status_mailgun')

            # Add secure domains
            if email_service.secure_domains:
                final_templates.append('admin/testmail/secure_domains')
            else:
                final_templates.append('admin/testmail/no_secure_domains')

            # Add success message
            final_templates.append('admin/testmail/success')

            # Add fallback info if applicable
            fallback_provider = ''
            if not forced_provider:
                provider_order = email_service._select_provider_for_email(target_email)
                if len(provider_order) > 1:
                    final_templates.append('admin/testmail/fallback')
                    fallback_provider = provider_order[1].upper()

            await message_manager.send_template(
                user=user,
                template_key=final_templates,
                variables={
                    'smtp_host': config_info['smtp']['host'],
                    'smtp_port': config_info['smtp']['port'],
                    'smtp_status': '✅ OK' if providers_status.get('smtp', False) else '❌ FAIL',
                    'mailgun_domain': config_info['mailgun']['domain'],
                    'mailgun_region': config_info['mailgun']['region'],
                    'mailgun_status': '✅ OK' if providers_status.get('mailgun', False) else '❌ FAIL',
                    'domains': ', '.join(email_service.secure_domains) if email_service.secure_domains else '',
                    'target_email': target_email,
                    'provider': selected_provider.upper(),
                    'fallback_provider': fallback_provider
                },
                update=reply,
                edit=True
            )
        else:
            # Error message
            error_templates = ['admin/testmail/header']

            # Add provider statuses
            for provider_name in providers_status.keys():
                if provider_name == 'smtp':
                    error_templates.append('admin/testmail/status_smtp')
                elif provider_name == 'mailgun':
                    error_templates.append('admin/testmail/status_mailgun')

            # Add secure domains
            if email_service.secure_domains:
                error_templates.append('admin/testmail/secure_domains')
            else:
                error_templates.append('admin/testmail/no_secure_domains')

            error_templates.append('admin/testmail/send_error')

            await message_manager.send_template(
                user=user,
                template_key=error_templates,
                variables={
                    'smtp_host': config_info['smtp']['host'],
                    'smtp_port': config_info['smtp']['port'],
                    'smtp_status': '✅ OK' if providers_status.get('smtp', False) else '❌ FAIL',
                    'mailgun_domain': config_info['mailgun']['domain'],
                    'mailgun_region': config_info['mailgun']['region'],
                    'mailgun_status': '✅ OK' if providers_status.get('mailgun', False) else '❌ FAIL',
                    'domains': ', '.join(email_service.secure_domains) if email_service.secure_domains else '',
                    'target_email': target_email,
                    'provider': selected_provider.upper()
                },
                update=reply,
                edit=True
            )

    except Exception as e:
        logger.error(f"Error in &testmail command: {e}", exc_info=True)
        await message.answer(f"❌ Critical error: {str(e)}")


@admin_router.message(F.text.startswith('&'))
async def cmd_unknown(message: Message, user: User, session, message_manager: MessageManager):
    """Handle unknown admin commands - show help."""
    command = message.text.strip()
    logger.info(f"Admin {message.from_user.id} requested unknown command: {command}")

    await message_manager.send_template(
        user=user,
        template_key='admin/commands/help',
        update=message
    )


# ============================================================================
# SETUP FUNCTION
# ============================================================================

def setup_admin_handlers(dp: Dispatcher, bot: Bot):
    """Register admin handlers with middleware."""
    logger.info("Setting up admin handlers")
    admin_router.message.middleware(AdminMiddleware(bot))
    dp.include_router(admin_router)
    logger.info("Admin handlers have been set up")