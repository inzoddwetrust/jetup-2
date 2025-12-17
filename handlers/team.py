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

    # Localized rank names
    rank_names = {
        "en": {
            "start": "Start",
            "builder": "Builder",
            "growth": "Growth",
            "leadership": "Leadership",
            "director": "Director"
        },
        "ru": {
            "start": "Старт",
            "builder": "Строитель",
            "growth": "Рост",
            "leadership": "Лидер",
            "director": "Директор"
        }
    }

    current_rank = user.rank or "start"
    rank_emoji = rank_emoji_map.get(current_rank, "🔷")

    # Get localized rank name
    user_lang = user.lang if user.lang in rank_names else "en"
    rank_display = rank_names[user_lang].get(current_rank, current_rank.title())

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
    current_idx = -1
    next_rank_data = {}
    rank_config = RANK_CONFIG()  # Load rank config

    try:
        current_idx = ranks_order.index(current_rank)
        if current_idx < len(ranks_order) - 1:
            next_rank = ranks_order[current_idx + 1]
            next_rank_enum = Rank(next_rank)
            next_rank_data = rank_config.get(next_rank_enum, {})

            # Get localized next rank name
            next_rank_name = rank_names[user_lang].get(next_rank, next_rank.title())
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
    # 50% RULE WARNING - determine which template to add
    # =========================================================================
    rule_50_template = None
    capped_count = 0

    if user.totalVolume and isinstance(user.totalVolume, dict):
        branches = user.totalVolume.get("branches", [])
        capped_count = sum(1 for b in branches if b.get("isCapped", False))

        if capped_count > 0:
            rule_50_template = '/team/rule50_capped'
        elif branches and qualifying_volume > 0:
            rule_50_template = '/team/rule50_ok'

    # =========================================================================
    # BUILD TEMPLATE LIST
    # =========================================================================
    template_keys = ['/team']
    if rule_50_template:
        template_keys.append(rule_50_template)

    # =========================================================================
    # SEND TEMPLATE
    # =========================================================================
    await message_manager.send_template(
        user=user,
        template_key=template_keys,
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

            # 50% rule data
            'capped_count': capped_count,

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
# MARKETING PLAN (5-PAGE CAROUSEL)
# ============================================================================

@team_router.callback_query(F.data.regexp(r"^/team/marketing(?:/(\d+))?$"))
async def show_marketing_info(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Show marketing plan carousel (5 pages).

    Routes:
        /team/marketing   -> Page 1
        /team/marketing/2 -> Page 2
        /team/marketing/3 -> Page 3
        /team/marketing/4 -> Page 4
        /team/marketing/5 -> Page 5
    """
    import re

    logger.info(f"User {user.userID} viewing marketing plan")

    # =========================================================================
    # PARSE PAGE NUMBER
    # =========================================================================
    match = re.match(r"^/team/marketing(?:/(\d+))?$", callback_query.data)
    page = 1
    if match and match.group(1):
        page = int(match.group(1))
        if page < 1 or page > 5:
            page = 1

    # =========================================================================
    # DYNAMIC DATA
    # =========================================================================

    # Pioneer slots left
    pioneer_slots_left = 50
    root_user = session.query(User).filter(User.upline == User.telegramID).first()
    if root_user and root_user.mlmStatus:
        pioneer_count = root_user.mlmStatus.get("pioneerPurchasesCount", 0)
        pioneer_slots_left = max(0, 50 - pioneer_count)

    # User rank markers (for page 3)
    lang = user.lang or "en"
    you_marker = {"en": "← You", "ru": "← Вы", "de": "← Du"}.get(lang, "← You")

    user_rank = user.rank or "start"
    rank_markers = {
        "user_rank_marker_start": you_marker if user_rank == "start" else "",
        "user_rank_marker_builder": you_marker if user_rank == "builder" else "",
        "user_rank_marker_growth": you_marker if user_rank == "growth" else "",
        "user_rank_marker_leadership": you_marker if user_rank == "leadership" else "",
        "user_rank_marker_director": you_marker if user_rank == "director" else "",
    }

    # =========================================================================
    # BUILD TEMPLATE KEY
    # =========================================================================
    if page == 1:
        template_key = '/team/marketing'
    else:
        template_key = f'/team/marketing/{page}'

    # =========================================================================
    # SEND TEMPLATE
    # =========================================================================
    await message_manager.send_template(
        user=user,
        template_key=template_key,
        variables={
            'page': page,
            'total_pages': 5,
            'pioneer_slots_left': pioneer_slots_left,
            **rank_markers
        },
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
    """Show team structure: branch tree with volumes using rgroup."""
    from mlm_system.utils.chain_walker import ChainWalker

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
    # GET BRANCHES DATA - build arrays for rgroup
    # =========================================================================
    branch_prefixes = []
    branch_names = []
    branch_ids = []
    branch_emojis = []
    branch_volumes = []
    branch_teams = []
    branch_indents = []

    cap_limit = 0
    capped_count = 0

    if user.totalVolume and isinstance(user.totalVolume, dict):
        branches = user.totalVolume.get("branches", [])
        cap_limit = user.totalVolume.get("capLimit", 0)

        # Sort by fullVolume descending, take top 5
        branches_sorted = sorted(branches, key=lambda b: b.get("fullVolume", 0), reverse=True)[:5]

        for i, branch in enumerate(branches_sorted):
            is_last = (i == len(branches_sorted) - 1)

            ref_user_id = branch.get("referralUserId")
            ref_user = session.query(User).filter_by(userID=ref_user_id).first() if ref_user_id else None

            # Name (max 15 chars)
            ref_name = branch.get("referralName", "User")
            if " (" in ref_name:
                ref_name = ref_name.split(" (")[0]
            if len(ref_name) > 15:
                ref_name = ref_name[:12] + "..."

            # Rank emoji
            ref_rank = ref_user.rank if ref_user else "start"
            ref_rank_emoji = rank_emoji_map.get(ref_rank, "🔷")

            # Volumes
            full_volume = branch.get("fullVolume", 0)
            capped_volume = branch.get("cappedVolume", full_volume)
            is_capped = branch.get("isCapped", False)

            if is_capped:
                capped_count += 1
                volume_str = f"${full_volume:,.0f} → ${capped_volume:,.0f} ⚠️"
            else:
                volume_str = f"${full_volume:,.0f} ✅"

            # Team size
            team_size = 0
            if ref_user:
                walker = ChainWalker(session)
                team_size = walker.count_downline(ref_user)

            # Tree prefixes
            prefix = "└─" if is_last else "├─"
            indent = "   " if is_last else "│  "

            branch_prefixes.append(prefix)
            branch_names.append(ref_name)
            branch_ids.append(str(ref_user_id or 0))
            branch_emojis.append(ref_rank_emoji)
            branch_volumes.append(volume_str)
            branch_teams.append(str(team_size))
            branch_indents.append(indent)
    else:
        # Fallback: get direct referrals from DB
        direct_referrals = session.query(User).filter(
            User.upline == user.telegramID
        ).order_by(User.personalVolumeTotal.desc()).limit(5).all()

        walker = ChainWalker(session)

        for i, ref in enumerate(direct_referrals):
            is_last = (i == len(direct_referrals) - 1)

            ref_name = ref.firstname or "User"
            if len(ref_name) > 15:
                ref_name = ref_name[:12] + "..."

            ref_rank_emoji = rank_emoji_map.get(ref.rank or "start", "🔷")
            ref_volume = float(ref.fullVolume or ref.personalVolumeTotal or 0)
            team_size = walker.count_downline(ref)

            prefix = "└─" if is_last else "├─"
            indent = "   " if is_last else "│  "

            branch_prefixes.append(prefix)
            branch_names.append(ref_name)
            branch_ids.append(str(ref.userID))
            branch_emojis.append(ref_rank_emoji)
            branch_volumes.append(f"${ref_volume:,.0f} ✅")
            branch_teams.append(str(team_size))
            branch_indents.append(indent)

    # =========================================================================
    # 50% RULE TEMPLATE + NO REFERRALS CHECK
    # =========================================================================
    rule_50_template = None
    no_referrals_template = None

    if not branch_names:
        no_referrals_template = '/team/stats/no_referrals'
    elif cap_limit > 0:
        if capped_count > 0:
            rule_50_template = '/team/stats/rule50_capped'
        else:
            rule_50_template = '/team/stats/rule50_ok'

    template_keys = ['/team/stats']
    if no_referrals_template:
        template_keys.append(no_referrals_template)
    elif rule_50_template:
        template_keys.append(rule_50_template)

    # =========================================================================
    # SEND TEMPLATE with rgroup
    # =========================================================================
    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        variables={
            'branches_count': len(branch_names),
            'cap_limit': f"{cap_limit:,.0f}",
            'capped_count': capped_count,
            'rgroup': {
                'prefix': branch_prefixes,
                'name': branch_names,
                'id': branch_ids,
                'emoji': branch_emojis,
                'volume': branch_volumes,
                'team': branch_teams,
                'indent': branch_indents,
            } if branch_names else None
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