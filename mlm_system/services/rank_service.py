# mlm_system/services/rank_service.py
"""
Rank management service for MLM system.
"""
from decimal import Decimal
from typing import Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified
import logging

from models.user import User
from models.bonus import Bonus
from models.mlm.rank_history import RankHistory
from models.mlm.monthly_stats import MonthlyStats
from mlm_system.config.ranks import RANK_CONFIG, Rank
from mlm_system.utils.time_machine import timeMachine

logger = logging.getLogger(__name__)


class RankService:
    """Service for managing user ranks and qualifications."""

    def __init__(self, session: Session):
        self.session = session

    async def checkRankQualification(self, userId: int) -> Optional[str]:
        """
        Check if user qualifies for a new rank.
        Returns new rank if qualified, None otherwise.
        """
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return None

        currentRank = user.rank or "start"

        # Check each rank from highest to lowest
        for rankEnum in [Rank.DIRECTOR, Rank.LEADERSHIP, Rank.GROWTH, Rank.BUILDER]:
            rank = rankEnum.value

            # Skip if already at or above this rank
            if self._compareRanks(currentRank, rank) >= 0:
                continue

            # Check qualification
            if await self._isQualifiedForRank(user, rank):
                logger.info(f"User {userId} qualified for rank {rank}")
                return rank

        return None

    async def _isQualifiedForRank(self, user: User, rank: str) -> bool:
        """
        Check if user meets requirements for specific rank.
        Uses totalVolume.qualifyingVolume with 50% rule applied.
        """
        try:
            rankEnum = Rank(rank)
            requirements = RANK_CONFIG()[rankEnum]
        except (ValueError, KeyError):
            return False

        # Use qualifying volume with 50% rule from totalVolume JSON
        if user.totalVolume and isinstance(user.totalVolume, dict):
            qualifying_volume = Decimal(str(user.totalVolume.get("qualifyingVolume", 0)))
        else:
            # Fallback to old field if totalVolume not calculated yet
            qualifying_volume = user.teamVolumeTotal or Decimal("0")
            logger.warning(
                f"User {user.userID} has no totalVolume JSON, "
                f"using teamVolumeTotal={qualifying_volume} as fallback"
            )

        required_tv = requirements["teamVolumeRequired"]

        # Check team volume requirement
        if qualifying_volume < required_tv:
            logger.debug(
                f"User {user.userID} not qualified for {rank}: "
                f"qualifying_volume={qualifying_volume} < required={required_tv}"
            )
            return False

        # Check active partners (counts ENTIRE structure, not just level 1)
        activePartners = await self._countActivePartners(user)
        required_partners = requirements["activePartnersRequired"]

        if activePartners < required_partners:
            logger.debug(
                f"User {user.userID} not qualified for {rank}: "
                f"active_partners={activePartners} < required={required_partners}"
            )
            return False

        logger.info(
            f"User {user.userID} QUALIFIED for {rank}: "
            f"TV={qualifying_volume} (required={required_tv}), "
            f"partners={activePartners} (required={required_partners})"
        )

        return True

    async def _countActivePartners(self, user: User) -> int:
        """
        Count active partners in user's ENTIRE structure.

        Active partner = user with isActive == True anywhere in downline.
        Uses ChainWalker for safe recursive traversal.

        Args:
            user: User to count active partners for

        Returns:
            Count of active users in entire downline
        """
        from mlm_system.utils.chain_walker import ChainWalker

        walker = ChainWalker(self.session)
        return walker.count_active_downline(user)

    async def _countTotalTeamSize(self, user: User) -> int:
        """
        Count total team size recursively.
        Uses ChainWalker for safe downline traversal.
        """
        from mlm_system.utils.chain_walker import ChainWalker

        walker = ChainWalker(self.session)
        return walker.count_downline(user)

    async def updateUserRank(self, userId: int, newRank: str, method: str = "natural") -> bool:
        """
        Update user's rank and record in history.

        Args:
            userId: User ID
            newRank: New rank value
            method: How rank was achieved - "natural", "assigned", "founder"

        Returns:
            True if rank updated successfully
        """
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return False

        oldRank = user.rank

        # Don't downgrade ranks (ranks are preserved once achieved)
        if self._compareRanks(newRank, oldRank) <= 0:
            logger.info(f"User {userId} already has rank {oldRank}, skipping update to {newRank}")
            return False

        # Update rank
        user.rank = newRank

        # Record in history
        history = RankHistory(
            userID=userId,
            oldRank=oldRank,
            newRank=newRank,
            qualificationMethod=method,
            qualifiedAt=timeMachine.now,
            month=timeMachine.currentMonth
        )
        self.session.add(history)

        # Update mlmStatus
        if not user.mlmStatus:
            user.mlmStatus = {}
        user.mlmStatus["rankQualifiedAt"] = timeMachine.now.isoformat()

        flag_modified(user, 'mlmStatus')

        self.session.commit()

        logger.info(
            f"User {userId} rank updated: {oldRank} → {newRank} "
            f"(method: {method})"
        )

        return True

    async def assignRankByFounder(
            self,
            userId: int,
            newRank: str,
            founderId: int
    ) -> bool:
        """
        Assign rank to user by founder.
        Only founders can assign ranks.
        """
        # Check if assigner is a founder
        founder = self.session.query(User).filter_by(userID=founderId).first()
        if not founder:
            logger.error(f"Founder {founderId} not found")
            return False

        if not founder.mlmStatus or not founder.mlmStatus.get("isFounder", False):
            logger.error(f"User {founderId} is not a founder, cannot assign ranks")
            return False

        # Get target user
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            logger.error(f"User {userId} not found")
            return False

        oldRank = user.rank

        # Assign rank
        user.rank = newRank

        if not user.mlmStatus:
            user.mlmStatus = {}
        user.mlmStatus["assignedRank"] = newRank
        user.mlmStatus["assignedBy"] = founderId
        user.mlmStatus["assignedAt"] = timeMachine.now.isoformat()

        flag_modified(user, 'mlmStatus')

        # Record in history
        history = RankHistory(
            userID=userId,
            oldRank=oldRank,
            newRank=newRank,
            qualificationMethod="assigned",
            qualifiedAt=timeMachine.now,
            month=timeMachine.currentMonth,
            notes=f"Assigned by founder {founderId}"
        )
        self.session.add(history)

        self.session.commit()

        logger.info(f"Rank {newRank} assigned to user {userId} by founder {founderId}")
        return True

    async def getUserActiveRank(self, userId: int) -> str:
        """
        Get user's currently active rank.
        Assigned ranks take priority, but user must be active.
        """
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return "start"

        # If user is not active, they can't use their rank
        if not user.isActive:
            return "start"

        # Check if user has assigned rank
        if user.mlmStatus and user.mlmStatus.get("assignedRank"):
            assignedRank = user.mlmStatus["assignedRank"]

            # Verify if user still qualifies for assigned rank
            if await self._isQualifiedForRank(user, assignedRank):
                return assignedRank
            else:
                logger.warning(
                    f"User {userId} has assigned rank {assignedRank} "
                    f"but doesn't qualify anymore"
                )
                # Fall through to natural rank

        # Return natural rank
        return user.rank or "start"

    async def updateMonthlyActivity(self, userId: int) -> bool:
        """Update user's monthly activity status."""
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return False

        # Check monthly PV
        monthlyPV = Decimal("0")
        if user.mlmVolumes:
            monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))

        # Update activity status
        isActive = monthlyPV >= Decimal("200")
        user.isActive = isActive

        if not user.mlmStatus:
            user.mlmStatus = {}
        user.mlmStatus["lastActiveMonth"] = timeMachine.currentMonth if isActive else None

        flag_modified(user, 'mlmStatus')

        logger.info(f"User {userId} activity updated: {isActive} (PV: {monthlyPV})")
        return True

    async def checkAllRanks(self) -> Dict[str, int]:
        """Check and update ranks for all users."""
        results = {
            "checked": 0,
            "updated": 0,
            "errors": 0
        }

        users = self.session.query(User).all()

        for user in users:
            try:
                results["checked"] += 1

                # Check for new rank qualification
                newRank = await self.checkRankQualification(user.userID)
                if newRank:
                    success = await self.updateUserRank(
                        user.userID,
                        newRank,
                        "natural"
                    )
                    if success:
                        results["updated"] += 1
            except Exception as e:
                logger.error(f"Error checking rank for user {user.userID}: {e}")
                results["errors"] += 1

        self.session.commit()

        logger.info(
            f"Rank check complete: checked={results['checked']}, "
            f"updated={results['updated']}, errors={results['errors']}"
        )

        return results

    def _compareRanks(self, rank1: str, rank2: str) -> int:
        """
        Compare two ranks.
        Returns: -1 if rank1 < rank2, 0 if equal, 1 if rank1 > rank2
        """
        rankOrder = {
            "start": 0,
            "builder": 1,
            "growth": 2,
            "leadership": 3,
            "director": 4
        }

        value1 = rankOrder.get(rank1, 0)
        value2 = rankOrder.get(rank2, 0)

        if value1 < value2:
            return -1
        elif value1 > value2:
            return 1
        else:
            return 0

    async def saveMonthlyStats(self, userId: int) -> bool:
        """Save monthly statistics snapshot for user."""
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return False

        currentMonth = timeMachine.currentMonth

        # Check if stats already exist for this month
        existing = self.session.query(MonthlyStats).filter_by(
            userID=userId,
            month=currentMonth
        ).first()

        if existing:
            logger.info(f"Monthly stats already exist for user {userId}, month {currentMonth}")
            return False

        # Calculate stats
        monthlyPV = Decimal("0")
        if user.mlmVolumes:
            monthlyPV = Decimal(user.mlmVolumes.get("monthlyPV", "0"))

        # Get qualifying volume with 50% rule
        if user.totalVolume and isinstance(user.totalVolume, dict):
            qualifying_tv = Decimal(str(user.totalVolume.get("qualifyingVolume", 0)))
        else:
            qualifying_tv = user.teamVolumeTotal or Decimal("0")

        # Get commission sum for the month
        commissionsEarned = self.session.query(
            func.sum(Bonus.bonusAmount)
        ).filter(
            Bonus.userID == userId,
            func.strftime('%Y-%m', Bonus.createdAt) == currentMonth
        ).scalar() or Decimal("0")

        # Create stats record
        stats = MonthlyStats(
            userID=userId,
            month=currentMonth,
            personalVolume=monthlyPV,
            teamVolume=qualifying_tv,
            activePartnersCount=await self._countActivePartners(user),
            directReferralsCount=self.session.query(func.count(User.userID)).filter(
                User.upline == user.telegramID
            ).scalar() or 0,
            totalTeamSize=await self._countTotalTeamSize(user),
            activeRank=await self.getUserActiveRank(userId),
            commissionsEarned=commissionsEarned,
            bonusesEarned=Decimal("0"),  # Will be filled separately
            globalPoolEarned=Decimal("0"),  # Will be filled by GlobalPoolService
            wasActive=1 if user.isActive else 0
        )

        self.session.add(stats)

        logger.info(f"Monthly stats saved for user {userId}, month {currentMonth}")
        return True