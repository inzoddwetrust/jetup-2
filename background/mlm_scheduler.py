# background/mlm_scheduler.py
"""
MLM Scheduler - handles all time-based MLM operations.
Runs as background task with volume queue processing.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from core.db import get_session
from models.user import User
from models.bonus import Bonus
from mlm_system.services.volume_service import VolumeService
from mlm_system.services.rank_service import RankService
from mlm_system.services.global_pool_service import GlobalPoolService
from mlm_system.utils.time_machine import timeMachine
from mlm_system.events.event_bus import eventBus, MLMEvents

logger = logging.getLogger(__name__)


class MLMScheduler:
    """Background scheduler for MLM operations."""

    def __init__(self, bot, checkInterval: int = 3600):
        """
        Initialize scheduler.

        Args:
            bot: Telegram bot instance
            checkInterval: Check interval in seconds (default 1 hour)
        """
        self.bot = bot
        self.checkInterval = checkInterval
        self.lastDay: Optional[int] = None
        self.lastMonth: Optional[str] = None
        self.isRunning = False

        # Volume queue processing interval (30 seconds)
        self.queueCheckInterval = 30
        self.lastQueueCheck: Optional[datetime] = None

        # Statistics
        self.stats = {
            "tasksExecuted": 0,
            "errors": 0,
            "lastError": None,
            "startedAt": datetime.now(timezone.utc),
            "lastExecutedAt": None,
            "volumeQueueProcessed": 0,
            "lastVolumeQueueCheck": None
        }

    async def run(self):
        """Main scheduler loop."""
        logger.info("MLM Scheduler started")
        self.isRunning = True

        while self.isRunning:
            try:
                # Check scheduled tasks (hourly checks)
                await self.checkScheduledTasks()

                # Process volume queue (every 30 seconds)
                await self.checkVolumeQueue()

                await asyncio.sleep(self.checkInterval)

            except Exception as e:
                logger.error(f"Error in MLM Scheduler: {e}", exc_info=True)
                self.stats["errors"] += 1
                self.stats["lastError"] = str(e)
                await asyncio.sleep(60)  # Short pause on error

    async def checkScheduledTasks(self):
        """Check and execute scheduled tasks."""
        currentTime = timeMachine.now
        currentDay = currentTime.day
        currentMonth = currentTime.strftime('%Y-%m')
        currentHour = currentTime.hour

        # Daily tasks at 00:00
        if currentHour == 0 and self.lastDay != currentDay:
            await self.executeDailyTasks()
            self.lastDay = currentDay

        # Monthly tasks
        if self.lastMonth != currentMonth:
            # 1st of month at 00:00 - reset volumes, process Autoship
            if currentDay == 1 and currentHour == 0:
                await self.executeFirstOfMonthTasks()

            # ✨ NEW: 2nd of month at 00:00 - reset Grace Day streaks
            elif currentDay == 2 and currentHour == 0:
                await self.executeSecondOfMonthTasks()

            # 3rd of month at 00:00 - calculate Global Pool
            elif currentDay == 3 and currentHour == 0:
                await self.executeThirdOfMonthTasks()

            # 5th of month at 10:00 - distribute payments
            elif currentDay == 5 and currentHour == 10:
                await self.executeFifthOfMonthTasks()

            # Update last month after all tasks done
            if currentDay > 5:
                self.lastMonth = currentMonth

    async def checkVolumeQueue(self):
        """
        Check and process volume update queue.
        Runs every 30 seconds independently of main scheduler.
        """
        now = datetime.now(timezone.utc)

        # Check if enough time passed since last queue check
        if self.lastQueueCheck:
            elapsed = (now - self.lastQueueCheck).total_seconds()
            if elapsed < self.queueCheckInterval:
                return  # Not time yet

        # Update last check time
        self.lastQueueCheck = now

        # Process queue
        session = get_session()
        try:
            volume_service = VolumeService(session)
            processed = await volume_service.processQueueBatch(batchSize=10)

            if processed > 0:
                self.stats["volumeQueueProcessed"] += processed
                self.stats["lastVolumeQueueCheck"] = now.isoformat()
                logger.info(f"Processed {processed} volume updates from queue")

        except Exception as e:
            logger.error(f"Error processing volume queue: {e}", exc_info=True)
            self.stats["errors"] += 1
        finally:
            session.close()

    async def executeDailyTasks(self):
        """Execute daily tasks."""
        logger.info(f"Executing daily tasks for {timeMachine.now.date()}")
        session = get_session()

        try:
            # Update rank qualifications
            await self.checkRankQualifications(session)

            # Check Grace Day status
            await self.processGraceDay(session)

            session.commit()
            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Error in daily tasks: {e}", exc_info=True)
            session.rollback()
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
        finally:
            session.close()

    async def executeFirstOfMonthTasks(self):
        """Execute tasks on 1st of month."""
        logger.info(f"Executing first-of-month tasks for {timeMachine.currentMonth}")
        session = get_session()

        try:
            # Reset monthly volumes
            volumeService = VolumeService(session)
            await volumeService.resetMonthlyVolumes()

            # Process Autoship
            await self.processAutoship(session)

            # Fire event
            await eventBus.emit(MLMEvents.MONTH_STARTED, {"month": timeMachine.currentMonth})

            session.commit()
            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Error in first-of-month tasks: {e}", exc_info=True)
            session.rollback()
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
        finally:
            session.close()

    async def executeSecondOfMonthTasks(self):
        """
        Execute tasks on 2nd of month.

        Tasks:
        - Reset Grace Day streaks for users who didn't purchase on 1st
        """
        logger.info(f"Executing second-of-month tasks for {timeMachine.currentMonth}")
        session = get_session()

        try:
            # Import here to avoid circular dependency
            from mlm_system.services.grace_day_service import GraceDayService

            # Reset streaks for users who missed Grace Day
            grace_day_service = GraceDayService(session)
            reset_result = await grace_day_service.resetMonthlyStreaks()

            logger.info(
                f"Grace Day streak reset complete: "
                f"{reset_result['resetsCount']} users reset"
            )

            session.commit()
            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Error in second-of-month tasks: {e}", exc_info=True)
            session.rollback()
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
        finally:
            session.close()

    async def executeThirdOfMonthTasks(self):
        """Execute tasks on 3rd of month."""
        logger.info(f"Executing third-of-month tasks for {timeMachine.currentMonth}")
        session = get_session()

        try:
            # Calculate Global Pool
            globalPoolService = GlobalPoolService(session)
            await globalPoolService.calculateMonthlyPool()

            # Save monthly statistics
            await self.saveMonthlyStats(session)

            session.commit()
            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Error in third-of-month tasks: {e}", exc_info=True)
            session.rollback()
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
        finally:
            session.close()

    async def executeFifthOfMonthTasks(self):
        """Execute tasks on 5th of month."""
        logger.info(f"Executing fifth-of-month tasks for {timeMachine.currentMonth}")
        session = get_session()

        try:
            # Process monthly payments
            await self.processMonthlyPayments(session)

            # Fire event
            await eventBus.emit(MLMEvents.PAYMENTS_PROCESSED, {"month": timeMachine.currentMonth})

            session.commit()
            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc).isoformat()

        except Exception as e:
            logger.error(f"Error in fifth-of-month tasks: {e}", exc_info=True)
            session.rollback()
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
        finally:
            session.close()

    async def checkRankQualifications(self, session):
        """Check rank qualifications for all users."""
        rankService = RankService(session)
        users = session.query(User).filter(User.isActive == True).all()

        updatedCount = 0
        for user in users:
            newRank = await rankService.checkRankQualification(user.userID)
            if newRank:
                await rankService.updateUserRank(user.userID, newRank)
                updatedCount += 1

        if updatedCount > 0:
            logger.info(f"Updated ranks for {updatedCount} users")

    async def processGraceDay(self, session):
        """
        Process Grace Day bonuses if applicable.

        NOTE: Grace Day bonus is now handled in event handler
        (mlm_system/events/handlers.py) when PURCHASE_COMPLETED is emitted.

        This method is kept for potential future Grace Day-specific tasks.
        """
        if not timeMachine.isGraceDay:
            return

        logger.info("Grace Day active - bonuses will be processed on purchase")

    async def processAutoship(self, session):
        """Process Autoship subscriptions."""
        logger.info("Processing Autoship subscriptions")

        # Find users with Autoship enabled
        users = session.query(User).filter(
            User.mlmVolumes.isnot(None)
        ).all()

        autoshipCount = 0
        for user in users:
            if not user.mlmVolumes:
                continue

            autoship_config = user.mlmVolumes.get("autoship", {})
            if autoship_config.get("enabled", False):
                # TODO: Implement Autoship purchase logic
                # This will be implemented later as per CODE_COMPLIANCE_REPORT
                autoshipCount += 1

        logger.info(f"Found {autoshipCount} users with Autoship enabled")

    async def saveMonthlyStats(self, session):
        """Save monthly statistics for all users."""
        rankService = RankService(session)
        users = session.query(User).all()

        savedCount = 0
        for user in users:
            if await rankService.saveMonthlyStats(user.userID):
                savedCount += 1

        logger.info(f"Saved monthly stats for {savedCount} users")

    async def processMonthlyPayments(self, session):
        """Process any pending monthly payments."""
        # Mark all pending bonuses as processed
        pendingBonuses = session.query(Bonus).filter(
            Bonus.status == "pending"
        ).all()

        processedCount = 0
        for bonus in pendingBonuses:
            bonus.status = "paid"
            processedCount += 1

        if processedCount > 0:
            logger.info(f"Processed {processedCount} pending bonuses")

    def getStatus(self) -> dict:
        """Get scheduler status."""
        return {
            "isRunning": self.isRunning,
            "currentTime": timeMachine.now.isoformat(),
            "isTestMode": timeMachine._isTestMode,
            "lastDay": self.lastDay,
            "lastMonth": self.lastMonth,
            "checkInterval": self.checkInterval,
            "queueCheckInterval": self.queueCheckInterval,
            "stats": self.stats
        }

    async def stop(self):
        """Stop scheduler."""
        logger.info("Stopping MLM Scheduler")
        self.isRunning = False


# Global scheduler instance (will be created in main.py)
scheduler: Optional[MLMScheduler] = None