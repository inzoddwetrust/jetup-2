# handlers/admin/mlm_commands.py
"""
MLM-specific admin commands.

Commands:
    &founder [telegramID]  - Manage Founder status
    &assignrank <telegramID> <rank> - Assign rank (Founders only)
"""
import logging

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from config import Config
from models.user import User
from mlm_system.config.ranks import RANK_CONFIG, Rank
from mlm_system.services.rank_service import RankService
from mlm_system.utils.time_machine import timeMachine

logger = logging.getLogger(__name__)

mlm_router = Router(name="admin_mlm")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_admin(user_id: int) -> bool:
    """Check if user is admin."""
    admin_ids = Config.get(Config.ADMIN_USER_IDS) or []
    return user_id in admin_ids


def get_all_founders(session: Session) -> list:
    """Get all users with Founder status."""
    founders = []
    users = session.query(User).all()

    for user in users:
        if user.mlmStatus and user.mlmStatus.get("isFounder", False):
            founders.append(user)

    return founders


def is_founder(session: Session, telegram_id: int) -> bool:
    """
    Check if user is a Founder.
    Fallback: if no founders exist, DEFAULT_REFERRER_ID is considered founder.
    """
    user = session.query(User).filter_by(telegramID=telegram_id).first()
    if not user:
        return False

    # Check isFounder flag
    if user.mlmStatus and user.mlmStatus.get("isFounder", False):
        return True

    # Fallback: if no founders exist, DEFAULT_REFERRER is founder
    founders = get_all_founders(session)
    if not founders:
        default_ref_id = int(Config.get(Config.DEFAULT_REFERRER_ID))
        return telegram_id == default_ref_id

    return False


def get_available_ranks() -> list:
    """Get list of available ranks from RANK_CONFIG."""
    try:
        config = RANK_CONFIG()
        ranks = []
        for rank_enum in Rank:
            rank_data = config.get(rank_enum, {})
            display_name = rank_data.get("displayName", rank_enum.value)
            percentage = rank_data.get("percentage", 0)
            ranks.append({
                "value": rank_enum.value,
                "display": display_name,
                "percentage": float(percentage * 100)
            })
        return ranks
    except Exception as e:
        logger.error(f"Error getting ranks: {e}")
        # Fallback to hardcoded
        return [
            {"value": "start", "display": "Start", "percentage": 4},
            {"value": "builder", "display": "Builder", "percentage": 8},
            {"value": "growth", "display": "Growth", "percentage": 12},
            {"value": "leadership", "display": "Leadership", "percentage": 15},
            {"value": "director", "display": "Director", "percentage": 18},
        ]


# =============================================================================
# &founder - Manage Founder Status
# =============================================================================

@mlm_router.message(F.text.regexp(r'^&founder'))
async def cmd_founder(
        message: Message,
        user: User,
        session: Session
):
    """
    Manage Founder status.

    Usage:
        &founder              - List all founders
        &founder <telegramID> - Toggle founder status for user
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &founder")

    parts = message.text.strip().split()

    # No arguments - show list of founders
    if len(parts) == 1:
        founders = get_all_founders(session)

        if not founders:
            default_ref_id = Config.get(Config.DEFAULT_REFERRER_ID)
            await message.reply(
                "👑 <b>Founders</b>\n\n"
                "No founders assigned.\n"
                f"Fallback: DEFAULT_REFERRER ({default_ref_id}) acts as founder.\n\n"
                "Usage: <code>&founder &lt;telegramID&gt;</code> to assign",
                parse_mode="HTML"
            )
            return

        lines = ["👑 <b>Current Founders:</b>\n"]
        for f in founders:
            lines.append(
                f"• {f.firstname} {f.surname or ''} "
                f"(TG: {f.telegramID}, ID: {f.userID})"
            )

        lines.append(f"\nTotal: {len(founders)}")
        lines.append("\nUsage: <code>&founder &lt;telegramID&gt;</code> to toggle")

        await message.reply("\n".join(lines), parse_mode="HTML")
        return

    # With argument - toggle founder status
    try:
        target_telegram_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Invalid telegramID. Must be a number.")
        return

    target_user = session.query(User).filter_by(telegramID=target_telegram_id).first()

    if not target_user:
        await message.reply(f"❌ User with telegramID {target_telegram_id} not found.")
        return

    # Initialize mlmStatus if needed
    if not target_user.mlmStatus:
        target_user.mlmStatus = {}

    # Toggle founder status
    current_status = target_user.mlmStatus.get("isFounder", False)
    new_status = not current_status

    target_user.mlmStatus["isFounder"] = new_status

    if new_status:
        target_user.mlmStatus["founderGrantedAt"] = timeMachine.now.isoformat()
        target_user.mlmStatus["founderGrantedBy"] = message.from_user.id
    else:
        target_user.mlmStatus.pop("founderGrantedAt", None)
        target_user.mlmStatus.pop("founderGrantedBy", None)

    flag_modified(target_user, 'mlmStatus')
    session.commit()

    status_text = "✅ GRANTED" if new_status else "❌ REVOKED"

    await message.reply(
        f"👑 <b>Founder Status {status_text}</b>\n\n"
        f"User: {target_user.firstname} {target_user.surname or ''}\n"
        f"TelegramID: {target_user.telegramID}\n"
        f"UserID: {target_user.userID}\n"
        f"Is Founder: {'Yes' if new_status else 'No'}",
        parse_mode="HTML"
    )

    logger.info(
        f"Admin {message.from_user.id} {'granted' if new_status else 'revoked'} "
        f"founder status for user {target_user.userID} (TG: {target_telegram_id})"
    )


# =============================================================================
# &assignrank - Assign Rank (Founders Only)
# =============================================================================

@mlm_router.message(F.text.regexp(r'^&assignrank'))
async def cmd_assignrank(
        message: Message,
        user: User,
        session: Session
):
    """
    Assign rank to user. Only Founders can use this command.

    Usage:
        &assignrank                      - Show available ranks
        &assignrank <telegramID> <rank>  - Assign rank to user
    """
    if not is_admin(message.from_user.id):
        return

    logger.info(f"Admin {message.from_user.id} triggered &assignrank")

    parts = message.text.strip().split()

    # No arguments - show available ranks
    if len(parts) == 1:
        ranks = get_available_ranks()

        lines = ["📊 <b>Available Ranks:</b>\n"]
        for r in ranks:
            lines.append(f"• <code>{r['value']}</code> - {r['display']} ({r['percentage']:.0f}%)")

        lines.append("\n<b>Usage:</b>")
        lines.append("<code>&assignrank &lt;telegramID&gt; &lt;rank&gt;</code>")
        lines.append("\n⚠️ Only Founders can assign ranks.")

        await message.reply("\n".join(lines), parse_mode="HTML")
        return

    # Check if caller is founder
    if not is_founder(session, message.from_user.id):
        founders = get_all_founders(session)

        if founders:
            founder_list = ", ".join([str(f.telegramID) for f in founders])
            await message.reply(
                f"❌ <b>Access Denied</b>\n\n"
                f"Only Founders can assign ranks.\n"
                f"Current founders: {founder_list}",
                parse_mode="HTML"
            )
        else:
            default_ref_id = Config.get(Config.DEFAULT_REFERRER_ID)
            await message.reply(
                f"❌ <b>Access Denied</b>\n\n"
                f"Only Founders can assign ranks.\n"
                f"No founders assigned. DEFAULT_REFERRER ({default_ref_id}) can assign.",
                parse_mode="HTML"
            )
        return

    # Need 2 arguments: telegramID and rank
    if len(parts) < 3:
        await message.reply(
            "❌ Missing arguments.\n\n"
            "Usage: <code>&assignrank &lt;telegramID&gt; &lt;rank&gt;</code>\n"
            "Example: <code>&assignrank 123456789 builder</code>",
            parse_mode="HTML"
        )
        return

    # Parse arguments
    try:
        target_telegram_id = int(parts[1])
    except ValueError:
        await message.reply("❌ Invalid telegramID. Must be a number.")
        return

    new_rank = parts[2].lower()

    # Validate rank
    valid_ranks = [r["value"] for r in get_available_ranks()]
    if new_rank not in valid_ranks:
        await message.reply(
            f"❌ Invalid rank: <code>{new_rank}</code>\n\n"
            f"Valid ranks: {', '.join(valid_ranks)}",
            parse_mode="HTML"
        )
        return

    # Find target user
    target_user = session.query(User).filter_by(telegramID=target_telegram_id).first()

    if not target_user:
        await message.reply(f"❌ User with telegramID {target_telegram_id} not found.")
        return

    # Get founder user for the service
    founder_user = session.query(User).filter_by(telegramID=message.from_user.id).first()

    if not founder_user:
        await message.reply("❌ Your user record not found.")
        return

    # Store old rank for reporting
    old_rank = target_user.rank or "start"

    # Use RankService to assign rank
    rank_service = RankService(session)
    success = await rank_service.assignRankByFounder(
        userId=target_user.userID,
        newRank=new_rank,
        founderId=founder_user.userID
    )

    if success:
        # Get display names
        ranks = get_available_ranks()
        old_display = next((r["display"] for r in ranks if r["value"] == old_rank), old_rank)
        new_display = next((r["display"] for r in ranks if r["value"] == new_rank), new_rank)

        await message.reply(
            f"✅ <b>Rank Assigned</b>\n\n"
            f"User: {target_user.firstname} {target_user.surname or ''}\n"
            f"TelegramID: {target_user.telegramID}\n"
            f"UserID: {target_user.userID}\n\n"
            f"Old rank: {old_display}\n"
            f"New rank: <b>{new_display}</b>\n\n"
            f"Assigned by: {founder_user.firstname} (Founder)",
            parse_mode="HTML"
        )

        logger.info(
            f"Founder {founder_user.userID} assigned rank {new_rank} "
            f"to user {target_user.userID} (was: {old_rank})"
        )
    else:
        await message.reply(
            f"❌ Failed to assign rank.\n"
            f"Check logs for details.",
            parse_mode="HTML"
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = ['mlm_router']