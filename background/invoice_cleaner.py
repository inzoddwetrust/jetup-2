# jetup-2/background/invoice_cleaner.py
"""
Invoice cleaner - removes old pending invoices.
Sends warnings before expiration and marks expired invoices.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from models.payment import Payment
from models.notification import Notification
from core.db import get_session
from core.templates import MessageTemplates
from config import Config

logger = logging.getLogger(__name__)


class InvoiceCleaner:
    """
    Background service to clean up old pending invoices.

    Timeline:
    - 1:30 after creation: first warning (30 min remaining)
    - 1:50 after creation: second warning (10 min remaining)
    - 2:00 after creation: mark as expired
    """

    def __init__(self, check_interval: int = 300):
        """
        Initialize invoice cleaner.

        Args:
            check_interval: Check interval in seconds (default: 300 = 5 min)
        """
        self.check_interval = check_interval
        self._running = False

    def format_remaining_time(self, remaining: timedelta) -> str:
        """Format remaining time in minutes."""
        return str(int(remaining.total_seconds() / 60))

    async def expire_invoice(self, session, invoice: Payment):
        """Mark invoice as expired and send notification."""
        try:
            invoice.status = "expired"

            text, buttons = await MessageTemplates.get_raw_template(
                'invoice_expired',
                {
                    'amount': invoice.amount,
                    'method': invoice.method
                }
            )

            notification = Notification(
                source="invoice_cleaner",
                text=text,
                targetType="user",
                targetValue=str(invoice.userID),
                priority=2,
                category="payment",
                importance="high",
                parseMode="HTML",
                buttons=buttons
            )

            session.add(notification)
            session.commit()
            logger.info(f"Invoice {invoice.paymentID} marked as expired")

        except Exception as e:
            logger.error(f"Error expiring invoice {invoice.paymentID}: {e}")
            session.rollback()

    async def send_warning(self, session, invoice: Payment, remaining: timedelta):
        """Send warning notification about upcoming expiration."""
        try:
            bot_username = Config.get(Config.BOT_USERNAME) or 'jetup_bot'

            text, buttons = await MessageTemplates.get_raw_template(
                'invoice_warning',
                {
                    'amount': invoice.amount,
                    'method': invoice.method,
                    'payment_id': invoice.paymentID,
                    'bot_username': bot_username,
                    'remaining_time': self.format_remaining_time(remaining)
                }
            )

            notification = Notification(
                source="invoice_cleaner",
                text=text,
                targetType="user",
                targetValue=str(invoice.userID),
                priority=2,
                category="payment",
                importance="high",
                parseMode="HTML",
                buttons=buttons
            )

            session.add(notification)
            session.commit()

            remaining_minutes = int(remaining.total_seconds() / 60)
            logger.info(f"Warning sent for invoice {invoice.paymentID}, {remaining_minutes} minutes remaining")

        except Exception as e:
            logger.error(f"Error sending warning for invoice {invoice.paymentID}: {e}")
            session.rollback()

    async def cleanup_old_invoices(self):
        """Clean up old pending invoices on startup."""
        with get_session() as session:
            try:
                # Mark invoices older than 3 hours as expired
                three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=3)
                old_invoices = (
                    session.query(Payment)
                    .filter(
                        Payment.status == "pending",
                        Payment.createdAt < three_hours_ago
                    )
                    .all()
                )

                for invoice in old_invoices:
                    invoice.status = "expired"
                    logger.info(f"Old invoice {invoice.paymentID} marked as expired on startup")

                if old_invoices:
                    session.commit()
                    logger.info(f"Cleaned up {len(old_invoices)} old pending invoices")

            except Exception as e:
                logger.error(f"Error cleaning up old invoices: {e}")
                session.rollback()

    async def process_pending_invoices(self):
        """Process pending invoices - send warnings and expire old ones."""
        with get_session() as session:
            try:
                # Get pending payments not older than 3 hours
                three_hours_ago = datetime.now(timezone.utc) - timedelta(hours=3)
                pending_invoices = (
                    session.query(Payment)
                    .filter(
                        Payment.status == "pending",
                        Payment.createdAt >= three_hours_ago
                    )
                    .all()
                )

                for invoice in pending_invoices:
                    # Ensure timezone awareness
                    if invoice.createdAt.tzinfo is None:
                        created_at = invoice.createdAt.replace(tzinfo=timezone.utc)
                    else:
                        created_at = invoice.createdAt

                    age = datetime.now(timezone.utc) - created_at

                    # Count existing notifications for this invoice
                    existing_notifications = (
                        session.query(Notification)
                        .filter(
                            Notification.source == "invoice_cleaner",
                            Notification.target_value == str(invoice.userID),
                            Notification.text.like(f"%{invoice.paymentID}%")
                        ).count()
                    )

                    # After 2 hours - mark as expired
                    if age >= timedelta(hours=2):
                        if invoice.status == "pending":
                            await self.expire_invoice(session, invoice)

                    # 10 minutes before expiration (1:50) - second warning
                    elif age >= timedelta(hours=1, minutes=50) and existing_notifications < 2:
                        remaining = timedelta(hours=2) - age
                        await self.send_warning(session, invoice, remaining)

                    # 30 minutes before expiration (1:30) - first warning
                    elif age >= timedelta(hours=1, minutes=30) and existing_notifications < 1:
                        remaining = timedelta(hours=2) - age
                        await self.send_warning(session, invoice, remaining)

            except Exception as e:
                logger.error(f"Error processing pending invoices: {e}")
                session.rollback()

    async def run(self):
        """Start invoice cleaner background task."""
        logger.info("Invoice cleaner started")

        # Clean up old invoices on startup
        await self.cleanup_old_invoices()

        self._running = True

        while self._running:
            try:
                await self.process_pending_invoices()
                await asyncio.sleep(self.check_interval)
            except Exception as e:
                logger.error(f"Error in invoice cleaner main loop: {e}")
                await asyncio.sleep(self.check_interval)

    async def stop(self):
        """Stop invoice cleaner."""
        self._running = False
        logger.info("Invoice cleaner stopped")