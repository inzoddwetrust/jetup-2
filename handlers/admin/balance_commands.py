# handlers/admin/balance_commands.py
"""
Balance management commands for admins.

Commands:
    &addbalance  - Manual balance adjustment
    &delpurchase - Delete purchase with optional refund

Templates used:
    admin/balance/success, admin/balance/user_not_found, admin/balance/usage, admin/balance/error
    admin/delpurchase/analysis, admin/delpurchase/success, admin/delpurchase/not_found, admin/delpurchase/usage
"""
import os
import shutil
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from config import Config
from core.message_manager import MessageManager
from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from models.active_balance import ActiveBalance
from models.notification import Notification

logger = logging.getLogger(__name__)

balance_router = Router(name="admin_balance")


# =============================================================================
# ADMIN CHECK
# =============================================================================

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admins = Config.get(Config.ADMIN_USER_IDS) or []
    return user_id in admins


# =============================================================================
# BACKUP UTILITY
# =============================================================================

async def create_backup(category: str = 'manual') -> str:
    """Create database backup before dangerous operations."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = Path(os.getenv("BACKUP_DIR", "./backups")) / category
    os.makedirs(backup_dir, exist_ok=True)

    database_url = Config.get(Config.DATABASE_URL)
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
    else:
        raise ValueError("Unsupported DATABASE_URL format")

    backup_path = backup_dir / f"jetup_{timestamp}.db"
    shutil.copy2(db_path, backup_path)
    logger.info(f"Backup created: {backup_path}")
    return str(backup_path)


# =============================================================================
# &addbalance - Manual Balance Adjustment
# =============================================================================

@balance_router.message(F.text.regexp(r'^&addbalance\s+\d+\s+[-]?\d+'))
async def cmd_addbalance(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Manual balance adjustment.

    Usage: &addbalance <userID> <amount> [reason]

    Examples:
        &addbalance 123 500
        &addbalance 123 -100 duplicate refund
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &addbalance")

    parts = message.text.split(maxsplit=3)
    target_user_id = int(parts[1])

    try:
        amount = Decimal(parts[2])
    except InvalidOperation:
        await message_manager.send_template(
            user=user,
            template_key='admin/balance/error',
            variables={'error': f'Invalid amount: {parts[2]}'},
            update=message
        )
        return

    reason = parts[3] if len(parts) > 3 else 'admin_adjustment'

    # Find target user
    target_user = session.query(User).filter_by(userID=target_user_id).first()
    if not target_user:
        await message_manager.send_template(
            user=user,
            template_key='admin/balance/user_not_found',
            variables={'user_id': target_user_id},
            update=message
        )
        return

    try:
        # Create ActiveBalance record
        balance_record = ActiveBalance(
            userID=target_user.userID,
            firstname=target_user.firstname,
            surname=target_user.surname,
            amount=amount,
            status='done',
            reason=reason,
            link='',
            notes=f'Admin adjustment by {user.userID} ({user.firstname})',
            ownerTelegramID=target_user.telegramID,
            ownerEmail=target_user.email or ''
        )
        session.add(balance_record)

        # Update user balance
        old_balance = target_user.balanceActive or Decimal('0')
        target_user.balanceActive = old_balance + amount

        session.commit()

        # Determine action text
        if amount >= 0:
            action = "increased"
            amount_sign = "+"
        else:
            action = "decreased"
            amount_sign = ""

        logger.info(f"Balance adjusted: user={target_user_id}, amount={amount}, by admin {user.userID}")

        await message_manager.send_template(
            user=user,
            template_key='admin/balance/success',
            variables={
                'action': action,
                'firstname': target_user.firstname or 'User',
                'user_id': target_user_id,
                'amount_sign': amount_sign,
                'amount': f"{abs(float(amount)):,.2f}",
                'reason': reason,
                'new_balance': f"{float(target_user.balanceActive):,.2f}"
            },
            update=message
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Error in &addbalance: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/balance/error',
            variables={'error': str(e)},
            update=message
        )


@balance_router.message(F.text == '&addbalance')
async def cmd_addbalance_usage(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show &addbalance usage."""
    if not is_admin(message.from_user.id):
        return

    await message_manager.send_template(
        user=user,
        template_key='admin/balance/usage',
        update=message
    )


# =============================================================================
# &delpurchase - Delete Purchase
# =============================================================================

@balance_router.message(F.text.regexp(r'^&delpurchase\s+\d+'))
async def cmd_delpurchase(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Delete purchase with optional refund.

    Usage:
        &delpurchase <purchaseID>                    - Analysis mode
        &delpurchase <purchaseID> --confirm          - Delete
        &delpurchase <purchaseID> --refund --confirm - Delete + refund
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &delpurchase")

    parts = message.text.split()
    purchase_id = int(parts[1])
    confirm_mode = '--confirm' in parts
    refund_mode = '--refund' in parts

    # Find purchase
    purchase = session.query(Purchase).filter_by(purchaseID=purchase_id).first()
    if not purchase:
        await message_manager.send_template(
            user=user,
            template_key='admin/delpurchase/not_found',
            variables={'purchase_id': purchase_id},
            update=message
        )
        return

    # Get related data
    purchase_user = session.query(User).filter_by(userID=purchase.userID).first()
    bonuses = session.query(Bonus).filter_by(purchaseID=purchase_id).all()
    balance_records = session.query(ActiveBalance).filter(
        ActiveBalance.reason.like(f'%purchase={purchase_id}%')
    ).all()

    # Analysis mode (default)
    if not confirm_mode:
        await message_manager.send_template(
            user=user,
            template_key='admin/delpurchase/analysis',
            variables={
                'purchase_id': purchase_id,
                'firstname': purchase_user.firstname if purchase_user else 'Unknown',
                'user_id': purchase.userID,
                'pack_name': purchase.projectName or 'N/A',
                'pack_price': f"{float(purchase.packPrice or 0):,.2f}",
                'created_at': purchase.createdAt.strftime('%Y-%m-%d %H:%M') if purchase.createdAt else 'N/A',
                'bonuses_count': len(bonuses),
                'balance_count': len(balance_records)
            },
            update=message
        )
        return

    # Delete mode
    try:
        # Create backup first
        await create_backup(category='manual')

        # Delete related records
        bonuses_deleted = 0
        for bonus in bonuses:
            session.delete(bonus)
            bonuses_deleted += 1

        balance_deleted = 0
        for br in balance_records:
            session.delete(br)
            balance_deleted += 1

        # Refund if requested
        refund_info = ""
        if refund_mode and purchase_user:
            refund_amount = purchase.packPrice or Decimal('0')
            purchase_user.balanceActive = (purchase_user.balanceActive or Decimal('0')) + refund_amount

            # Create refund record
            refund_record = ActiveBalance(
                userID=purchase_user.userID,
                firstname=purchase_user.firstname,
                surname=purchase_user.surname,
                amount=refund_amount,
                status='done',
                reason=f'refund_purchase={purchase_id}',
                notes=f'Refund by admin {user.userID}'
            )
            session.add(refund_record)
            refund_info = f"💰 Refunded: ${float(refund_amount):,.2f}"

        # Delete purchase
        session.delete(purchase)
        session.commit()

        logger.warning(f"Purchase {purchase_id} deleted by admin {user.userID}, refund={refund_mode}")

        await message_manager.send_template(
            user=user,
            template_key='admin/delpurchase/success',
            variables={
                'purchase_id': purchase_id,
                'firstname': purchase_user.firstname if purchase_user else 'Unknown',
                'bonuses_deleted': bonuses_deleted,
                'balance_deleted': balance_deleted,
                'refund_info': refund_info
            },
            update=message
        )

    except Exception as e:
        session.rollback()
        logger.error(f"Error in &delpurchase: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/balance/error',
            variables={'error': str(e)},
            update=message
        )


@balance_router.message(F.text == '&delpurchase')
async def cmd_delpurchase_usage(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show &delpurchase usage."""
    if not is_admin(message.from_user.id):
        return

    await message_manager.send_template(
        user=user,
        template_key='admin/delpurchase/usage',
        update=message
    )


__all__ = ['balance_router']