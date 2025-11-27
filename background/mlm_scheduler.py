# background/mlm_scheduler.py
"""
MLM Scheduler - handles all time-based MLM operations.
Uses APScheduler for professional task scheduling.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from core.db import get_db_session_ctx
from models.user import User
from models.bonus import Bonus
from mlm_system.services.volume_service import VolumeService
from mlm_system.services.rank_service import RankService
from mlm_system.services.global_pool_service import GlobalPoolService
from mlm_system.utils.time_machine import timeMachine
from mlm_system.events.event_bus import eventBus, MLMEvents

logger = logging.getLogger(__name__)


class MLMScheduler:
    """
    Background scheduler for MLM operations.
    Uses APScheduler for reliable task scheduling.
    """

    def __init__(self, bot):
        """
        Initialize scheduler.

        Args:
            bot: Telegram bot instance
        """
        self.bot = bot
        self.isRunning = False

        # Create APScheduler instance
        self.scheduler = AsyncIOScheduler(
            timezone='UTC',
            job_defaults={
                'coalesce': True,  # Combine missed runs into one
                'max_instances': 1,  # Only one instance of each job at a time
                'misfire_grace_time': 300  # 5 minutes grace period
            }
        )

        # State tracking (for backward compatibility)
        self.lastDay: Optional[int] = None
        self.lastMonth: Optional[str] = None

        # Statistics
        self.stats = {
            "tasksExecuted": 0,
            "errors": 0,
            "lastError": None,
            "startedAt": None,
            "lastExecutedAt": None,
            "volumeQueueProcessed": 0,
            "lastVolumeQueueCheck": None
        }

    async def start(self):
        """
        Start scheduler with all jobs.

        Jobs configured:
        - Volume queue processing: every 30 seconds
        - Scheduled tasks check: every 1 hour
        - Daily tasks: every day at 00:00 UTC
        """
        if self.isRunning:
            logger.warning("MLM Scheduler already running")
            return

        logger.info("=" * 60)
        logger.info("Starting MLM Scheduler with APScheduler")
        logger.info("=" * 60)

        self.isRunning = True
        self.stats["startedAt"] = datetime.now(timezone.utc)

        # ═══════════════════════════════════════════════════════════════
        # JOB 1: Volume Queue Processing (every 30 seconds)
        # ═══════════════════════════════════════════════════════════════
        self.scheduler.add_job(
            func=self._safe_volume_queue_wrapper,
            trigger=IntervalTrigger(seconds=30),
            id='volume_queue',
            name='Volume Queue Processing',
            replace_existing=True
        )
        logger.info("✓ Job registered: Volume Queue (every 30 seconds)")

        # ═══════════════════════════════════════════════════════════════
        # JOB 2: Scheduled Tasks Check (every 1 hour)
        # ═══════════════════════════════════════════════════════════════
        self.scheduler.add_job(
            func=self._safe_scheduled_tasks_wrapper,
            trigger=IntervalTrigger(hours=1),
            id='scheduled_tasks',
            name='Scheduled Tasks Check',
            replace_existing=True
        )
        logger.info("✓ Job registered: Scheduled Tasks (every 1 hour)")

        # ═══════════════════════════════════════════════════════════════
        # JOB 3: Daily Tasks (every day at 00:00 UTC)
        # ═══════════════════════════════════════════════════════════════
        self.scheduler.add_job(
            func=self._safe_daily_tasks_wrapper,
            trigger=CronTrigger(hour=0, minute=0),
            id='daily_tasks',
            name='Daily Tasks (00:00 UTC)',
            replace_existing=True
        )
        logger.info("✓ Job registered: Daily Tasks (00:00 UTC)")

        # Start the scheduler
        self.scheduler.start()

        logger.info("=" * 60)
        logger.info("✅ MLM Scheduler started successfully")
        logger.info(f"Active jobs: {len(self.scheduler.get_jobs())}")
        logger.info("=" * 60)

    async def stop(self):
        """Stop scheduler gracefully."""
        if not self.isRunning:
            return

        logger.info("Stopping MLM Scheduler...")
        self.isRunning = False

        # Shutdown scheduler
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)

        logger.info("✓ MLM Scheduler stopped")

    # ═══════════════════════════════════════════════════════════════════
    # SAFE WRAPPERS (error handling for APScheduler jobs)
    # ═══════════════════════════════════════════════════════════════════

    async def _safe_volume_queue_wrapper(self):
        """Safe wrapper for volume queue processing."""
        try:
            await self.checkVolumeQueue()
        except Exception as e:
            logger.error(f"Error in volume queue job: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)

    async def _safe_scheduled_tasks_wrapper(self):
        """Safe wrapper for scheduled tasks check."""
        try:
            await self.checkScheduledTasks()
        except Exception as e:
            logger.error(f"Error in scheduled tasks job: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)

    async def _safe_daily_tasks_wrapper(self):
        """Safe wrapper for daily tasks."""
        try:
            await self.executeDailyTasks()
        except Exception as e:
            logger.error(f"Error in daily tasks job: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)

    # ═══════════════════════════════════════════════════════════════════
    # ORIGINAL METHODS (unchanged)
    # ═══════════════════════════════════════════════════════════════════

    async def checkScheduledTasks(self):
        """Check and execute scheduled tasks."""
        currentTime = timeMachine.now
        currentDay = currentTime.day
        currentMonth = currentTime.strftime('%Y-%m')
        currentHour = currentTime.hour

        # Daily tasks at 00:00 (handled by APScheduler cron job now)
        # This method now only handles monthly tasks

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
        Called by APScheduler every 30 seconds.
        """
        now = datetime.now(timezone.utc)

        # Process queue
        try:
            with get_db_session_ctx() as session:
                volume_service = VolumeService(session)
                processed = await volume_service.processQueueBatch(batchSize=10)

                if processed > 0:
                    self.stats["volumeQueueProcessed"] += processed
                    self.stats["lastVolumeQueueCheck"] = now
                    logger.info(f"Processed {processed} volume updates from queue")

        except Exception as e:
            logger.error(f"Error processing volume queue: {e}", exc_info=True)
            self.stats["errors"] += 1
            raise  # Re-raise for APScheduler to track

    async def executeDailyTasks(self):
        """Execute daily tasks."""
        logger.info(f"Executing daily tasks for {timeMachine.now.date()}")

        try:
            with get_db_session_ctx() as session:
                # Update rank qualifications
                await self.checkRankQualifications(session)

                # Check Grace Day status
                await self.processGraceDay(session)

            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error in daily tasks: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
            raise  # Re-raise for APScheduler to track

    async def executeFirstOfMonthTasks(self):
        """Execute tasks on 1st of month."""
        logger.info(f"Executing first-of-month tasks for {timeMachine.currentMonth}")

        try:
            with get_db_session_ctx() as session:
                # Reset monthly volumes
                volumeService = VolumeService(session)
                await volumeService.resetMonthlyVolumes()

                # Process Autoship
                await self.processAutoship(session)

                # Fire event
                await eventBus.emit(MLMEvents.MONTH_STARTED, {"month": timeMachine.currentMonth})

            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error in first-of-month tasks: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
            raise  # Re-raise for APScheduler to track

    async def executeSecondOfMonthTasks(self):
        """
        Execute tasks on 2nd of month.

        Tasks:
        - Reset Grace Day streaks for users who didn't purchase on 1st
        """
        logger.info(f"Executing second-of-month tasks for {timeMachine.currentMonth}")

        try:
            with get_db_session_ctx() as session:
                # Import here to avoid circular dependency
                from mlm_system.services.grace_day_service import GraceDayService

                # Reset streaks for users who missed Grace Day
                grace_day_service = GraceDayService(session)
                reset_result = await grace_day_service.resetMonthlyStreaks()

                logger.info(
                    f"Grace Day streak reset complete: "
                    f"{reset_result['resetsCount']} users reset"
                )

            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error in second-of-month tasks: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
            raise  # Re-raise for APScheduler to track

    async def executeThirdOfMonthTasks(self):
        """Execute tasks on 3rd of month."""
        logger.info(f"Executing third-of-month tasks for {timeMachine.currentMonth}")

        try:
            with get_db_session_ctx() as session:
                # Calculate Global Pool
                globalPoolService = GlobalPoolService(session)
                await globalPoolService.calculateMonthlyPool()

                # Save monthly statistics
                await self.saveMonthlyStats(session)

            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error in third-of-month tasks: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
            raise  # Re-raise for APScheduler to track

    async def executeFifthOfMonthTasks(self):
        """Execute tasks on 5th of month."""
        logger.info(f"Executing fifth-of-month tasks for {timeMachine.currentMonth}")

        try:
            with get_db_session_ctx() as session:
                # Process monthly payments
                await self.processMonthlyPayments(session)

                # Fire event
                await eventBus.emit(MLMEvents.PAYMENTS_PROCESSED, {"month": timeMachine.currentMonth})

            self.stats["tasksExecuted"] += 1
            self.stats["lastExecutedAt"] = datetime.now(timezone.utc)

        except Exception as e:
            logger.error(f"Error in fifth-of-month tasks: {e}", exc_info=True)
            self.stats["errors"] += 1
            self.stats["lastError"] = str(e)
            raise  # Re-raise for APScheduler to track

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
        """
        Process pending monthly payments - differential commissions and Global Pool.

        Called on 5th of each month.

        This method:
        1. Finds all pending bonuses (differential + global_pool)
        2. Creates PassiveBalance transactions
        3. Updates user.balancePassive
        4. Changes bonus status to "paid"
        5. Creates notifications for users

        Transaction flow (double-entry bookkeeping):
        - Bonus record: tracking/audit
        - PassiveBalance record: transaction history
        - user.balancePassive: current balance total
        """
        from models import PassiveBalance, Notification
        from decimal import Decimal

        logger.info("Processing monthly payments (differential + global_pool)")

        # Find pending bonuses that should be paid on 5th
        pendingBonuses = session.query(Bonus).filter(
            Bonus.status == "pending",
            Bonus.commissionType.in_(["differential", "global_pool"])
        ).all()

        if not pendingBonuses:
            logger.info("No pending bonuses to process")
            return

        processedCount = 0
        totalAmount = Decimal("0")
        errors = 0

        for bonus in pendingBonuses:
            try:
                # Get user
                user = session.query(User).filter_by(userID=bonus.userID).first()
                if not user:
                    logger.error(f"User {bonus.userID} not found for bonus {bonus.bonusID}")
                    bonus.status = "error"
                    bonus.notes = (bonus.notes or "") + " | User not found"
                    errors += 1
                    continue

                # ═══════════════════════════════════════════════════════════
                # STEP 1: Create PassiveBalance transaction (double-entry)
                # ═══════════════════════════════════════════════════════════
                passive_transaction = PassiveBalance()
                passive_transaction.userID = bonus.userID
                passive_transaction.firstname = user.firstname
                passive_transaction.surname = user.surname
                passive_transaction.amount = bonus.bonusAmount
                passive_transaction.status = "done"
                passive_transaction.reason = f"bonus={bonus.bonusID}"
                passive_transaction.link = ""

                # Set appropriate notes based on bonus type
                if bonus.commissionType == "differential":
                    passive_transaction.notes = f"Differential commission - Level {bonus.uplineLevel or 'N/A'}"
                elif bonus.commissionType == "global_pool":
                    passive_transaction.notes = f"Global Pool {timeMachine.currentMonth}"
                else:
                    passive_transaction.notes = "MLM commission"

                session.add(passive_transaction)

                # ═══════════════════════════════════════════════════════════
                # STEP 2: Update user's passive balance total
                # ═══════════════════════════════════════════════════════════
                user.balancePassive = (user.balancePassive or Decimal("0")) + bonus.bonusAmount

                # ═══════════════════════════════════════════════════════════
                # STEP 3: Update bonus status
                # ═══════════════════════════════════════════════════════════
                bonus.status = "paid"

                # ═══════════════════════════════════════════════════════════
                # STEP 4: Create notification for user (via templates)
                # ═══════════════════════════════════════════════════════════
                try:
                    from core.templates import MessageTemplates

                    # Select appropriate template based on bonus type
                    if bonus.commissionType == "differential":
                        template_key = '/mlm/differential_commission_paid'
                        template_vars = {
                            'bonus_amount': float(bonus.bonusAmount),
                            'level': bonus.uplineLevel or 'N/A',
                            'month': timeMachine.currentMonth
                        }
                    elif bonus.commissionType == "global_pool":
                        template_key = '/mlm/global_pool_paid'
                        template_vars = {
                            'bonus_amount': float(bonus.bonusAmount),
                            'month': timeMachine.currentMonth
                        }
                    else:
                        # Skip notification for unknown types
                        template_key = None

                    if template_key:
                        # Get template text and buttons
                        text, buttons = await MessageTemplates.get_raw_template(
                            template_key,
                            template_vars,
                            lang=user.lang or 'en'
                        )

                        # Create notification
                        notification = Notification(
                            source="mlm_system",
                            text=text,
                            buttons=buttons,
                            targetType="user",
                            targetValue=str(bonus.userID),
                            priority=2,
                            category="mlm",
                            importance="high",
                            parseMode="HTML"
                        )

                        session.add(notification)

                except Exception as notif_error:
                    # Don't fail entire payment if notification fails
                    logger.error(
                        f"Failed to create notification for bonus {bonus.bonusID}: {notif_error}",
                        exc_info=True
                    )

                # Update stats
                processedCount += 1
                totalAmount += bonus.bonusAmount

                logger.info(
                    f"✓ Processed bonus {bonus.bonusID}: "
                    f"${bonus.bonusAmount} ({bonus.commissionType}) "
                    f"for user {user.userID}"
                )

            except Exception as e:
                logger.error(
                    f"Error processing bonus {bonus.bonusID}: {e}",
                    exc_info=True
                )
                bonus.status = "error"
                bonus.notes = (bonus.notes or "") + f" | Error: {str(e)[:200]}"
                errors += 1

        # Commit all changes
        session.commit()

        logger.info(
            f"Monthly payments processed: "
            f"processed={processedCount}, total=${totalAmount}, errors={errors}"
        )

        return {
            "success": True,
            "processed": processedCount,
            "totalAmount": float(totalAmount),
            "errors": errors
        }

    def getStatus(self) -> dict:
        """Get scheduler status."""
        jobs_info = []
        if self.scheduler.running:
            for job in self.scheduler.get_jobs():
                jobs_info.append({
                    "id": job.id,
                    "name": job.name,
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None
                })

        return {
            "isRunning": self.isRunning,
            "schedulerRunning": self.scheduler.running if hasattr(self, 'scheduler') else False,
            "currentTime": timeMachine.now.isoformat(),
            "isTestMode": timeMachine._isTestMode,
            "lastDay": self.lastDay,
            "lastMonth": self.lastMonth,
            "stats": self.stats,
            "jobs": jobs_info
        }


# Global scheduler instance (will be created in main.py)
scheduler: Optional[MLMScheduler] = None