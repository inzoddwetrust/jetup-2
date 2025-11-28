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
from datetime import datetime, timezone, timedelta
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

        # Calculate 30 days ago using existing datetime import
        thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

        users_active = session.query(func.count(User.userID)).filter(
            User.lastActive >= thirty_days_ago
        ).scalar() or 0

        # Active partners (use direct field isActive, not JSON)
        active_partners = session.query(func.count(User.userID)).filter(
            User.isActive == True
        ).scalar() or 0

        # Financial stats
        deposits_total = session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'confirmed'
        ).scalar() or Decimal('0')

        payments_pending = session.query(func.count(Payment.paymentID)).filter(
            Payment.status == 'check'
        ).scalar() or 0

        # Purchases
        purchases_count = session.query(func.count(Purchase.purchaseID)).scalar() or 0
        purchases_volume = session.query(func.sum(Purchase.packPrice)).scalar() or Decimal('0')

        # Bonuses
        bonuses_paid = session.query(func.sum(Bonus.bonusAmount)).filter(
            Bonus.status == 'paid'
        ).scalar() or Decimal('0')

        bonuses_pending = session.query(func.sum(Bonus.bonusAmount)).filter(
            Bonus.status == 'pending'
        ).scalar() or Decimal('0')

        # Time Machine status
        time_machine_status = ""
        try:
            from mlm_system.utils.time_machine import timeMachine
            if timeMachine._isTestMode:
                time_machine_status = f"⏰ Time Machine: {timeMachine.now.strftime('%Y-%m-%d %H:%M')}"
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
    bonuses_earned = session.query(func.sum(Bonus.bonusAmount)).filter_by(
        userID=found_user.userID, status='paid'
    ).scalar() or Decimal('0')

    # Upline (upline field stores telegramID of sponsor)
    upline_info = "None"
    if found_user.upline:
        upline = session.query(User).filter_by(telegramID=found_user.upline).first()
        if upline:
            upline_info = f"{upline.firstname} (ID: {upline.userID})"

    # MLM - use direct fields, not JSON
    rank = found_user.rank or 'start'
    is_active = "✅" if found_user.isActive else "❌"
    team_volume = found_user.teamVolumeTotal or Decimal('0')

    await message_manager.send_template(
        user=user,
        template_key='admin/user/info',
        variables={
            'user_id': found_user.userID,
            'telegram_id': found_user.telegramID or 'N/A',
            'firstname': found_user.firstname or '',
            'surname': found_user.surname or '',
            'email': found_user.email or 'N/A',
            'phone': found_user.phoneNumber or 'N/A',
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
    """
    Time Machine control for testing Grace Day and monthly operations.

    Usage:
        &time              - Show current time status
        &time set DATE     - Set virtual date (YYYY-MM-DD or YYYY-MM-DD HH:MM)
        &time grace        - Jump to 1st of current month
        &time +Nd          - Advance N days
        &time reset        - Return to real time
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &time")

    try:
        from mlm_system.utils.time_machine import timeMachine
        parts = message.text.split()

        # &time — show status
        if len(parts) == 1:
            mode = "🧪 TEST MODE" if timeMachine._isTestMode else "🔴 REAL TIME"
            current = timeMachine.now
            await message_manager.send_template(
                user=user,
                template_key='admin/time/status',
                variables={
                    'current_time': current.strftime('%Y-%m-%d %H:%M:%S'),
                    'current_month': current.strftime('%Y-%m'),
                    'is_grace_day': "✅ Yes" if timeMachine.isGraceDay else "❌ No",
                    'mode': mode
                },
                update=message
            )
            return

        cmd = parts[1].lower()

        # &time reset
        if cmd == 'reset':
            timeMachine.resetToRealTime()
            logger.warning(f"Time Machine reset by admin {message.from_user.id}")
            await message_manager.send_template(user=user, template_key='admin/time/reset', update=message)
            return

        # &time grace — jump to 1st of current month
        if cmd == 'grace':
            now = datetime.now(timezone.utc)
            grace_day = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            timeMachine.setTime(grace_day, adminId=message.from_user.id)
            logger.warning(f"Time Machine set to Grace Day by admin {message.from_user.id}")
            await message_manager.send_template(
                user=user,
                template_key='admin/time/set',
                variables={'datetime': grace_day.strftime('%Y-%m-%d %H:%M:%S')},
                update=message
            )
            return

        # &time +Nd — advance N days
        if cmd.startswith('+') and cmd.endswith('d'):
            if not timeMachine._isTestMode:
                await message_manager.send_template(
                    user=user,
                    template_key='admin/time/error',
                    update=message
                )
                return

            try:
                days = int(cmd[1:-1])
                timeMachine.advanceTime(days=days)
                await message_manager.send_template(
                    user=user,
                    template_key='admin/time/set',
                    variables={'datetime': timeMachine.now.strftime('%Y-%m-%d %H:%M:%S')},
                    update=message
                )
            except ValueError:
                await message_manager.send_template(user=user, template_key='admin/time/error', update=message)
            return

        # &time set DATE [TIME] or just &time DATE [TIME]
        if cmd == 'set':
            date_str = parts[2] if len(parts) > 2 else None
            time_str = parts[3] if len(parts) > 3 else "00:00"
        else:
            date_str = parts[1]
            time_str = parts[2] if len(parts) > 2 else "00:00"

        if not date_str:
            await message_manager.send_template(user=user, template_key='admin/time/error', update=message)
            return

        try:
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            timeMachine.setTime(dt, adminId=message.from_user.id)
            logger.warning(f"Time Machine set to {dt} by admin {message.from_user.id}")

            # Immediately trigger scheduled tasks check for new time
            try:
                from core.system_services import ServiceManager
                service_manager = get_service(ServiceManager)
                if service_manager and hasattr(service_manager, 'mlm_scheduler') and service_manager.mlm_scheduler:
                    await service_manager.mlm_scheduler.checkScheduledTasks()
                    logger.info("Triggered checkScheduledTasks after Time Machine change")
            except Exception as e:
                logger.error(f"Failed to trigger scheduled tasks: {e}")

            await message_manager.send_template(
                user=user,
                template_key='admin/time/set',
                variables={'datetime': dt.strftime('%Y-%m-%d %H:%M:%S')},
                update=message
            )
        except ValueError:
            await message_manager.send_template(user=user, template_key='admin/time/error', update=message)

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
    template_keys.append(
        'admin/testmail/secure_domains' if email_service.secure_domains else 'admin/testmail/no_secure_domains')

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
        template_keys.append(
            'admin/testmail/reason_secure' if domain in email_service.secure_domains else 'admin/testmail/reason_regular')

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

    await message_manager.send_template(user=user, template_key=template_keys, variables=base_vars, update=status_msg,
                                        edit=True)

    # Get email templates and send
    email_subject, _ = await MessageTemplates.get_raw_template('admin/testmail/email_subject',
                                                               {'provider': selected_provider.upper()},
                                                               lang=user.lang or 'en')
    email_body, _ = await MessageTemplates.get_raw_template('admin/testmail/email_body', {
        'firstname': firstname, 'target_email': target_email,
        'provider': selected_provider.upper(), 'time': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    }, lang=user.lang or 'en')

    provider = email_service.providers[selected_provider]
    success = await provider.send_email(to=target_email, subject=email_subject, html_body=email_body, text_body=None)

    final_templates = ['admin/testmail/header']
    for pn in providers_status.keys():
        final_templates.append(f'admin/testmail/status_{pn}')
    final_templates.append(
        'admin/testmail/secure_domains' if email_service.secure_domains else 'admin/testmail/no_secure_domains')
    final_templates.append('admin/testmail/success' if success else 'admin/testmail/send_error')

    if success and not forced_provider:
        po = email_service._select_provider_for_email(target_email)
        if len(po) > 1:
            final_templates.append('admin/testmail/fallback')
            base_vars['fallback_provider'] = po[1].upper()

    await message_manager.send_template(user=user, template_key=final_templates, variables=base_vars, update=status_msg,
                                        edit=True)


# =============================================================================
# &object - Send by file_id
# =============================================================================

@misc_router.message(F.text.regexp(r'^&object\s+.+'))
async def cmd_object(message: Message, user: User, session: Session, message_manager: MessageManager):
    """Send media by file_id to detect type."""
    if not is_admin(message.from_user.id):
        return

    file_id = message.text.split(maxsplit=1)[1].strip()
    logger.info(f"Admin {message.from_user.id} testing object: {file_id[:30]}...")

    # Try sending as different media types
    send_attempts = [
        ('sticker', lambda: message.reply_sticker(sticker=file_id)),
        ('photo', lambda: message.reply_photo(photo=file_id, caption="📷 Photo object")),
        ('video', lambda: message.reply_video(video=file_id, caption="🎥 Video object")),
        ('document', lambda: message.reply_document(document=file_id, caption="📄 Document object")),
        ('animation', lambda: message.reply_animation(animation=file_id, caption="🎬 Animation object")),
        ('audio', lambda: message.reply_audio(audio=file_id, caption="🎵 Audio object")),
        ('voice', lambda: message.reply_voice(voice=file_id, caption="🎤 Voice object")),
        ('video_note', lambda: message.reply_video_note(video_note=file_id))
    ]

    for media_type, send_func in send_attempts:
        try:
            await send_func()
            # Success - report the type
            await message_manager.send_template(
                user=user,
                template_key='admin/object/success',
                variables={'media_type': media_type},
                update=message
            )
            logger.info(f"Successfully sent object as {media_type}")
            return
        except Exception:
            continue

    # All attempts failed
    await message_manager.send_template(
        user=user,
        template_key='admin/object/error',
        variables={
            'file_id': file_id[:50] + '...' if len(file_id) > 50 else file_id,
            'error': 'Invalid file_id or object from another bot'
        },
        update=message
    )


@misc_router.message(F.text == '&object')
async def cmd_object_usage(message: Message, user: User, session: Session, message_manager: MessageManager):
    if not is_admin(message.from_user.id):
        return
    await message_manager.send_template(user=user, template_key='admin/object/usage', update=message)


# =============================================================================
# MEDIA FILE_ID EXTRACTION (when admin sends photo/video/document)
# =============================================================================

@misc_router.message(F.photo)
async def extract_photo_file_id(message: Message, user: User, session: Session, message_manager: MessageManager):
    """Extract file_id from photo sent by admin."""
    if not is_admin(message.from_user.id):
        return

    # Get the largest photo (last in array)
    photo = message.photo[-1]
    file_id = photo.file_id

    await message_manager.send_template(
        user=user,
        template_key='admin/object/extracted',
        variables={
            'media_type': 'photo',
            'file_id': file_id,
            'width': photo.width,
            'height': photo.height,
            'file_size': photo.file_size or 'N/A'
        },
        update=message
    )


@misc_router.message(F.video)
async def extract_video_file_id(message: Message, user: User, session: Session, message_manager: MessageManager):
    """Extract file_id from video sent by admin."""
    if not is_admin(message.from_user.id):
        return

    video = message.video
    file_id = video.file_id

    await message_manager.send_template(
        user=user,
        template_key='admin/object/extracted',
        variables={
            'media_type': 'video',
            'file_id': file_id,
            'width': video.width,
            'height': video.height,
            'file_size': video.file_size or 'N/A'
        },
        update=message
    )


@misc_router.message(F.document)
async def extract_document_file_id(message: Message, user: User, session: Session, message_manager: MessageManager):
    """Extract file_id from document sent by admin."""
    if not is_admin(message.from_user.id):
        return

    doc = message.document
    file_id = doc.file_id

    await message_manager.send_template(
        user=user,
        template_key='admin/object/extracted',
        variables={
            'media_type': 'document',
            'file_id': file_id,
            'file_name': doc.file_name or 'N/A',
            'mime_type': doc.mime_type or 'N/A',
            'file_size': doc.file_size or 'N/A'
        },
        update=message
    )


@misc_router.message(F.animation)
async def extract_animation_file_id(message: Message, user: User, session: Session, message_manager: MessageManager):
    """Extract file_id from animation/GIF sent by admin."""
    if not is_admin(message.from_user.id):
        return

    anim = message.animation
    file_id = anim.file_id

    await message_manager.send_template(
        user=user,
        template_key='admin/object/extracted',
        variables={
            'media_type': 'animation',
            'file_id': file_id,
            'width': anim.width,
            'height': anim.height,
            'file_size': anim.file_size or 'N/A'
        },
        update=message
    )


@misc_router.message(F.sticker)
async def extract_sticker_file_id(message: Message, user: User, session: Session, message_manager: MessageManager):
    """Extract file_id from sticker sent by admin."""
    if not is_admin(message.from_user.id):
        return

    sticker = message.sticker
    file_id = sticker.file_id

    await message_manager.send_template(
        user=user,
        template_key='admin/object/extracted',
        variables={
            'media_type': 'sticker',
            'file_id': file_id,
            'emoji': sticker.emoji or 'N/A',
            'set_name': sticker.set_name or 'N/A',
            'file_size': sticker.file_size or 'N/A'
        },
        update=message
    )


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

    if user:
        await message_manager.send_template(
            user=user,
            template_key='admin/commands/unknown',
            variables={'command': command},
            update=message
        )
    else:
        await message.reply(
            f"❓ Unknown: <code>{command}</code>\nUse <code>&help</code>",
            parse_mode="HTML"
        )


__all__ = ['misc_router']
