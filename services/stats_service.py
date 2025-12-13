# jetup-2/services/stats_service.py
"""
Statistics service with update functions for Config dynamic values.

Global statistics (users, projects, invested total) are managed by Config.get_dynamic().
This service provides user-specific statistics and update functions.
"""
import logging
from typing import List
from decimal import Decimal
from sqlalchemy import func

from core.db import get_db_session_ctx
from models.user import User
from models.project import Project
from models.purchase import Purchase

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# GLOBAL STATISTICS UPDATE FUNCTIONS (for Config.register_dynamic)
# ═══════════════════════════════════════════════════════════════════════════

def update_users_count() -> int:
    """
    Get total number of registered users.

    Returns:
        Total user count

    Usage:
        Config.register_dynamic(Config.USERS_COUNT, update_users_count, 600)
    """
    with get_db_session_ctx() as session:
        count = session.query(func.count(User.userID)).scalar() or 0
        logger.debug(f"Updated users_count: {count}")
        return count


def update_projects_count() -> int:
    """
    Get number of active projects (status: active or child).

    Returns:
        Active projects count (distinct projectID)

    Usage:
        Config.register_dynamic(Config.PROJECTS_COUNT, update_projects_count, 3600)
    """
    with get_db_session_ctx() as session:
        count = session.query(
            func.count(func.distinct(Project.projectID))
        ).filter(
            Project.status.in_(["active", "child"])
        ).scalar() or 0

        logger.debug(f"Updated projects_count: {count}")
        return count


def update_invested_total() -> Decimal:
    """
    Get total investment amount (sum of all purchases).

    Returns:
        Total invested amount as Decimal

    Usage:
        Config.register_dynamic(Config.INVESTED_TOTAL, update_invested_total, 300)
    """
    with get_db_session_ctx() as session:
        total = session.query(func.sum(Purchase.packPrice)).scalar()

        if total is None:
            total = Decimal("0")
        else:
            # Ensure it's Decimal (PostgreSQL returns Decimal, but just in case)
            total = Decimal(str(total))

        logger.debug(f"Updated invested_total: {total}")
        return total


def update_sorted_projects() -> List[int]:
    """
    Get list of project IDs sorted by rate field.

    Projects with lower rate appear first.
    Groups by projectID (multiple language versions have same projectID).

    Returns:
        List of project IDs in order

    Usage:
        Config.register_dynamic(Config.SORTED_PROJECTS, update_sorted_projects, 3600)
    """
    with get_db_session_ctx() as session:
        # Get projects sorted by rate
        # group_by projectID to get unique projects (lang versions have same projectID)
        # order by MIN rate among language versions
        projects = session.query(Project.projectID).filter(
            Project.status.in_(["active", "child"])
        ).group_by(Project.projectID).order_by(
            func.min(func.coalesce(Project.rate, 999))  # NULL rates go last
        ).all()

        project_ids = [pid for (pid,) in projects]
        logger.debug(f"Updated sorted_projects: {len(project_ids)} projects")
        return project_ids


# ═══════════════════════════════════════════════════════════════════════════
# USER-SPECIFIC STATISTICS (StatsService class)
# ═══════════════════════════════════════════════════════════════════════════

class StatsService:
    """
    Service for user-specific statistics.

    For global statistics (users count, projects count, etc.),
    use Config.get_dynamic() instead.

    Usage:
        stats_service = get_service(StatsService)
        referrals = await stats_service.get_user_referrals_count(telegram_id)
    """

    async def get_user_referrals_count(
            self,
            telegram_id: int,
            direct_only: bool = True
    ) -> int:
        """
        Get number of referrals for user.

        Args:
            telegram_id: User's Telegram ID
            direct_only: If True, count only direct referrals (level 1)

        Returns:
            Number of referrals
        """
        with get_db_session_ctx() as session:
            if direct_only:
                count = session.query(func.count(User.userID)).filter(
                    User.upline == telegram_id
                ).scalar() or 0
            else:
                # Recursive count all downline
                count = self._count_all_referrals_recursive(session, telegram_id)

            return count

    async def get_user_purchases_total(self, user_id: int) -> Decimal:
        """
        Get total purchases amount for specific user.

        Args:
            user_id: User's internal ID (not telegram ID)

        Returns:
            Total purchase amount as Decimal
        """
        with get_db_session_ctx() as session:
            total = session.query(func.sum(Purchase.packPrice)).filter(
                Purchase.userID == user_id
            ).scalar()

            if total is None:
                return Decimal("0")

            return Decimal(str(total))

    async def get_user_active_downline_count(self, telegram_id: int) -> int:
        """
        Get count of active downline members (who made at least one purchase).

        Args:
            telegram_id: User's Telegram ID

        Returns:
            Count of active downline members
        """
        with get_db_session_ctx() as session:
            # Get all downline user IDs
            downline_ids = self._get_all_downline_ids(session, telegram_id)

            if not downline_ids:
                return 0

            # Count how many have purchases
            active_count = session.query(func.count(func.distinct(Purchase.userID))).filter(
                Purchase.userID.in_(downline_ids)
            ).scalar() or 0

            return active_count

    # ═══════════════════════════════════════════════════════════════════════
    # PRIVATE HELPER METHODS
    # ═══════════════════════════════════════════════════════════════════════

    def _count_all_referrals_recursive(self, session, telegram_id: int, visited: set = None) -> int:
        """
        Recursively count all downline referrals.

        Args:
            session: Database session
            telegram_id: User's Telegram ID
            visited: Set of already visited IDs (cycle protection)

        Returns:
            Total count of all levels
        """
        from config import Config

        # Skip for root user - would cause infinite recursion (all users are his referrals)
        if telegram_id == Config.get(Config.DEFAULT_REFERRER_ID):
            return 0

        # Initialize visited set on first call
        if visited is None:
            visited = set()

        # Cycle protection
        if telegram_id in visited:
            logger.warning(f"Cycle detected in referral chain at {telegram_id}")
            return 0

        visited.add(telegram_id)
        count = 0

        # Get direct referrals
        direct_refs = session.query(User.telegramID).filter(
            User.upline == telegram_id
        ).all()

        for (ref_id,) in direct_refs:
            count += 1  # Count this referral
            count += self._count_all_referrals_recursive(session, ref_id, visited)

        return count

    def _get_all_downline_ids(self, session, telegram_id: int, visited: set = None) -> List[int]:
        """
        Get all downline user IDs recursively.

        Args:
            session: Database session
            telegram_id: User's Telegram ID
            visited: Set of already visited IDs (cycle protection)

        Returns:
            List of user IDs (internal IDs, not telegram IDs)
        """
        from config import Config

        # Skip for root user - would return ALL users in system
        if telegram_id == Config.get(Config.DEFAULT_REFERRER_ID):
            return []

        # Initialize visited set on first call
        if visited is None:
            visited = set()

        # Cycle protection
        if telegram_id in visited:
            logger.warning(f"Cycle detected in referral chain at {telegram_id}")
            return []

        visited.add(telegram_id)
        result = []

        # Get direct referrals
        direct_refs = session.query(User.userID, User.telegramID).filter(
            User.upline == telegram_id
        ).all()

        for user_id, ref_telegram_id in direct_refs:
            result.append(user_id)
            # Recursively get their downline
            result.extend(self._get_all_downline_ids(session, ref_telegram_id, visited))

        return result


# Export
__all__ = [
    'update_users_count',
    'update_projects_count',
    'update_invested_total',
    'update_sorted_projects',
    'StatsService'
]