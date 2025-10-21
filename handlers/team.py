# jetup/handlers/team.py
"""
Team handlers - referral system, structure, statistics.
"""
import logging
from datetime import datetime
from decimal import Decimal
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.types import BufferedInputFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from services.document.csv_generator import CSVGenerator
from models.user import User
from models.purchase import Purchase
from core.message_manager import MessageManager
from core.utils import safe_delete_message
from config import Config

logger = logging.getLogger(__name__)

team_router = Router(name="team_router")


# ============================================================================
# MAIN TEAM SCREEN
# ============================================================================

@team_router.callback_query(F.data == "/team")
async def handle_team(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show main team screen with referral counts."""
    from mlm_system.utils.chain_walker import ChainWalker

    logger.info(f"User {user.userID} opened team screen")

    # Count direct referrals
    upline_count = session.query(func.count(User.userID)).filter(
        User.upline == user.telegramID
    ).scalar() or 0

    # Count all referrals recursively using ChainWalker
    walker = ChainWalker(session)
    upline_total = walker.count_downline(user)

    await message_manager.send_template(
        user=user,
        template_key='/team',
        update=callback_query,
        variables={
            'userInvitedUplineFirst': upline_count,
            'userInvitedUplineTotal': upline_total
        },
        delete_original=True
    )


# ============================================================================
# REFERRAL INFO & LINK
# ============================================================================

@team_router.callback_query(F.data == "/team/referal/info")
async def start_referral_link_dialog(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show referral program information."""
    logger.info(f"User {user.userID} viewing referral info")

    await message_manager.send_template(
        user=user,
        template_key='/team/referal/info',
        update=callback_query,
        delete_original=True
    )


@team_router.callback_query(F.data == "/team/referal/card")
async def show_referral_link(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show referral link with user info."""
    logger.info(f"User {user.userID} viewing referral card")

    # Get bot username from config
    bot_username = Config.get(Config.BOT_USERNAME)
    ref_link = f"<a href='https://t.me/{bot_username}?start={user.telegramID}'>🚀JETUP!🚀</a>"

    await message_manager.send_template(
        user=user,
        template_key='/team/referal/card',
        variables={
            'ref_link': ref_link,
            'firstname': user.firstname,
            'user_id': user.userID
        },
        update=callback_query,
        edit=True
    )


# ============================================================================
# MARKETING PLAN (TEMPORARILY DISABLED)
# ============================================================================

@team_router.callback_query(F.data == "/team/marketing")
async def show_marketing_info(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Show marketing plan (commission structure).

    NOTE: Temporarily disabled while new MLM system is being tested.
    Old PURCHASE_BONUSES system removed, new MLM system not ready for display yet.
    """
    logger.info(f"User {user.userID} viewing marketing plan (under development)")

    # Show under development screen
    await message_manager.send_template(
        user=user,
        template_key='under_development',
        update=callback_query,
        delete_original=True
    )


# ============================================================================
# TEAM STATISTICS
# ============================================================================

@team_router.callback_query(F.data == "/team/stats")
async def handle_team_stats(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show team statistics: referrals and their purchases."""
    logger.info(f"User {user.userID} viewing team stats")

    # Delete original message
    await safe_delete_message(callback_query)

    # Get bot username for referral link
    bot_username = Config.get(Config.BOT_USERNAME)
    ref_link = f"https://t.me/{bot_username}?start={user.telegramID}"

    # Calculate current month start
    now = datetime.utcnow()
    current_month_start = datetime(now.year, now.month, 1)

    logger.info(f"Calculating stats from {current_month_start}")

    # Get all referrals
    referrals = session.query(User).filter(
        User.upline == user.telegramID
    ).all()

    # Count referrals
    total_referrals = len(referrals)
    new_referrals = len([
        r for r in referrals
        if r.createdAt and r.createdAt >= current_month_start
    ])

    # Get referral IDs
    referral_ids = [r.userID for r in referrals]

    # Calculate purchases
    total_purchases = Decimal('0')
    monthly_purchases = Decimal('0')

    if referral_ids:
        referral_purchases = session.query(Purchase).filter(
            Purchase.userID.in_(referral_ids)
        ).order_by(Purchase.createdAt).all()

        logger.info(f"Found purchases for referrals {referral_ids}:")
        for purchase in referral_purchases:
            # Convert to Decimal for precision
            amount = Decimal(str(purchase.packPrice))
            total_purchases += amount

            if purchase.createdAt and purchase.createdAt >= current_month_start:
                monthly_purchases += amount
                logger.info(
                    f"Monthly purchase - ID: {purchase.purchaseID}, "
                    f"User: {purchase.userID}, Date: {purchase.createdAt}, "
                    f"Amount: {amount}"
                )
            else:
                logger.info(
                    f"Earlier purchase - ID: {purchase.purchaseID}, "
                    f"User: {purchase.userID}, Date: {purchase.createdAt}, "
                    f"Amount: {amount}"
                )

        logger.info(f"Total purchases sum: {total_purchases}")
        logger.info(f"Current month purchases sum: {monthly_purchases}")

    # Send stats message
    # Convert Decimal to float for template
    await message_manager.send_template(
        user=user,
        template_key='/team/stats',
        update=callback_query,
        variables={
            'ref_link': ref_link,
            'total_refs': total_referrals,
            'new_refs': new_referrals,
            'total_purchases': float(total_purchases),
            'monthly_purchases': float(monthly_purchases)
        }
    )

# ============================================================================
# CSV REPORT DOWNLOAD
# ============================================================================

@team_router.callback_query(F.data.regexp(r"^.*/download/csv/.*$"))
async def handle_csv_download(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Handle CSV report downloads.
    Format: /team/stats/download/csv/team_full
    """
    callback_data = callback_query.data

    # Parse callback data
    parts = callback_data.split("/download/csv/")
    if len(parts) != 2:
        logger.error(f"Invalid callback format: {callback_data}")
        await callback_query.answer("Invalid request format")
        return

    report_type = parts[1]
    back_button = parts[0]

    logger.info(f"User {user.userID} downloading CSV report: {report_type}")

    try:
        # Show generating message
        await message_manager.send_template(
            user=user,
            template_key='/download/csv/report_generating',
            update=callback_query
        )

        # Generate CSV using CSVGenerator service
        csv_generator = CSVGenerator()
        csv_bytes = csv_generator.generate_report(
            session=session,
            user=user,
            report_type=report_type,
            params=None
        )

        if not csv_bytes:
            logger.error(f"Failed to generate CSV report: {report_type}")
            await message_manager.send_template(
                user=user,
                template_key='/download/csv/report_error',
                variables={'back_button': back_button or '/dashboard/existingUser'},
                update=callback_query
            )
            return

        # Create filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = CSVGenerator.REPORTS.get(report_type, {}).get("name", report_type.capitalize())
        filename = f"{report_name}_{timestamp}.csv"

        # Send CSV file
        file = BufferedInputFile(
            file=csv_bytes,
            filename=filename
        )

        await callback_query.message.answer_document(document=file)

        logger.info(f"CSV report sent to user {user.userID}: {filename}")

        # Show ready message
        await message_manager.send_template(
            user=user,
            template_key='/download/csv/report_ready',
            variables={'back_button': back_button or '/dashboard/existingUser'},
            update=callback_query
        )

    except Exception as e:
        logger.error(f"Error generating CSV report: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='report_generation_error',
            update=callback_query
        )