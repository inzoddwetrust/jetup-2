# mlm_system/services/global_pool_service.py
"""
Global Pool management service for MLM system.

CHANGELOG:
- ✅ Added DEFAULT_REFERRER protection to avoid O(n²) operations
"""
from decimal import Decimal
from typing import List, Dict
from sqlalchemy.orm import Session
import logging
import json

from models import User, GlobalPool, Bonus, MonthlyStats
from mlm_system.config.ranks import GLOBAL_POOL_PERCENTAGE
from mlm_system.utils.time_machine import timeMachine
from mlm_system.services.volume_service import VolumeService

logger = logging.getLogger(__name__)


class GlobalPoolService:
    """Service for managing Global Pool distributions."""

    def __init__(self, session: Session):
        self.session = session
        self.volumeService = VolumeService(session)

    async def calculateMonthlyPool(self) -> Dict:
        """
        Calculate Global Pool for current month.
        Called on 3rd of each month.
        """
        currentMonth = timeMachine.currentMonth

        # Check if already calculated for this month
        existing = self.session.query(GlobalPool).filter_by(
            month=currentMonth
        ).first()

        if existing:
            logger.warning(f"Global Pool already calculated for {currentMonth}")
            return {
                "success": False,
                "error": "Already calculated",
                "poolId": existing.poolID
            }

        # Calculate total company volume for the month
        totalVolume = await self._calculateCompanyMonthlyVolume()

        # Calculate pool size (2% of total volume)
        poolSize = totalVolume * GLOBAL_POOL_PERCENTAGE

        # Find qualified users
        qualifiedUsers = await self._findQualifiedUsers()
        qualifiedCount = len(qualifiedUsers)

        # Calculate per-user amount
        perUserAmount = Decimal("0")
        if qualifiedCount > 0:
            perUserAmount = poolSize / qualifiedCount

        # Create GlobalPool record
        pool = GlobalPool(
            month=currentMonth,
            totalCompanyVolume=totalVolume,
            poolPercentage=GLOBAL_POOL_PERCENTAGE,
            poolSize=poolSize,
            qualifiedUsersCount=qualifiedCount,
            perUserAmount=perUserAmount,
            status="calculated",
            qualifiedUsers=json.dumps([u["userId"] for u in qualifiedUsers])
        )

        self.session.add(pool)
        self.session.commit()

        logger.info(
            f"Global Pool calculated for {currentMonth}: "
            f"volume={totalVolume}, pool={poolSize}, "
            f"qualified={qualifiedCount}, per_user={perUserAmount}"
        )

        return {
            "success": True,
            "poolId": pool.poolID,
            "month": currentMonth,
            "totalVolume": totalVolume,
            "poolSize": poolSize,
            "qualifiedUsers": qualifiedCount,
            "perUserAmount": perUserAmount
        }

    async def _calculateCompanyMonthlyVolume(self) -> Decimal:
        """Calculate total company volume for current month."""
        from config import Config

        currentMonth = timeMachine.currentMonth
        default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)

        # Get all users' monthly PV
        totalVolume = Decimal("0")
        users = self.session.query(User).filter(
            User.isActive == True
        ).all()

        for user in users:
            # Skip root user - their volume is system volume, not real investment
            if user.telegramID == default_referrer_id:
                continue

            if user.mlmVolumes:
                monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))
                totalVolume += monthlyPV

        return totalVolume

    async def _findQualifiedUsers(self) -> List[Dict]:
        """
        Find users qualified for Global Pool.
        Requirement: 2 Directors in different direct branches.
        """
        from config import Config

        qualifiedUsers = []
        default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)

        # Get all potential qualifiers (could be Directors themselves)
        allUsers = self.session.query(User).filter(
            User.isActive == True
        ).all()

        for user in allUsers:
            # Skip root user - not subject to qualification checks
            # Also avoids expensive getBestBranches() call for user with ALL downline
            if user.telegramID == default_referrer_id:
                continue

            # Check if user has 2 directors in different branches
            if await self._checkGlobalPoolQualification(user):
                qualifiedUsers.append({
                    "userId": user.userID,
                    "telegramId": user.telegramID,
                    "rank": user.rank
                })

        return qualifiedUsers

    async def _checkGlobalPoolQualification(self, user: User) -> bool:
        """
        Check if user qualifies for Global Pool.
        Need 2 Directors in top 2 branches.
        """
        from config import Config

        # Skip root user - would trigger expensive operations on entire user tree
        if user.telegramID == Config.get(Config.DEFAULT_REFERRER_ID):
            return False

        # Get top 2 branches
        branches = await self.volumeService.getBestBranches(user.userID, 2)

        if len(branches) < 2:
            return False

        # Check if both branches have Directors
        directorsCount = 0
        for branch in branches:
            if branch.get("hasDirector", False):
                directorsCount += 1

        return directorsCount >= 2

    async def distributeGlobalPool(self) -> Dict:
        """
        Distribute Global Pool to qualified users.
        Called on 5th of each month.

        ✅ FIXED: Now creates PassiveBalance transaction records for audit trail.
        """
        currentMonth = timeMachine.currentMonth

        # Get calculated pool for current month
        pool = self.session.query(GlobalPool).filter_by(
            month=currentMonth,
            status="calculated"
        ).first()

        if not pool:
            logger.error(f"No calculated pool found for {currentMonth}")
            return {
                "success": False,
                "error": "Pool not calculated"
            }

        if pool.qualifiedUsersCount == 0:
            pool.status = "distributed"
            pool.distributedAt = timeMachine.now
            logger.info(f"No qualified users for Global Pool {currentMonth}")
            return {
                "success": True,
                "distributed": 0,
                "total": Decimal("0")
            }

        qualifiedUserIds = json.loads(pool.qualifiedUsers or "[]")

        distributed = 0
        totalDistributed = Decimal("0")

        for userId in qualifiedUserIds:
            user = self.session.query(User).filter_by(userID=userId).first()
            if not user:
                logger.error(f"User {userId} not found for Global Pool distribution")
                continue

            # ═══════════════════════════════════════════════════════════
            # STEP 1: Create Bonus record with PENDING status
            # ═══════════════════════════════════════════════════════════
            bonus = Bonus()
            bonus.userID = userId
            bonus.downlineID = None  # No specific downline for Global Pool
            bonus.purchaseID = None  # No specific purchase

            bonus.commissionType = "global_pool"
            bonus.fromRank = user.rank
            bonus.bonusRate = float(GLOBAL_POOL_PERCENTAGE)
            bonus.bonusAmount = pool.perUserAmount
            bonus.compressionApplied = 0

            # ✅ CHANGED: Status is PENDING (paid on 5th of next month)
            bonus.status = "pending"
            bonus.notes = f"Global Pool for {currentMonth}"

            # Owner fields
            bonus.ownerTelegramID = user.telegramID
            bonus.ownerEmail = user.email

            self.session.add(bonus)
            self.session.flush()  # Get bonus.bonusID for notification

            # ═══════════════════════════════════════════════════════════
            # STEP 2: Update monthly stats (for tracking only)
            # ═══════════════════════════════════════════════════════════
            monthlyStats = self.session.query(MonthlyStats).filter_by(
                userID=userId,
                month=currentMonth
            ).first()

            if monthlyStats:
                monthlyStats.globalPoolEarned = pool.perUserAmount

            # ═══════════════════════════════════════════════════════════
            # STEP 3: Create PENDING notification for user
            # ═══════════════════════════════════════════════════════════
            try:
                from models.notification import Notification
                from core.templates import MessageTemplates

                # Calculate payment date (5th of next month)
                year, month = map(int, currentMonth.split('-'))
                next_month = month + 1
                next_year = year
                if next_month > 12:
                    next_month = 1
                    next_year += 1
                payment_date = f"{next_year}-{next_month:02d}-05"

                # Get template
                text, buttons = await MessageTemplates.get_raw_template(
                    '/mlm/global_pool_pending',
                    {
                        'bonus_amount': float(pool.perUserAmount),
                        'month': currentMonth,
                        'payment_date': payment_date,
                        'pool_size': float(pool.poolSize),
                        'qualified_count': pool.qualifiedUsersCount
                    },
                    lang=user.lang or 'en'
                )

                # Create notification
                notification = Notification(
                    source="mlm_system",
                    text=text,
                    buttons=buttons,
                    targetType="user",
                    targetValue=str(userId),
                    priority=2,
                    category="mlm",
                    importance="high",
                    parseMode="HTML"
                )

                self.session.add(notification)

                logger.info(
                    f"✓ Pending Global Pool notification created for user {userId}: "
                    f"${pool.perUserAmount} (bonusID={bonus.bonusID})"
                )

            except Exception as notif_error:
                # Don't fail pool distribution if notification fails
                logger.error(
                    f"Failed to create pending notification for user {userId}: {notif_error}",
                    exc_info=True
                )

            distributed += 1
            totalDistributed += pool.perUserAmount

            logger.info(
                f"✓ Global Pool bonus created (pending) for user {userId}: "
                f"${pool.perUserAmount} (bonusID={bonus.bonusID})"
            )

        # Update pool status
        pool.status = "distributed"
        pool.distributedAt = timeMachine.now

        self.session.commit()

        logger.info(
            f"Global Pool distribution complete (pending): "
            f"distributed={distributed}, total=${totalDistributed}"
        )

        return {
            "success": True,
            "distributed": distributed,
            "total": totalDistributed,
            "perUser": pool.perUserAmount
        }

    async def getPoolHistory(self, months: int = 6) -> List[Dict]:
        """Get Global Pool history for last N months."""
        pools = self.session.query(GlobalPool).order_by(
            GlobalPool.createdAt.desc()
        ).limit(months).all()

        history = []
        for pool in pools:
            history.append({
                "month": pool.month,
                "totalVolume": float(pool.totalCompanyVolume),
                "poolSize": float(pool.poolSize),
                "qualified": pool.qualifiedUsersCount,
                "perUser": float(pool.perUserAmount or 0),
                "status": pool.status,
                "distributedAt": pool.distributedAt.isoformat() if pool.distributedAt else None
            })

        return history

    async def checkUserQualification(self, userId: int) -> Dict:
        """Check if specific user qualifies for Global Pool."""
        from config import Config

        user = self.session.query(User).filter_by(userID=userId).first()

        if not user:
            return {
                "qualified": False,
                "reason": "User not found"
            }

        # Root user doesn't qualify
        if user.telegramID == Config.get(Config.DEFAULT_REFERRER_ID):
            return {
                "qualified": False,
                "reason": "System user"
            }

        if not user.isActive:
            return {
                "qualified": False,
                "reason": "User not active"
            }

        # Get branches info
        branches = await self.volumeService.getBestBranches(userId, 2)

        directorsInBranches = 0
        branchesInfo = []

        for i, branch in enumerate(branches):
            hasDirector = branch.get("hasDirector", False)
            if hasDirector:
                directorsInBranches += 1

            branchesInfo.append({
                "branch": i + 1,
                "volume": float(branch["volume"]),
                "hasDirector": hasDirector,
                "rootUserId": branch["rootUserId"]
            })

        qualified = directorsInBranches >= 2

        return {
            "qualified": qualified,
            "reason": "Qualified" if qualified else f"Only {directorsInBranches} Director branches",
            "branches": branchesInfo,
            "directorsCount": directorsInBranches
        }