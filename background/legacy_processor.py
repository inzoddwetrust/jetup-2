# background/legacy_processor.py
"""
Legacy Migration Background Processor - EVENT-DRIVEN ARCHITECTURE

SIMPLIFIED VERSION - most work happens on email verification event.
This background loop is just a FALLBACK for:
- Users who registered before migration system deployed
- Retry failed migrations
- Hourly cleanup

Main processing happens in services/legacy_migration_service.py
triggered by handlers/start.py on email verification.
"""
import asyncio
import logging

from services.legacy_migration_service import LegacyMigrationService

logger = logging.getLogger(__name__)


class LegacyUserProcessor:
    """
    Background processor for legacy user migration - FALLBACK ONLY.

    Architecture Change:
    - OLD: Poll Google Sheets every 10 minutes, process all users
    - NEW: Event-driven on email verify + hourly fallback batch

    This is now just a simple wrapper around LegacyMigrationService.process_batch()
    """

    def __init__(self, check_interval: int = 3600, batch_size: int = 100):
        """
        Initialize legacy processor.

        Args:
            check_interval: Seconds between runs (3600 = 1 hour, reduced from 10min)
            batch_size: Records per batch (increased from 50 to 100)
        """
        self.check_interval = check_interval
        self.batch_size = batch_size
        self._running = False
        self._processing = False

    async def start(self):
        """Start background loop."""
        if self._running:
            logger.warning("Legacy processor already running")
            return

        self._running = True
        logger.info(f"Starting legacy migration processor (interval: {self.check_interval}s)")
        await self._run_migration_loop()

    async def stop(self):
        """Stop background loop."""
        self._running = False
        logger.info("Stopping legacy migration processor")

    async def run_once(self) -> dict:
        """
        Run migration once (for manual trigger via &legacy command).

        Returns:
            Dict with processing stats
        """
        if self._processing:
            raise RuntimeError("Migration already in progress")

        self._processing = True
        try:
            logger.info("Manual legacy migration triggered")

            # SYNC FIRST: Google Sheets ↔ PostgreSQL
            from services.legacy_sync_service import LegacySyncService
            logger.info("Syncing with Google Sheets...")
            sync_stats = await LegacySyncService.sync_all()
            logger.info(f"Sync complete: {sync_stats}")

            # THEN PROCESS
            stats = await LegacyMigrationService.process_batch(self.batch_size)
            logger.info(f"Manual migration complete: {stats}")
            return stats
        finally:
            self._processing = False

    async def _run_migration_loop(self):
        """Main background loop - runs every hour as fallback."""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self._running:
            try:
                # Sleep first
                await asyncio.sleep(self.check_interval)

                # SYNC ONLY: Google Sheets ↔ PostgreSQL
                from services.legacy_sync_service import LegacySyncService
                sync_stats = await LegacySyncService.sync_all()

                if sync_stats.get('v1', {}).get('imported', 0) > 0 or \
                        sync_stats.get('v2', {}).get('imported', 0) > 0:
                    logger.info(f"Hourly sync imported new records: {sync_stats}")

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Critical error in sync loop: {e}", exc_info=True)

                if consecutive_errors >= max_consecutive_errors:
                    break

                await asyncio.sleep(self.check_interval * consecutive_errors)


# Global instance
legacy_processor = LegacyUserProcessor()