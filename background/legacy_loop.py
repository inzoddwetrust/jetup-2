# background/legacy_loop.py
"""
Legacy Migration Background Loop

Hourly sync: Import from GS + Export to GS
Processing happens only on email verification (instant) or &legacy command (manual).

This loop is ONLY for keeping GS and PostgreSQL in sync for reporting purposes.
"""
import logging
import asyncio
from typing import Optional

from services.legacy_sync import LegacySyncService

logger = logging.getLogger(__name__)


class LegacyBackgroundLoop:
    """
    Background loop for legacy migration sync.

    Runs hourly:
    1. Import new records from GS → PostgreSQL
    2. Export progress from PostgreSQL → GS (for customer reporting)

    Does NOT process migrations — that happens on email verification.
    """

    def __init__(self, interval: int = 3600):
        """
        Initialize background loop.

        Args:
            interval: Seconds between syncs (default: 3600 = 1 hour)
        """
        self.interval = interval
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self):
        """Start background loop."""
        if self._running:
            logger.warning("Legacy background loop already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Legacy background loop started (interval: {self.interval}s)")

    async def stop(self):
        """Stop background loop gracefully."""
        if not self._running:
            return

        self._running = False

        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        logger.info("Legacy background loop stopped")

    async def _run_loop(self):
        """
        Main loop.

        Sleep first, then sync. This gives the bot time to fully start
        before first sync attempt.
        """
        # Initial delay (let bot start up)
        await asyncio.sleep(60)

        while self._running:
            try:
                logger.info("Legacy sync: starting hourly sync...")

                result = await LegacySyncService.sync_all()

                # Log results
                v1 = result.get('v1', {})
                v2 = result.get('v2', {})

                logger.info(
                    f"Legacy sync complete: "
                    f"V1(imported={v1.get('imported', 0)}, exported={v1.get('exported', 0)}) "
                    f"V2(imported={v2.get('imported', 0)}, exported={v2.get('exported', 0)})"
                )

            except Exception as e:
                logger.error(f"Error in legacy sync loop: {e}", exc_info=True)

            # Wait for next cycle
            await asyncio.sleep(self.interval)

    @property
    def is_running(self) -> bool:
        """Check if loop is running."""
        return self._running


# Global instance
legacy_loop = LegacyBackgroundLoop()