# jetup/background/notification_processor.py
"""
Notification processor service.
Processes pending notifications and sends them to users.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from sqlalchemy import and_
from contextlib import asynccontextmanager
from typing import Optional

from models import Notification, NotificationDelivery, User
from core.db import get_db_session_ctx
from core.utils import SafeDict
from config import Config
from aiogram import Bot, types

logger = logging.getLogger(__name__)


class NotificationProcessor:
    """
    Service for processing and delivering notifications.

    Features:
    - Automatic delivery creation for new notifications
    - Retry logic for failed deliveries (up to 3 attempts)
    - Support for user/all/filter targeting
    - Keyboard button formatting with variables
    - Auto-deletion after delay
    - Silent notifications
    """

    def __init__(self, polling_interval: int = 10):
        """
        Initialize notification processor.

        Args:
            polling_interval: Interval in seconds to check for new notifications (default: 10)
        """
        self.polling_interval = polling_interval
        self._running = False
        self._bot = None

    @staticmethod
    def _sequence_format(template: str, variables: dict, sequence_index: int = 0) -> str:
        """
        Format string with variables, supporting both scalar and sequence values.
        For sequence values, uses value at sequence_index or last value if index out of range.

        Args:
            template: Template string with {variable} placeholders
            variables: Dictionary of variable values (can be lists/tuples)
            sequence_index: Index for sequence values

        Returns:
            Formatted string
        """
        formatted_vars = {}

        for key, value in variables.items():
            if isinstance(value, (list, tuple)):
                try:
                    formatted_vars[key] = value[min(sequence_index, len(value) - 1)]
                except (IndexError, ValueError):
                    continue
            else:
                formatted_vars[key] = value

        return template.format_map(SafeDict(formatted_vars))

    @staticmethod
    def _create_keyboard(buttons_str: str, variables: dict = None) -> Optional[types.InlineKeyboardMarkup]:
        """
        Create keyboard from configuration string with variable support.

        Supported formats:
        - Legacy: [button1:Text1; button2:Text2],[button3:Text3]
        - New with ||: button1:Text1; button2:Text2 || button3:Text3
        - New with newlines: button1:Text1; button2:Text2\nbutton3:Text3

        Button format:
        - Regular callback: callback_data:Button Text
        - URL button: |url|example.com:Button Text

        Args:
            buttons_str: String with button configuration
            variables: Variables for formatting button text/callbacks

        Returns:
            InlineKeyboardMarkup or None
        """
        if not buttons_str or not buttons_str.strip():
            return None

        try:
            keyboard = types.InlineKeyboardMarkup(inline_keyboard=[])

            # Remove outer brackets if present
            cleaned_buttons = buttons_str.strip('[]')

            # Determine format and split rows
            if '||' in cleaned_buttons:
                rows = cleaned_buttons.split('||')
            elif '\n' in cleaned_buttons:
                rows = cleaned_buttons.split('\n')
            else:
                # Legacy format
                rows = cleaned_buttons.split('],[')

            sequence_index = 0

            for row in rows:
                if not row.strip():
                    continue

                row = row.strip().strip('[]')
                button_row = []
                buttons = row.split(';')

                for button in buttons:
                    button = button.strip()
                    if not button or ':' not in button:
                        continue

                    callback, text = button.split(':', 1)
                    callback, text = callback.strip(), text.strip()

                    # Format with variables
                    if variables:
                        try:
                            if not callback.startswith('|url|'):
                                callback = NotificationProcessor._sequence_format(
                                    callback, variables, sequence_index
                                )
                            text = NotificationProcessor._sequence_format(
                                text, variables, sequence_index
                            )
                            sequence_index += 1
                        except Exception as e:
                            logger.error(f"Error formatting button: {e}")
                            continue

                    # Create button
                    if callback.startswith('|url|'):
                        url = 'https://' + callback[5:]
                        button_row.append(
                            types.InlineKeyboardButton(text=text, url=url)
                        )
                    else:
                        button_row.append(
                            types.InlineKeyboardButton(text=text, callback_data=callback)
                        )

                if button_row:
                    keyboard.inline_keyboard.append(button_row)

            return keyboard if keyboard.inline_keyboard else None

        except Exception as e:
            logger.error(f"Error creating keyboard: {e}", exc_info=True)
            return None

    @asynccontextmanager
    async def get_bot(self):
        """
        Context manager for safe bot usage.
        Creates bot instance if needed, reuses existing one.
        """
        if self._bot is None:
            api_token = Config.get(Config.API_TOKEN)
            self._bot = Bot(token=api_token)
        try:
            yield self._bot
        finally:
            # Close only when service is stopping
            if not self._running and self._bot:
                await self._bot.session.close()
                self._bot = None

    async def process_filter(self, filter_json: str) -> list[int]:
        """
        Process JSON filter conditions to get list of user IDs.

        Args:
            filter_json: JSON string with filter conditions

        Returns:
            List of user IDs matching filter
        """
        # TODO: Implement query building from filter conditions
        conditions = json.loads(filter_json)
        with get_db_session_ctx() as session:
            query = session.query(User.userID)
            # Build query based on conditions
            return []

    async def create_deliveries(self, notification: Notification) -> None:
        """
        Create delivery records for a notification based on target type.

        Args:
            notification: Notification object to create deliveries for
        """
        with get_db_session_ctx() as session:
            if notification.targetType == "user":
                delivery = NotificationDelivery(
                    notificationID=notification.notificationID,
                    userID=int(notification.targetValue)
                )
                session.add(delivery)

            elif notification.targetType == "all":
                users = session.query(User.userID).all()
                deliveries = [
                    NotificationDelivery(
                        notificationID=notification.notificationID,
                        userID=user.userID
                    ) for user in users
                ]
                session.bulk_save_objects(deliveries)

            elif notification.targetType == "filter":
                user_ids = await self.process_filter(notification.targetValue)
                deliveries = [
                    NotificationDelivery(
                        notificationID=notification.notificationID,
                        userID=user_id
                    ) for user_id in user_ids
                ]
                session.bulk_save_objects(deliveries)

    async def send_notification(self, delivery: NotificationDelivery) -> bool:
        """
        Send a single notification to user.

        Args:
            delivery: NotificationDelivery object

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            with get_db_session_ctx() as session:
                # Get delivery in THIS session (not merge from another session!)
                delivery = session.query(NotificationDelivery).filter_by(
                    deliveryID=delivery.deliveryID
                ).first()

                if not delivery:
                    logger.error(f"Delivery not found: {delivery.deliveryID}")
                    return False

                # Get user
                user = session.query(User).filter_by(userID=delivery.userID).first()

                if not user or not user.telegramID:
                    logger.warning(f"User {delivery.userID} not found or has no telegram ID")
                    delivery.status = "error"
                    delivery.errorMessage = "User not found or no telegram ID"
                    return False

                # Get notification (via relationship)
                notification = delivery.notification

                # Check expiry
                if notification.expiryAt and notification.expiryAt < datetime.now(timezone.utc):
                    delivery.status = "expired"
                    logger.info(f"Notification {notification.notificationID} expired")
                    return False

                # Create keyboard if buttons exist
                keyboard = None
                if notification.buttons:
                    variables = {
                        'user_id': user.userID,
                        'telegram_id': user.telegramID,
                    }
                    keyboard = NotificationProcessor._create_keyboard(notification.buttons, variables)

                # Send message via bot
                async with self.get_bot() as bot:
                    message = await bot.send_message(
                        chat_id=user.telegramID,
                        text=notification.text,
                        parse_mode=notification.parseMode,
                        reply_markup=keyboard,
                        disable_web_page_preview=notification.disablePreview,
                        disable_notification=notification.silent
                    )

                    # Schedule auto-deletion if needed
                    if notification.autoDelete:
                        asyncio.create_task(self._schedule_deletion(
                            user.telegramID,
                            message.message_id,
                            notification.autoDelete
                        ))

                # Update delivery status
                delivery.status = "sent"
                delivery.sentAt = datetime.now(timezone.utc)

                # Update user last active
                user.lastActive = datetime.now(timezone.utc)

                logger.info(f"Notification {notification.notificationID} sent to user {user.userID}")
                return True

        except Exception as e:
            logger.error(f"Error sending notification to delivery {delivery.deliveryID}: {e}", exc_info=True)

            # Try to update error status
            try:
                with get_db_session_ctx() as session:
                    delivery = session.query(NotificationDelivery).filter_by(
                        deliveryID=delivery.deliveryID
                    ).first()
                    if delivery:
                        delivery.errorMessage = str(e)[:500]  # Limit error message length
            except:
                pass

            return False

    async def _schedule_deletion(self, chat_id: int, message_id: int, delay: int):
        """
        Schedule message deletion after delay.

        Args:
            chat_id: Telegram chat ID
            message_id: Message ID to delete
            delay: Delay in seconds
        """
        await asyncio.sleep(delay)
        try:
            async with self.get_bot() as bot:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception as e:
            logger.error(f"Error deleting message {message_id}: {e}")

    async def process_pending_deliveries(self) -> None:
        """
        Process pending notification deliveries.
        Sends notifications and updates delivery status.
        """
        with get_db_session_ctx() as session:
            # Get pending deliveries (up to 3 attempts)
            pending_deliveries = (
                session.query(NotificationDelivery)
                .join(Notification)
                .filter(and_(
                    NotificationDelivery.status == "pending",
                    NotificationDelivery.attempts < 3
                ))
                .order_by(Notification.priority.desc())
                .limit(50)
                .all()
            )

            for delivery in pending_deliveries:
                success = await self.send_notification(delivery)

                delivery.attempts += 1
                if success:
                    delivery.status = "sent"
                    delivery.sentAt = datetime.now(timezone.utc)
                elif delivery.attempts >= 3:
                    delivery.status = "error"

    async def process_new_notifications(self) -> None:
        """
        Find notifications without deliveries and create them.
        """
        with get_db_session_ctx() as session:
            # Find notifications without any deliveries
            new_notifications = (
                session.query(Notification)
                .outerjoin(NotificationDelivery)
                .filter(NotificationDelivery.deliveryID == None)
                .all()
            )

            for notification in new_notifications:
                try:
                    await self.create_deliveries(notification)
                except Exception as e:
                    logger.error(f"Error processing notification {notification.notificationID}: {e}")

    async def run(self) -> None:
        """
        Main processing loop.
        Runs continuously checking for new notifications and sending pending ones.
        """
        logger.info("Starting notification processor")
        self._running = True

        try:
            while self._running:
                try:
                    await self.process_new_notifications()
                    await self.process_pending_deliveries()
                except Exception as e:
                    logger.error(f"Error in notification processor: {e}")

                await asyncio.sleep(self.polling_interval)
        finally:
            self._running = False
            if self._bot:
                await self._bot.session.close()
                self._bot = None
            logger.info("Notification processor stopped")

    async def stop(self):
        """Stop the processor gracefully."""
        self._running = False
        await asyncio.sleep(0)