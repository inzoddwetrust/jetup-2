# mlm_system/services/volume_service.py
"""
Volume tracking service for MLM system with 50% rule.
"""
from decimal import Decimal
from typing import List, Dict, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timezone
import logging

from models.user import User
from models.purchase import Purchase
from models.volume_queue import VolumeUpdateTask
from mlm_system.config.ranks import RANK_CONFIG, Rank, MINIMUM_PV
from mlm_system.utils.time_machine import timeMachine

logger = logging.getLogger(__name__)


class VolumeService:
    """Service for tracking personal and team volumes with 50% rule."""

    def __init__(self, session: Session):
        self.session = session

    # ============================================================
    # PUBLIC API - Main entry points
    # ============================================================

    async def updatePurchaseVolumes(self, purchase: Purchase):
        """
        Update volumes after a purchase.
        Fast operation - only updates PV and FV, queues TV recalculation.

        Args:
            purchase: Purchase object
        """
        purchaseAmount = Decimal(str(purchase.packPrice))
        currentMonth = timeMachine.currentMonth
        user = purchase.user

        logger.info(f"Updating volumes for purchase {purchase.purchaseID}, amount={purchaseAmount}")

        # 1. Update purchaser's Personal Volume (fast)
        await self._updatePersonalVolume(user, purchaseAmount, currentMonth)

        # 2. Update Full Volume up the chain (fast, simple sum)
        await self._updateFullVolumeChain(user, purchaseAmount)

        # 3. Queue Total Volume recalculation for entire upline (async)
        await self._queueUplineRecalculation(user.userID)

        logger.info(f"Purchase volumes updated, queued TV recalculation")

    async def recalculateTotalVolume(self, userId: int) -> bool:
        """
        Full recalculation of totalVolume JSON with 50% rule.
        Called by background worker from queue.

        Args:
            userId: User ID to recalculate

        Returns:
            True if successful
        """
        try:
            user = self.session.query(User).filter_by(userID=userId).first()
            if not user:
                logger.warning(f"User {userId} not found for TV recalculation")
                return False

            logger.info(f"Recalculating TV for user {userId}")

            # Calculate qualifying volume with 50% rule
            tv_json = await self.calculateQualifyingVolume(userId)

            # Update user record
            user.totalVolume = tv_json
            self.session.commit()

            logger.info(
                f"TV recalculated for user {userId}: "
                f"qualifying={tv_json.get('qualifyingVolume', 0)}, "
                f"full={tv_json.get('fullVolume', 0)}"
            )

            return True

        except Exception as e:
            logger.error(f"Error recalculating TV for user {userId}: {e}", exc_info=True)
            self.session.rollback()
            return False

    async def calculateQualifyingVolume(
            self,
            userId: int,
            targetRank: Optional[str] = None
    ) -> Dict:
        """
        Calculate qualifying TV with 50% rule and generate detailed JSON.

        Args:
            userId: User ID
            targetRank: Target rank (if None, uses next rank from current)

        Returns:
            TV JSON structure with branches details
        """
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return {}

        # Determine target rank
        if not targetRank:
            targetRank = self._getNextRank(user.rank)

        # Get requirements for target rank
        try:
            rankEnum = Rank(targetRank)
            rank_requirements = RANK_CONFIG.get(rankEnum, {})
        except ValueError:
            rank_requirements = {}

        required_tv = rank_requirements.get("teamVolumeRequired", Decimal("0"))

        # Calculate 50% cap limit
        cap_limit = required_tv * Decimal("0.5")

        # Get all branches with their volumes
        branches_data = await self._calculateBranchesVolumes(userId)

        # Apply 50% rule
        qualifying_volume = Decimal("0")
        full_volume_total = Decimal("0")
        branches_json = []

        for branch in branches_data:
            branch_fv = branch["fullVolume"]
            full_volume_total += branch_fv

            # Apply cap
            if branch_fv > cap_limit:
                capped_volume = cap_limit
                is_capped = True
            else:
                capped_volume = branch_fv
                is_capped = False

            qualifying_volume += capped_volume

            branches_json.append({
                "referralTelegramId": branch["telegramId"],
                "referralName": branch["name"],
                "referralUserId": branch["userId"],
                "fullVolume": float(branch_fv),
                "cappedVolume": float(capped_volume),
                "isCapped": is_capped
            })

        # Sort branches by fullVolume (descending)
        branches_json.sort(key=lambda x: x["fullVolume"], reverse=True)

        # Calculate gap
        gap = max(Decimal("0"), required_tv - qualifying_volume)

        # Build final JSON
        tv_json = {
            "qualifyingVolume": float(qualifying_volume),
            "fullVolume": float(full_volume_total),
            "requiredForNextRank": float(required_tv),
            "gap": float(gap),
            "nextRank": targetRank,
            "currentRank": user.rank,
            "capLimit": float(cap_limit),
            "branches": branches_json,
            "calculatedAt": datetime.now(timezone.utc).isoformat()
        }

        return tv_json

    async def getBestBranches(
            self,
            userId: int,
            count: int = 2
    ) -> List[Dict]:
        """
        Get top N branches with Directors for a user.
        Used by Global Pool service.

        CRITICAL: Must prioritize branches WITH Directors over volume!

        Args:
            userId: User ID
            count: Number of top branches to return

        Returns:
            List of branches sorted by:
            1. Has Director (priority)
            2. Volume (secondary)
        """
        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            return []

        # Get branches data
        branches_data = await self._calculateBranchesVolumes(userId)

        # Convert to format expected by GlobalPoolService
        branches = []
        for branch in branches_data:
            referral = self.session.query(User).filter_by(
                userID=branch["userId"]
            ).first()

            if referral:
                has_director = await self._checkForDirectorInBranch(referral)

                branches.append({
                    "rootUser": referral,
                    "rootUserId": referral.userID,
                    "volume": branch["fullVolume"],
                    "hasDirector": has_director
                })

        # ✅ FIX: Sort by hasDirector FIRST, then by volume
        # This ensures branches with Directors are prioritized
        branches.sort(key=lambda x: (not x["hasDirector"], -x["volume"]))

        # Log for debugging
        if len(branches) >= count:
            selected = branches[:count]
            directors_count = sum(1 for b in selected if b["hasDirector"])
            logger.info(
                f"Selected {count} branches for user {userId}: "
                f"{directors_count} with Directors, "
                f"volumes: {[float(b['volume']) for b in selected]}"
            )

        return branches[:count]

    async def resetMonthlyVolumes(self):
        """Reset all monthly volumes - called on 1st of month."""
        logger.info(f"Resetting monthly volumes for {timeMachine.currentMonth}")

        # Reset all users' monthly PV
        allUsers = self.session.query(User).all()

        for user in allUsers:
            if user.mlmVolumes:
                user.mlmVolumes["monthlyPV"] = 0.0

            # Reset monthly activity
            user.isActive = False

        self.session.commit()
        logger.info(f"Reset monthly volumes for {len(allUsers)} users")

    # ============================================================
    # QUEUE MANAGEMENT
    # ============================================================

    async def processQueueBatch(self, batchSize: int = 10) -> int:
        """
        Process batch of volume update tasks from queue.
        Called by background scheduler.

        Args:
            batchSize: Number of tasks to process

        Returns:
            Number of tasks processed
        """
        # Get pending tasks
        tasks = self.session.query(VolumeUpdateTask).filter(
            VolumeUpdateTask.status == 'pending'
        ).order_by(
            VolumeUpdateTask.priority.desc(),
            VolumeUpdateTask.createdAt.asc()
        ).limit(batchSize).all()

        if not tasks:
            return 0

        processed_count = 0

        for task in tasks:
            try:
                # Mark as processing
                task.status = 'processing'
                task.startedAt = datetime.now(timezone.utc)
                task.attempts += 1
                self.session.commit()

                # Recalculate TV
                success = await self.recalculateTotalVolume(task.userId)

                if success:
                    task.status = 'completed'
                    task.completedAt = datetime.now(timezone.utc)
                    processed_count += 1
                else:
                    task.status = 'failed'
                    task.lastError = "Recalculation failed"

                self.session.commit()

            except Exception as e:
                logger.error(f"Error processing task {task.id}: {e}", exc_info=True)
                task.status = 'failed'
                task.lastError = str(e)[:500]
                self.session.commit()

        logger.info(f"Processed {processed_count}/{len(tasks)} volume update tasks")
        return processed_count

    async def _queueUplineRecalculation(self, userId: int):
        """
        Add user and entire upline chain to recalculation queue.
        Avoids duplicates.

        Args:
            userId: Starting user ID
        """
        # Get upline chain
        upline_chain = await self._getUplineChain(userId)

        # Add to queue (check for existing tasks)
        for upline_user_id in upline_chain:
            # Check if already in queue
            existing = self.session.query(VolumeUpdateTask).filter(
                and_(
                    VolumeUpdateTask.userId == upline_user_id,
                    VolumeUpdateTask.status.in_(['pending', 'processing'])
                )
            ).first()

            if not existing:
                task = VolumeUpdateTask(
                    userId=upline_user_id,
                    priority=0
                )
                self.session.add(task)

        self.session.commit()
        logger.info(f"Queued {len(upline_chain)} users for TV recalculation")

    async def _getUplineChain(self, userId: int) -> Set[int]:
        """
        Get complete upline chain for a user.

        Args:
            userId: User ID

        Returns:
            Set of user IDs in upline chain (including self)
        """
        chain = {userId}
        current_user_id = userId

        # Walk up the chain
        max_depth = 50  # Safety limit
        depth = 0

        while depth < max_depth:
            user = self.session.query(User).filter_by(userID=current_user_id).first()
            if not user or not user.upline:
                break

            # Get upline user
            upline_user = self.session.query(User).filter_by(
                telegramID=user.upline
            ).first()

            if not upline_user:
                break

            chain.add(upline_user.userID)
            current_user_id = upline_user.userID
            depth += 1

        return chain

    # ============================================================
    # PRIVATE HELPERS - Volume Calculation
    # ============================================================

    async def _updatePersonalVolume(
            self,
            user: User,
            amount: Decimal,
            currentMonth: str
    ):
        """Update user's Personal Volume (PV)."""
        # Update total PV
        user.personalVolumeTotal = (user.personalVolumeTotal or Decimal("0")) + amount

        # Update monthly PV in JSON
        if not user.mlmVolumes:
            user.mlmVolumes = {}

        user.mlmVolumes["personalTotal"] = float(user.personalVolumeTotal)
        user.mlmVolumes["monthlyPV"] = str(
            Decimal(user.mlmVolumes.get("monthlyPV", "0")) + amount
        )

        # Check activation status
        monthlyPv = Decimal(user.mlmVolumes["monthlyPV"])
        if monthlyPv >= MINIMUM_PV:
            user.isActive = True
            user.lastActiveMonth = currentMonth

            if user.mlmStatus:
                user.mlmStatus["lastActiveMonth"] = currentMonth

        logger.debug(
            f"Updated PV for user {user.userID}: "
            f"total={user.personalVolumeTotal}, monthly={monthlyPv}"
        )

    async def _updateFullVolumeChain(self, user: User, amount: Decimal):
        """
        Update Full Volume up the upline chain.
        Fast operation - simple sum, no 50% rule.
        Uses ChainWalker for safe upline traversal.
        """
        from mlm_system.utils.chain_walker import ChainWalker

        walker = ChainWalker(self.session)

        def update_volume(upline_user: User, level: int) -> bool:
            """Update FV for each upline user."""
            # Update FV (simple sum)
            upline_user.fullVolume = (upline_user.fullVolume or Decimal("0")) + amount

            # DEPRECATED: Also update old teamVolumeTotal for compatibility
            upline_user.teamVolumeTotal = (upline_user.teamVolumeTotal or Decimal("0")) + amount

            logger.debug(
                f"Updated FV for user {upline_user.userID}: {upline_user.fullVolume} "
                f"(level {level})"
            )

            return True  # Continue to next upline

        # Walk up the chain safely
        walker.walk_upline(user, update_volume)

    async def _calculateBranchesVolumes(self, userId: int) -> List[Dict]:
        """
        Calculate FV for each branch (direct referrals).

        Args:
            userId: User ID

        Returns:
            List of branches with their full volumes
        """
        # Get direct referrals
        referrals = self.session.query(User).filter(
            User.upline == self.session.query(User.telegramID).filter_by(
                userID=userId
            ).scalar_subquery()
        ).all()

        branches = []

        for referral in referrals:
            # Calculate FV for this entire branch
            branch_fv = await self._calculateBranchFullVolume(referral.userID)

            branches.append({
                "userId": referral.userID,
                "telegramId": referral.telegramID,
                "name": f"{referral.firstname or 'User'} ({referral.userID})",
                "fullVolume": branch_fv
            })

        return branches

    async def _calculateBranchFullVolume(self, branchRootUserId: int) -> Decimal:
        """
        Calculate total FV for a branch recursively.
        Includes branch root's purchases + all structure below.

        Args:
            branchRootUserId: Root user ID of the branch

        Returns:
            Total FV for this branch
        """
        # Get branch root user
        branch_root = self.session.query(User).filter_by(
            userID=branchRootUserId
        ).first()

        if not branch_root:
            return Decimal("0")

        # Start with branch root's personal purchases
        root_purchases = self.session.query(
            func.sum(Purchase.packPrice)
        ).filter(
            Purchase.userID == branchRootUserId
        ).scalar() or Decimal("0")

        # Add FV from entire structure below (use stored fullVolume)
        # This is already calculated recursively
        structure_fv = branch_root.fullVolume or Decimal("0")

        return root_purchases + structure_fv

    async def _checkForDirectorInBranch(self, rootUser: User) -> bool:
        """
        Check if there's a Director rank in the branch.
        Used by Global Pool service.
        Uses ChainWalker for safe downline traversal.
        """
        from mlm_system.utils.chain_walker import ChainWalker

        # Check root first
        if rootUser.rank == "director":
            return True

        walker = ChainWalker(self.session)
        found_director = [False]  # Use list to allow modification in callback

        def check_director(downline_user: User, level: int):
            """Check each downline user for Director rank."""
            if downline_user.rank == "director":
                found_director[0] = True

        # Walk downline
        walker.walk_downline(rootUser, check_director)

        return found_director[0]

    def _getNextRank(self, currentRank: str) -> str:
        """Get next rank in hierarchy."""
        ranks_order = ["start", "builder", "growth", "leadership", "director"]
        try:
            current_idx = ranks_order.index(currentRank)
            if current_idx < len(ranks_order) - 1:
                return ranks_order[current_idx + 1]
        except ValueError:
            pass
        return "director"  # Default to highest