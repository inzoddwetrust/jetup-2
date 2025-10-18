# jetup/background/transfer_bonus_processor.py
"""
Transfer Bonus Processor - processes pending transfer bonuses.
Separate from MLM system to avoid conflicts.
"""
import asyncio
import logging
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import and_

from models import Bonus, User
from models.active_balance import ActiveBalance
from core.db import get_db_session_ctx

logger = logging.getLogger(__name__)


class TransferBonusProcessor:
    """
    Processor for transfer bonuses only.
    Does NOT interfere with MLM system bonuses.
    """

    def __init__(self, polling_interval: int = 10):
        """
        Initialize transfer bonus processor.

        Args:
            polling_interval: Interval in seconds to check for pending bonuses (default: 10)
        """
        self.polling_interval = polling_interval
        self._running = False
        self.stats = {
            "processed": 0,
            "errors": 0,
            "totalAmount": Decimal("0")
        }

    async def process_pending_bonuses(self) -> None:
        """
        Process all pending transfer bonuses.
        Only processes bonuses with commissionType='transfer_bonus'.
        """
        with get_db_session_ctx() as session:
            # Get ONLY transfer bonuses with pending status
            pending_bonuses = (
                session.query(Bonus)
                .filter(and_(
                    Bonus.status == "pending",
                    Bonus.commissionType == "transfer_bonus"
                ))
                .limit(50)  # Process in batches
                .all()
            )

            if not pending_bonuses:
                return

            logger.info(f"Found {len(pending_bonuses)} pending transfer bonuses to process")

            processed = 0
            errors = 0

            for bonus in pending_bonuses:
                try:
                    # Get user
                    user = session.query(User).filter_by(userID=bonus.userID).first()

                    if not user:
                        logger.error(f"User {bonus.userID} not found for bonus {bonus.bonusID}")
                        bonus.status = "error"
                        bonus.notes = (bonus.notes or "") + " | User not found"
                        errors += 1
                        continue

                    # Add bonus to ACTIVE balance (not passive - this is transfer bonus!)
                    user.balanceActive = (user.balanceActive or Decimal("0")) + bonus.bonusAmount

                    # Create ActiveBalance transaction record
                    active_record = ActiveBalance(
                        userID=user.userID,
                        firstname=user.firstname,
                        surname=user.surname,
                        amount=bonus.bonusAmount,
                        status='done',
                        reason=f'bonus={bonus.bonusID}',
                        notes=f'Transfer bonus ({bonus.bonusRate * 100:.0f}%)'
                    )
                    session.add(active_record)

                    # Mark bonus as paid
                    bonus.status = "paid"

                    # Update stats
                    processed += 1
                    self.stats["processed"] += 1
                    self.stats["totalAmount"] += bonus.bonusAmount

                    logger.info(
                        f"Processed transfer bonus {bonus.bonusID}: "
                        f"+{bonus.bonusAmount} to user {user.userID}"
                    )

                except Exception as e:
                    logger.error(
                        f"Error processing bonus {bonus.bonusID}: {e}",
                        exc_info=True
                    )
                    bonus.status = "error"
                    bonus.notes = (bonus.notes or "") + f" | Error: {str(e)[:200]}"
                    errors += 1
                    self.stats["errors"] += 1

            logger.info(
                f"Transfer bonus processing complete: "
                f"processed={processed}, errors={errors}"
            )

    async def run(self) -> None:
        """
        Main processing loop.
        Runs continuously checking for pending transfer bonuses.
        """
        logger.info("Starting Transfer Bonus Processor")
        self._running = True

        try:
            while self._running:
                try:
                    await self.process_pending_bonuses()
                except Exception as e:
                    logger.error(f"Error in transfer bonus processor: {e}")

                await asyncio.sleep(self.polling_interval)
        finally:
            self._running = False
            logger.info("Transfer Bonus Processor stopped")

    async def stop(self):
        """Stop the processor gracefully."""
        self._running = False
        await asyncio.sleep(0)

    def get_stats(self) -> dict:
        """Get processor statistics."""
        return {
            "running": self._running,
            "processed": self.stats["processed"],
            "errors": self.stats["errors"],
            "totalAmount": float(self.stats["totalAmount"])
        }