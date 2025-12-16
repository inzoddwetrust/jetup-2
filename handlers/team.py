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
    """Show main team screen with full MLM metrics."""
    from mlm_system.utils.chain_walker import ChainWalker
    from mlm_system.config.ranks import RANK_CONFIG, Rank

    logger.info(f"User {user.userID} opened team screen")

    # =========================================================================
    # RANK DATA
    # =========================================================================
    rank_emoji_map = {
        "start": "🔷",
        "builder": "🔶",
        "growth": "💎",
        "leadership": "⭐️",
        "director": "👑"
    }

    current_rank = user.rank or "start"
    rank_emoji = rank_emoji_map.get(current_rank, "🔷")

    # Get rank display name from config
    try:
        rank_enum = Rank(current_rank)
        rank_config = RANK_CONFIG()
        rank_display = rank_config[rank_enum].get("displayName", current_rank.title())
    except (ValueError, KeyError):
        rank_display = current_rank.title()

    # =========================================================================
    # PIONEER STATUS
    # =========================================================================
    pioneer_text = ""
    if user.mlmStatus and user.mlmStatus.get("hasPioneerBonus", False):
        # Get global pioneer count from root user
        default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
        root_user = session.query(User).filter_by(telegramID=default_referrer_id).first()

        pioneer_number = "?"
        if root_user and root_user.mlmStatus:
            pioneer_number = root_user.mlmStatus.get("pioneerPurchasesCount", "?")

        pioneer_text = f"🎖 Pioneer #{pioneer_number}/50 (+4%)"

    # =========================================================================
    # SALES DATA
    # =========================================================================
    personal_volume = float(user.personalVolumeTotal or Decimal("0"))
    team_volume_full = float(user.fullVolume or Decimal("0"))

    # =========================================================================
    # QUALIFICATION TO NEXT RANK
    # =========================================================================
    qualifying_volume = 0
    required_volume = 0
    next_rank_name = ""
    progress_percent = 0
    progress_bar = "░░░░░░░░░░"  # 10 blocks = 100%
    gap_amount = 0

    # Get next rank
    ranks_order = ["start", "builder", "growth", "leadership", "director"]
    try:
        current_idx = ranks_order.index(current_rank)
        if current_idx < len(ranks_order) - 1:
            next_rank = ranks_order[current_idx + 1]
            next_rank_enum = Rank(next_rank)
            next_rank_data = rank_config.get(next_rank_enum, {})

            next_rank_name = next_rank_data.get("displayName", next_rank.title())
            required_volume = float(next_rank_data.get("teamVolumeRequired", Decimal("0")))

            # Get qualifying volume from totalVolume JSON
            if user.totalVolume and isinstance(user.totalVolume, dict):
                qualifying_volume = float(user.totalVolume.get("qualifyingVolume", 0))
            else:
                qualifying_volume = float(user.teamVolumeTotal or Decimal("0"))

            # Calculate progress
            if required_volume > 0:
                progress_percent = min(100, int((qualifying_volume / required_volume) * 100))
                filled_blocks = int(progress_percent / 10)
                progress_bar = "█" * filled_blocks + "░" * (10 - filled_blocks)
                gap_amount = max(0, required_volume - qualifying_volume)
    except (ValueError, KeyError, IndexError):
        pass

    # =========================================================================
    # TEAM METRICS
    # =========================================================================
    # Count direct referrals
    direct_referrals = session.query(func.count(User.userID)).filter(
        User.upline == user.telegramID
    ).scalar() or 0

    # Count all referrals recursively using ChainWalker
    walker = ChainWalker(session)
    total_team = walker.count_downline(user)

    # Count active partners (entire structure with isActive=True)
    active_partners = walker.count_active_downline(user)

    # Get required active partners for next rank
    required_active_partners = 0
    if current_idx < len(ranks_order) - 1:
        required_active_partners = int(next_rank_data.get("activePartnersRequired", 0))

    # =========================================================================
    # 50% RULE WARNING
    # =========================================================================
    rule_50_warning = ""
    if user.totalVolume and isinstance(user.totalVolume, dict):
        branches = user.totalVolume.get("branches", [])
        capped_count = sum(1 for b in branches if b.get("isCapped", False))

        if capped_count > 0:
            rule_50_warning = f"⚠️ Правило 50%: {capped_count} ветка достигла лимита\n💡 Развивайте другие ветки"
        elif branches and qualifying_volume > 0:
            rule_50_warning = "✅ Баланс веток: OK"

    # =========================================================================
    # SEND TEMPLATE
    # =========================================================================
    await message_manager.send_template(
        user=user,
        template_key='/team',
        update=callback_query,
        variables={
            # Rank data
            'rank_emoji': rank_emoji,
            'rank_display': rank_display,
            'pioneer_text': pioneer_text,

            # Sales data
            'personal_volume': f"{personal_volume:,.0f}",
            'team_volume_full': f"{team_volume_full:,.0f}",

            # Qualification data
            'next_rank_name': next_rank_name,
            'qualifying_volume': f"{qualifying_volume:,.0f}",
            'required_volume': f"{required_volume:,.0f}",
            'progress_percent': progress_percent,
            'progress_bar': progress_bar,
            'gap_amount': f"{gap_amount:,.0f}",

            # Team metrics
            'direct_referrals': direct_referrals,
            'total_team': total_team,
            'active_partners': active_partners,
            'required_active_partners': required_active_partners,

            # 50% rule
            'rule_50_warning': rule_50_warning,

            # Legacy variables (for backward compatibility)
            'userInvitedUplineFirst': direct_referrals,
            'userInvitedUplineTotal': total_team
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

    # Calculate team statistics
    # Direct referrals count
    direct_refs = session.query(func.count(User.userID)).filter(
        User.upline == user.telegramID
    ).scalar() or 0

    # Get direct referrals with purchases
    referrals_with_purchases = session.query(
        User.userID,
        User.firstname,
        User.surname,
        User.createdAt,
        func.sum(Purchase.packPrice).label('total_purchases'),
        func.count(Purchase.purchaseID).label('purchases_count')
    ).outerjoin(
        Purchase, Purchase.userID == User.userID
    ).filter(
        User.upline == user.telegramID
    ).group_by(
        User.userID, User.firstname, User.surname, User.createdAt
    ).all()

    # Team total purchases
    team_total = Decimal("0")
    for ref in referrals_with_purchases:
        if ref.total_purchases:
            team_total += Decimal(str(ref.total_purchases))

    # Format data for template
    stats_data = []
    for ref in referrals_with_purchases:
        stats_data.append({
            'name': f"{ref.firstname} {ref.surname or ''}".strip() or "User",
            'joined': ref.createdAt.strftime("%Y-%m-%d") if ref.createdAt else "N/A",
            'purchases': int(ref.purchases_count or 0),
            'volume': f"${float(ref.total_purchases or 0):,.0f}"
        })

    # Sort by volume
    stats_data.sort(key=lambda x: float(x['volume'].replace('$', '').replace(',', '')), reverse=True)

    await message_manager.send_template(
        user=user,
        template_key='/team/stats',
        variables={
            'direct_refs': direct_refs,
            'team_total': f"${float(team_total):,.0f}",
            'rgroup': {
                'name': [s['name'] for s in stats_data],
                'joined': [s['joined'] for s in stats_data],
                'purchases': [s['purchases'] for s in stats_data],
                'volume': [s['volume'] for s in stats_data]
            } if stats_data else None
        },
        update=callback_query,
        delete_original=True
    )


# ============================================================================
# CSV DOWNLOAD
# ============================================================================

@team_router.callback_query(F.data.regexp(r"/team/stats/download/csv/.+$"))
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