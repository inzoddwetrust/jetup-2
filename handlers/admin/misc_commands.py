# handlers/admin/misc_commands.py
"""
Miscellaneous admin commands.

Commands:
    &stats    - Bot statistics
    &user     - Find user by ID/email/name
    &time     - Time Machine control
    &testmail - Test email sending
    &object   - Send media by file_id
    &help     - Show admin commands help
    &fallback - Handle unknown commands

Templates used:
    admin/stats/report, admin/stats/error
    admin/user/info, admin/user/not_found, admin/user/usage
    admin/time/status, admin/time/set, admin/time/reset, admin/time/error
    admin/testmail/* (full set from Talentir)
    admin/object/usage, admin/object/error
    admin/commands/help, admin/commands/unknown
"""
import re
import logging
from datetime import datetime, timezone
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import func
from sqlalchemy.orm import Session

from config import Config
from core.di import get_service
from core.message_manager import MessageManager
from core.templates import MessageTemplates
from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from models.payment import Payment
from email_system import EmailService

logger = logging.getLogger(__name__)

misc_router = Router(name="admin_misc")


# =============================================================================
# ADMIN CHECK
# =============================================================================

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    return user_id in admins


# =============================================================================
# &stats - Bot Statistics
# =============================================================================

@misc_router.message(F.text == '&stats')
async def cmd_stats(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show bot statistics."""
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &stats")

    try:
        # Gather statistics
        users_total = session.query(func.count(User.userID)).scalar() or 0
        users_active = session.query(func.count(User.userID)).filter(
            User.lastActive >= func.date('now', '-30 days')
        ).scalar() or 0

        # Active partners
        active_partners = 0
        for u in session.query(User).all():
            if u.mlmStatus and u.mlmStatus.get('isActive'):
                active_partners += 1

        # Financial stats
        deposits_total = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'paid'
        ).scalar() or Decimal('0')

        payments_pending = session.query(func.count(Payment.paymentID)).filter(
            Payment.status == 'check'
        ).scalar() or 0

        # Purchases
        purchases_count = session.query(func.count(Purchase.purchaseID)).scalar() or 0
        purchases_volume = session.query(func.sum(Purchase.packPrice)).scalar() or Decimal('0')

        # Bonuses
        bonuses_paid = session.query(func.sum(Bonus.amount)).filter(
            Bonus.status == 'paid'
        ).scalar() or Decimal('0')

        bonuses_pending = session.query(func.sum(Bonus.amount)).filter(
            Bonus.status == 'pending'
        ).scalar() or Decimal('0')

        # Time Machine status
        time_machine_status = ""
        try:
            from mlm_system.utils.time_machine import timeMachine
            if timeMachine.isTestMode:
                time_machine_status = f"⏰ Time Machine: {timeMachine.now().strftime('%Y-%m-%d %H:%M')}"
        except (ImportError, AttributeError):
            time_machine_status = ""

        await message_manager.send_template(
            user=user,
            template_key='admin/stats/report',
            variables={
                'users_total': users_total,
                'users_active': users_active,
                'active_partners': active_partners,
                'deposits_total': f"{float(deposits_total):,.2f}",
                'payments_pending': payments_pending,
                'purchases_count': purchases_count,
                'purchases_volume': f"{float(purchases_volume):,.2f}",
                'bonuses_paid': f"{float(bonuses_paid):,.2f}",
                'bonuses_pending': f"{float(bonuses_pending):,.2f}",
                'time_machine_status': time_machine_status
            },
            update=message
        )

    except Exception as e:
        logger.error(f"Error in &stats: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/stats/error',
            variables={'error': str(e)},
            update=message
        )


# =============================================================================
# &user - Find User
# =============================================================================

@misc_router.message(F.text.regexp(r'^&user\s+.+'))
async def cmd_user(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Find user by ID, telegramID, email, or name."""
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &user")

    query = message.text.split(maxsplit=1)[1].strip()
    found_user = None

    if query.startswith('@'):
        telegram_id = query[1:]
        if telegram_id.isdigit():
            found_user = session.query(User).filter_by(telegramID=int(telegram_id)).first()
    elif query.isdigit():
        found_user = session.query(User).filter_by(userID=int(query)).first()
    elif '@' in query:
        found_user = session.query(User).filter(
            func.lower(User.email) == query.lower()
        ).first()
    else:
        found_user = session.query(User).filter(
            func.lower(User.firstname).contains(query.lower())
        ).first()

    if not found_user:
        await message_manager.send_template(
            user=user,
            template_key='admin/user/not_found',
            variables={'query': query},
            update=message
        )
        return

    # Stats
    purchases_count = session.query(func.count(Purchase.purchaseID)).filter_by(
        userID=found_user.userID
    ).scalar() or 0
    purchases_sum = session.query(func.sum(Purchase.packPrice)).filter_by(
        userID=found_user.userID
    ).scalar() or Decimal('0')
    bonuses_earned = session.query(func.sum(Bonus.amount)).filter_by(
        userID=found_user.userID, status='paid'
    ).scalar() or Decimal('0')

    # Upline
    upline_info = "None"
    if found_user.uplinerID:
        upline = session.query(User).filter_by(userID=found_user.uplinerID).first()
        if upline:
            upline_info = f"{upline.firstname} (ID: {upline.userID})"

    # MLM
    mlm_status = found_user.mlmStatus or {}
    rank = mlm_status.get('rank', 'None')
    is_active = "✅" if mlm_status.get('isActive') else "❌"
    team_volume = Decimal(str((found_user.mlmVolumes or {}).get('teamVolume', 0)))

    await message_manager.send_template(
        user=user,
        template_key='admin/user/info',
        variables={
            'user_id': found_user.userID,
            'telegram_id': found_user.telegramID or 'N/A',
            'firstname': found_user.firstname or '',
            'surname': found_user.surname or '',
            'email': found_user.email or 'N/A',
            'phone': found_user.phone or 'N/A',
            'lang': found_user.lang or 'en',
            'status': found_user.status or 'active',
            'balance_active': f"{float(found_user.balanceActive or 0):,.2f}",
            'balance_passive': f"{float(found_user.balancePassive or 0):,.2f}",
            'rank': rank,
            'is_active': is_active,
            'upline': upline_info,
            'team_volume': f"{float(team_volume):,.2f}",
            'purchases_count': purchases_count,
            'purchases_sum': f"{float(purchases_sum):,.2f}",
            'bonuses_earned': f"{float(bonuses_earned):,.2f}",
            'registered': found_user.createdAt.strftime('%Y-%m-%d') if found_user.createdAt else 'N/A',
            'last_active': found_user.lastActive.strftime('%Y-%m-%d %H:%M') if found_user.lastActive else 'N/A'
        },
        update=message
    )


@misc_router.message(F.text == '&user')
async def cmd_user_usage(message: Message, user: User, session: Session, message_manager: MessageManager):
    if not is_admin(message.from_user.id):
        return
    await message_manager.send_template(user=user, template_key='admin/user/usage', update=message)


# =============================================================================
# &time - Time Machine
# =============================================================================

@misc_router.message(F.text.regexp(r'^&time'))
async def cmd_time(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Time Machine control."""
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &time")

    try:
        from mlm_system.utils.time_machine import timeMachine
        parts = message.text.split()

        if len(parts) == 1:
            mode = "🧪 TEST MODE" if timeMachine.isTestMode else "🔴 REAL TIME"
            current = timeMachine.now()
            await message_manager.send_template(
                user=user,
                template_key='admin/time/status',
                variables={
                    'current_time': current.strftime('%Y-%m-%d %H:%M:%S'),
                    'current_month': current.strftime('%Y-%m'),
                    'is_grace_day': "✅ Yes" if timeMachine.isGraceDay() else "❌ No",
                    'mode': mode
                },
                update=message
            )
            return

        if parts[1].lower() == 'reset':
            timeMachine.reset()
            logger.warning(f"Time Machine reset by admin {message.from_user.id}")
            await message_manager.send_template(user=user, template_key='admin/time/reset', update=message)
            return

        date_str = parts[1]
        time_str = parts[2] if len(parts) > 2 else "00:00"

        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        except ValueError:
            await message_manager.send_template(user=user, template_key='admin/time/error', update=message)
            return

        timeMachine.setTime(dt)
        logger.warning(f"Time Machine set to {dt} by admin {message.from_user.id}")
        await message_manager.send_template(
            user=user,
            template_key='admin/time/set',
            variables={'datetime': dt.strftime('%Y-%m-%d %H:%M:%S')},
            update=message
        )

    except ImportError:
        await message_manager.send_template(user=user, template_key='admin/time/error', update=message)


# =============================================================================
# &testmail - Test Email (FULL TALENTIR PATTERN)
# =============================================================================

@misc_router.message(F.text.regexp(r'^&testmail'))
async def cmd_testmail(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Test email - full Talentir pattern."""
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &testmail")

    email_service = get_service(EmailService)
    if not email_service:
        await message_manager.send_template(user=user, template_key='admin/testmail/no_providers', update=message)
        return

    parts = message.text.split()
    custom_email = parts[1] if len(parts) > 1 else None
    forced_provider = parts[2].lower() if len(parts) > 2 else None

    if forced_provider and forced_provider not in ['smtp', 'mailgun']:
        await message_manager.send_template(
            user=user, template_key='admin/testmail/invalid_provider',
            variables={'provider': forced_provider}, update=message
        )
        return

    if custom_email and not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', custom_email):
        await message_manager.send_template(
            user=user, template_key='admin/testmail/invalid_email',
            variables={'email': custom_email}, update=message
        )
        return

    status_msg = await message_manager.send_template(user=user, template_key='admin/testmail/checking', update=message)

    providers_status = await email_service.get_providers_status()
    config_info = email_service.get_config_info()

    template_keys = ['admin/testmail/header']
    for pn in providers_status.keys():
        template_keys.append(f'admin/testmail/status_{pn}')
    template_keys.append('admin/testmail/secure_domains' if email_service.secure_domains else 'admin/testmail/no_secure_domains')

    target_email = custom_email or user.email
    firstname = user.firstname or "Admin"

    if not target_email:
        await message_manager.send_template(
            user=user, template_key='admin/testmail/invalid_email',
            variables={'email': 'No email set'}, update=status_msg, edit=True
        )
        return

    if forced_provider:
        if not providers_status.get(forced_provider):
            template_keys.append('admin/testmail/no_available_providers')
            await message_manager.send_template(user=user, template_key=template_keys, variables={
                'smtp_host': config_info['smtp']['host'], 'smtp_port': config_info['smtp']['port'],
                'smtp_status': '✅ OK' if providers_status.get('smtp') else '❌ FAIL',
                'mailgun_domain': config_info['mailgun']['domain'], 'mailgun_region': config_info['mailgun']['region'],
                'mailgun_status': '✅ OK' if providers_status.get('mailgun') else '❌ FAIL',
                'domains': ', '.join(email_service.secure_domains) or '', 'provider': forced_provider.upper()
            }, update=status_msg, edit=True)
            return
        selected_provider = forced_provider
        template_keys.append('admin/testmail/reason_forced')
    else:
        provider_order = email_service._select_provider_for_email(target_email)
        if not provider_order:
            template_keys.append('admin/testmail/no_available_providers')
            await message_manager.send_template(user=user, template_key=template_keys, variables={
                'smtp_host': config_info['smtp']['host'], 'smtp_port': config_info['smtp']['port'],
                'smtp_status': '✅ OK' if providers_status.get('smtp') else '❌ FAIL',
                'mailgun_domain': config_info['mailgun']['domain'], 'mailgun_region': config_info['mailgun']['region'],
                'mailgun_status': '✅ OK' if providers_status.get('mailgun') else '❌ FAIL',
                'domains': ', '.join(email_service.secure_domains) or ''
            }, update=status_msg, edit=True)
            return
        selected_provider = provider_order[0]
        domain = email_service._get_email_domain(target_email)
        template_keys.append('admin/testmail/reason_secure' if domain in email_service.secure_domains else 'admin/testmail/reason_regular')

    template_keys.append('admin/testmail/sending')

    base_vars = {
        'smtp_host': config_info['smtp']['host'], 'smtp_port': config_info['smtp']['port'],
        'smtp_status': '✅ OK' if providers_status.get('smtp') else '❌ FAIL',
        'mailgun_domain': config_info['mailgun']['domain'], 'mailgun_region': config_info['mailgun']['region'],
        'mailgun_status': '✅ OK' if providers_status.get('mailgun') else '❌ FAIL',
        'domains': ', '.join(email_service.secure_domains) or '',
        'target_email': target_email, 'provider': selected_provider.upper(),
        'domain': email_service._get_email_domain(target_email)
    }

    await message_manager.send_template(user=user, template_key=template_keys, variables=base_vars, update=status_msg, edit=True)

    # Get email templates and send
    email_subject, _ = await MessageTemplates.get_raw_template('admin/testmail/email_subject', {'provider': selected_provider.upper()}, lang=user.lang or 'en')
    email_body, _ = await MessageTemplates.get_raw_template('admin/testmail/email_body', {
        'firstname': firstname, 'target_email': target_email,
        'provider': selected_provider.upper(), 'time': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    }, lang=user.lang or 'en')

    provider = email_service.providers[selected_provider]
    success = await provider.send_email(to=target_email, subject=email_subject, html_body=email_body, text_body=None)

    final_templates = ['admin/testmail/header']
    for pn in providers_status.keys():
        final_templates.append(f'admin/testmail/status_{pn}')
    final_templates.append('admin/testmail/secure_domains' if email_service.secure_domains else 'admin/testmail/no_secure_domains')
    final_templates.append('admin/testmail/success' if success else 'admin/testmail/send_error')

    if success and not forced_provider:
        po = email_service._select_provider_for_email(target_email)
        if len(po) > 1:
            final_templates.append('admin/testmail/fallback')
            base_vars['fallback_provider'] = po[1].upper()

    await message_manager.send_template(user=user, template_key=final_templates, variables=base_vars, update=status_msg, edit=True)


# =============================================================================
# &object - Send by file_id
# =============================================================================

@misc_router.message(F.text.regexp(r'^&object\s+.+'))
async def cmd_object(message: Message, user: User, session: Session, message_manager: MessageManager):
    if not is_admin(message.from_user.id):
        return

    file_id = message.text.split(maxsplit=1)[1].strip()
    logger.info(f"Admin {message.from_user.id} testing object: {file_id[:20]}...")

    from aiogram import Bot
    bot = get_service(Bot)

    for media_type, method in [('photo', bot.send_photo), ('video', bot.send_video), ('document', bot.send_document),
                                ('animation', bot.send_animation), ('audio', bot.send_audio), ('voice', bot.send_voice),
                                ('sticker', bot.send_sticker), ('video_note', bot.send_video_note)]:
        try:
            await method(chat_id=message.chat.id, **{media_type: file_id})
            return
        except Exception:
            continue

    await message_manager.send_template(user=user, template_key='admin/object/error',
        variables={'file_id': file_id[:50] + '...' if len(file_id) > 50 else file_id, 'error': 'Could not determine media type'}, update=message)


@misc_router.message(F.text == '&object')
async def cmd_object_usage(message: Message, user: User, session: Session, message_manager: MessageManager):
    if not is_admin(message.from_user.id):
        return
    await message_manager.send_template(user=user, template_key='admin/object/usage', update=message)


# =============================================================================
# &help
# =============================================================================

@misc_router.message(F.text.regexp(r'^&h(elp)?$'))
async def cmd_help(message: Message, user: User, session: Session, message_manager: MessageManager):
    if not is_admin(message.from_user.id):
        return
    await message_manager.send_template(user=user, template_key='admin/commands/help', update=message)


# =============================================================================
# FALLBACK (MUST BE LAST!)
# =============================================================================

@misc_router.message(F.text.startswith('&'))
async def cmd_fallback(message: Message, user: User, session: Session, message_manager: MessageManager):
    if not is_admin(message.from_user.id):
        return

    command = message.text.split()[0]
    logger.info(f"Admin {message.from_user.id} unknown command: {command}")
    await message_manager.send_template(user=user, template_key='admin/commands/unknown', variables={'command': command}, update=message)


__all__ = ['misc_router']