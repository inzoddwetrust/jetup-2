# jetup/services/stats_service.py
"""
Statistics service - modern replacement for GlobalVariables.
Caches and updates bot statistics.
"""
import logging
from typing import Any, Dict
from decimal import Decimal
from datetime import datetime
from sqlalchemy import func

from core.db import get_session
from models.user import User
from models.project import Project
from models.purchase import Purchase

logger = logging.getLogger(__name__)


class StatsService:
    """
    Service for managing and caching bot statistics.

    Usage:
        stats_service = get_service(StatsService)
        users_count = await stats_service.get_users_count()
    """

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._cache_timestamps: Dict[str, datetime] = {}
        self._cache_ttl: Dict[str, int] = {
            'users_count': 300,  # 5 minutes
            'projects_count': 3600,  # 1 hour
            'purchases_total': 100,  # 100 seconds
            'sorted_projects': 3600,  # 1 hour
        }

    async def initialize(self):
        """Initialize service and preload cache."""
        logger.info("Initializing StatsService...")
        await self.refresh_all()
        logger.info("StatsService initialized")

    async def get_users_count(self) -> int:
        """Get total number of users."""
        return await self._get_cached('users_count', self._fetch_users_count)

    async def get_projects_count(self) -> int:
        """Get number of active projects."""
        return await self._get_cached('projects_count', self._fetch_projects_count)

    async def get_purchases_total(self) -> float:
        """Get total purchases amount."""
        return await self._get_cached('purchases_total', self._fetch_purchases_total)

    async def get_sorted_projects(self) -> list:
        """Get list of project IDs sorted by rate."""
        return await self._get_cached('sorted_projects', self._fetch_sorted_projects)

    async def get_user_referrals_count(self, telegram_id: int, direct_only: bool = True) -> int:
        """
        Get number of referrals for user.

        Args:
            telegram_id: User's Telegram ID
            direct_only: If True, count only direct referrals

        Returns:
            Number of referrals
        """
        session = get_session()
        try:
            if direct_only:
                count = session.query(func.count(User.userID)).filter(
                    User.upline == telegram_id
                ).scalar() or 0
            else:
                # Recursive count all downline
                count = self._count_all_referrals_recursive(session, telegram_id)

            return count
        finally:
            session.close()

    async def get_user_purchases_total(self, user_id: int) -> Decimal:
        """Get total purchases amount for user."""
        session = get_session()
        try:
            total = session.query(func.sum(Purchase.packPrice)).filter(
                Purchase.userID == user_id
            ).scalar() or Decimal("0")

            return Decimal(str(total))
        finally:
            session.close()

    async def refresh_all(self):
        """Refresh all cached statistics."""
        logger.info("Refreshing all statistics...")

        await self._fetch_users_count(force=True)
        await self._fetch_projects_count(force=True)
        await self._fetch_purchases_total(force=True)
        await self._fetch_sorted_projects(force=True)

        logger.info("All statistics refreshed")

    # ========================================================================
    # PRIVATE METHODS
    # ========================================================================

    async def _get_cached(self, key: str, fetch_func):
        """Get value from cache or fetch if expired."""
        now = datetime.utcnow()

        # Check if cached and not expired
        if key in self._cache and key in self._cache_timestamps:
            age = (now - self._cache_timestamps[key]).total_seconds()
            ttl = self._cache_ttl.get(key, 300)

            if age < ttl:
                return self._cache[key]

        # Fetch new value
        value = await fetch_func()
        self._cache[key] = value
        self._cache_timestamps[key] = now

        return value

    async def _fetch_users_count(self, force: bool = False) -> int:
        """Fetch total users count from database."""
        session = get_session()
        try:
            count = session.query(func.count(User.userID)).scalar() or 0
            logger.debug(f"Users count: {count}")
            return count
        finally:
            session.close()

    async def _fetch_projects_count(self, force: bool = False) -> int:
        """Fetch active projects count."""
        session = get_session()
        try:
            count = session.query(
                func.count(func.distinct(Project.projectID))
            ).filter(
                Project.status.in_(["active", "child"])
            ).scalar() or 0

            logger.debug(f"Projects count: {count}")
            return count
        finally:
            session.close()

    async def _fetch_purchases_total(self, force: bool = False) -> float:
        """Fetch total purchases amount."""
        session = get_session()
        try:
            total = session.query(func.sum(Purchase.packPrice)).scalar() or 0
            logger.debug(f"Purchases total: {total}")
            return float(total)
        finally:
            session.close()

    async def _fetch_sorted_projects(self, force: bool = False) -> list:
        """Fetch project IDs sorted by rate."""
        session = get_session()
        try:
            projects = session.query(Project.projectID).filter(
                Project.status.in_(["active", "child"])
            ).group_by(Project.projectID).order_by(
                func.min(func.coalesce(Project.rate, 999))
            ).all()

            project_ids = [pid for (pid,) in projects]
            logger.debug(f"Sorted projects: {len(project_ids)} projects")
            return project_ids
        finally:
            session.close()

    def _count_all_referrals_recursive(self, session, telegram_id: int, visited: set = None) -> int:
        """Recursively count all referrals in downline."""
        if visited is None:
            visited = set()

        if telegram_id in visited:
            return 0

        visited.add(telegram_id)

        referrals = session.query(User.telegramID).filter(
            User.upline == telegram_id
        ).all()

        total = 0
        for (ref_id,) in referrals:
            if ref_id not in visited:
                total += 1 + self._count_all_referrals_recursive(session, ref_id, visited)

        return total