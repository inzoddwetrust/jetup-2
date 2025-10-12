# bot/mlm_scheduler.py
"""
MLM Scheduler - handles all time-based MLM operations.
Runs as background task like NotificationProcessor.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from mlm_system import (
    VolumeService,
    RankService,
    GlobalPoolService,
    timeMachine,
    eventBus,
    MLMEvents
)
from init import Session

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

        # Statistics - правильная типизация
        self.stats = {
            "tasksExecuted": 0,
            "errors": 0,
            "lastError": None,
            "startedAt": datetime.now(timezone.utc),
            "lastExecutedAt": None
        }

    async def run(self):
        """Main scheduler loop."""
        logger.info("MLM Scheduler started")
        self.isRunning = True

        while self.isRunning:
            try:
                await self.checkScheduledTasks()
                await asyncio.sleep(self.checkInterval)
            except Exception as e:
                logger.error(f"Error in MLM Scheduler: {e}")
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
            # 1st of month at 00:00 - reset volumes
            if currentDay == 1 and currentHour == 0:
                await self.executeFirstOfMonthTasks()

            # 3rd of month at 00:00 - calculate Global Pool
            elif currentDay == 3 and currentHour == 0:
                await self.executeThirdOfMonthTasks()

            # 5th of month at 10:00 - distribute payments
            elif currentDay == 5 and currentHour == 10:
                await self.executeFifthOfMonthTasks()

            # Update last month after all tasks done
            if currentDay > 5:
                self.lastMonth = currentMonth

    async def executeDailyTasks(self):
        """Execute daily tasks."""
        logger.info("Executing daily MLM tasks")

        with Session() as session:
            try:
                # Check Grace Day
                if timeMachine.isGraceDay:
                    await self.processGraceDay(session)

                # Update activity statuses
                await self.updateActivityStatuses(session)

                # Check rank qualifications
                rankService = RankService(session)
                results = await rankService.checkAllRanks()

                logger.info(f"Daily tasks complete: {results}")
                self.stats["tasksExecuted"] += 1

                session.commit()

            except Exception as e:
                session.rollback()
                logger.error(f"Error in daily tasks: {e}")
                raise

    async def executeFirstOfMonthTasks(self):
        """Tasks for 1st of month."""
        logger.info("Executing 1st of month tasks")

        with Session() as session:
            try:
                # Save monthly stats before reset
                await self.saveAllMonthlyStats(session)

                # Reset monthly volumes
                volumeService = VolumeService(session)
                await volumeService.resetMonthlyVolumes()

                # Emit event
                await eventBus.emit(MLMEvents.MONTH_STARTED, {
                    "month": timeMachine.currentMonth
                })

                logger.info("1st of month tasks complete")
                self.stats["tasksExecuted"] += 1

                session.commit()

            except Exception as e:
                session.rollback()
                logger.error(f"Error in 1st of month tasks: {e}")
                raise

    async def executeThirdOfMonthTasks(self):
        """Tasks for 3rd of month."""
        logger.info("Executing 3rd of month tasks")

        with Session() as session:
            try:
                # Calculate Global Pool
                poolService = GlobalPoolService(session)
                result = await poolService.calculateMonthlyPool()

                if result["success"]:
                    # Emit event
                    await eventBus.emit(MLMEvents.GLOBAL_POOL_CALCULATED, result)

                logger.info(f"3rd of month tasks complete: {result}")
                self.stats["tasksExecuted"] += 1

                session.commit()

            except Exception as e:
                session.rollback()
                logger.error(f"Error in 3rd of month tasks: {e}")
                raise

    async def executeFifthOfMonthTasks(self):
        """Tasks for 5th of month."""
        logger.info("Executing 5th of month tasks")

        with Session() as session:
            try:
                # Distribute Global Pool
                poolService = GlobalPoolService(session)
                result = await poolService.distributeGlobalPool()

                if result["success"]:
                    # Emit event
                    await eventBus.emit(MLMEvents.GLOBAL_POOL_DISTRIBUTED, result)

                # Process any pending commissions
                await self.processMonthlyPayments(session)

                logger.info(f"5th of month tasks complete: {result}")
                self.stats["tasksExecuted"] += 1

                session.commit()

            except Exception as e:
                session.rollback()
                logger.error(f"Error in 5th of month tasks: {e}")
                raise

    async def processGraceDay(self, session):
        """Process Grace Day bonuses."""
        logger.info("Processing Grace Day")

        # Find users who paid on 1st
        from models import User
        from mlm_system.config.ranks import MINIMUM_PV

        activeUsers = session.query(User).filter(
            User.isActive == True,
            User.lastActiveMonth == timeMachine.currentMonth
        ).all()

        graceDayCount = 0
        for user in activeUsers:
            if user.mlmVolumes:
                monthlyPV = user.mlmVolumes.get("monthlyPV", "0")
                if float(monthlyPV) >= float(MINIMUM_PV):
                    # User paid on Grace Day - could add bonus here
                    graceDayCount += 1

        logger.info(f"Grace Day: {graceDayCount} users activated on 1st")

    async def updateActivityStatuses(self, session):
        """Update all users' activity statuses."""
        from models import User

        rankService = RankService(session)
        users = session.query(User).all()

        updatedCount = 0
        for user in users:
            wasActive = user.isActive
            await rankService.updateMonthlyActivity(user.userID)

            if user.isActive != wasActive:
                updatedCount += 1

                # Emit event
                eventName = MLMEvents.USER_ACTIVATED if user.isActive else MLMEvents.USER_DEACTIVATED
                await eventBus.emit(eventName, {
                    "userId": user.userID,
                    "telegramId": user.telegramID
                })

        logger.info(f"Updated activity status for {updatedCount} users")

    async def saveAllMonthlyStats(self, session):
        """Save monthly statistics for all users."""
        from models import User

        rankService = RankService(session)
        users = session.query(User).all()

        savedCount = 0
        for user in users:
            if await rankService.saveMonthlyStats(user.userID):
                savedCount += 1

        logger.info(f"Saved monthly stats for {savedCount} users")

    async def processMonthlyPayments(self, session):
        """Process any pending monthly payments."""
        from models import Bonus

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
            "stats": self.stats
        }

    async def stop(self):
        """Stop scheduler."""
        logger.info("Stopping MLM Scheduler")
        self.isRunning = False


# Global scheduler instance (will be created in main.py)
scheduler: Optional[MLMScheduler] = None