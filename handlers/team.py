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
from core.message_manager import MessageManager
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
# TEAM STRUCTURE (was TEAM STATISTICS)
# ============================================================================

@team_router.callback_query(F.data == "/team/stats")
async def handle_team_stats(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show team structure: branch tree with volumes."""
    from mlm_system.utils.chain_walker import ChainWalker
    from mlm_system.config.ranks import RANK_CONFIG, Rank

    logger.info(f"User {user.userID} viewing team structure")

    # =========================================================================
    # RANK EMOJI MAP
    # =========================================================================
    rank_emoji_map = {
        "start": "🔷",
        "builder": "🔶",
        "growth": "💎",
        "leadership": "⭐️",
        "director": "👑"
    }

    # =========================================================================
    # GET BRANCHES DATA
    # =========================================================================
    branches_tree = []
    cap_limit = 0
    capped_count = 0

    # Try to get from totalVolume JSON first (pre-calculated)
    if user.totalVolume and isinstance(user.totalVolume, dict):
        branches = user.totalVolume.get("branches", [])
        cap_limit = user.totalVolume.get("capLimit", 0)

        # Sort by fullVolume descending, take top 5
        branches_sorted = sorted(branches, key=lambda b: b.get("fullVolume", 0), reverse=True)[:5]

        for branch in branches_sorted:
            ref_user_id = branch.get("referralUserId")
            ref_user = session.query(User).filter_by(userID=ref_user_id).first() if ref_user_id else None

            # Get name (max 15 chars)
            ref_name = branch.get("referralName", "User")
            # Extract just firstname from "Firstname (ID)" format
            if " (" in ref_name:
                ref_name = ref_name.split(" (")[0]
            if len(ref_name) > 15:
                ref_name = ref_name[:12] + "..."

            # Get rank
            ref_rank = ref_user.rank if ref_user else "start"
            ref_rank_emoji = rank_emoji_map.get(ref_rank, "🔷")

            # Get volumes
            full_volume = branch.get("fullVolume", 0)
            capped_volume = branch.get("cappedVolume", full_volume)
            is_capped = branch.get("isCapped", False)

            if is_capped:
                capped_count += 1

            # Get team size using ChainWalker
            team_size = 0
            if ref_user:
                walker = ChainWalker(session)
                team_size = walker.count_downline(ref_user)

            branches_tree.append({
                "name": ref_name,
                "user_id": ref_user_id or 0,
                "rank_emoji": ref_rank_emoji,
                "full_volume": full_volume,
                "capped_volume": capped_volume,
                "is_capped": is_capped,
                "team_size": team_size
            })
    else:
        # Fallback: get direct referrals from DB
        direct_referrals = session.query(User).filter(
            User.upline == user.telegramID
        ).order_by(User.personalVolumeTotal.desc()).limit(5).all()

        walker = ChainWalker(session)

        for ref in direct_referrals:
            # Get name (max 15 chars)
            ref_name = ref.firstname or "User"
            if len(ref_name) > 15:
                ref_name = ref_name[:12] + "..."

            ref_rank_emoji = rank_emoji_map.get(ref.rank or "start", "🔷")
            ref_volume = float(ref.fullVolume or ref.personalVolumeTotal or 0)
            team_size = walker.count_downline(ref)

            branches_tree.append({
                "name": ref_name,
                "user_id": ref.userID,
                "rank_emoji": ref_rank_emoji,
                "full_volume": ref_volume,
                "capped_volume": ref_volume,
                "is_capped": False,
                "team_size": team_size
            })

    # =========================================================================
    # BUILD TREE TEXT
    # =========================================================================
    tree_lines = []

    for i, branch in enumerate(branches_tree):
        is_last = (i == len(branches_tree) - 1)
        prefix = "└─" if is_last else "├─"
        indent = "   " if is_last else "│  "

        # Name line with rank emoji
        name_line = f"{prefix} 👤 {branch['name']} ({branch['user_id']}) {branch['rank_emoji']}"
        tree_lines.append(name_line)

        # Volume line
        if branch['is_capped']:
            volume_line = f"{indent} └─ TV: ${branch['full_volume']:,.0f} → ${branch['capped_volume']:,.0f} ⚠️"
        else:
            volume_line = f"{indent} └─ TV: ${branch['full_volume']:,.0f} ✅"
        tree_lines.append(volume_line)

        # Team size line
        team_line = f"{indent} └─ Команда: {branch['team_size']} чел."
        tree_lines.append(team_line)

        # Empty line between branches (except last)
        if not is_last:
            tree_lines.append("│")

    tree_text = "\n".join(tree_lines) if tree_lines else "Нет рефералов"

    # =========================================================================
    # 50% RULE INFO
    # =========================================================================
    rule_50_text = ""
    if cap_limit > 0:
        rule_50_text = f"💡 Правило 50%: Лимит на ветку: ${cap_limit:,.0f}"
        if capped_count > 0:
            rule_50_text += f"\n⚠️ {capped_count} ветка достигла лимита"

    # =========================================================================
    # SEND TEMPLATE
    # =========================================================================
    await message_manager.send_template(
        user=user,
        template_key='/team/stats',
        variables={
            'tree_text': tree_text,
            'rule_50_text': rule_50_text,
            'branches_count': len(branches_tree)
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