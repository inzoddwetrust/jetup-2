# jetup/services/user_domain/auth_service.py
"""
Authentication and authorization service.
Handles user registration, EULA acceptance, and channel subscription checks.
"""
import logging
from datetime import datetime, timezone
from typing import Tuple, List, Dict, Any, Optional
from aiogram import Bot
from aiogram.types import User as TelegramUser
from sqlalchemy.orm import Session

from models.user import User
from config import Config

logger = logging.getLogger(__name__)


class AuthService:
    """
    Service for user authentication and authorization.

    Responsibilities:
    - User registration (with referral support)
    - EULA acceptance tracking
    - Channel subscription verification
    """

    def __init__(self, session: Session):
        """
        Initialize auth service.

        Args:
            session: SQLAlchemy database session
        """
        self.session = session

    async def register_user(
            self,
            telegram_user: TelegramUser,
            referrer_id: Optional[int] = None
    ) -> Tuple[User, bool]:
        """
        Register new user or return existing one.
        All logic is in User.create_from_telegram_data().

        Args:
            telegram_user: Telegram user object from message/callback
            referrer_id: Telegram ID of referrer (from /start REFERRER_ID)

        Returns:
            Tuple[User, bool]: (user object, is_new_user)

        Raises:
            ValueError: If DEFAULT_REFERRER_ID not configured and no referrer provided
        """
        # Check if user already exists
        existing_user = self.session.query(User).filter_by(telegramID=telegram_user.id).first()
        is_new = existing_user is None

        # Create or get user (all logic in model)
        user = User.create_from_telegram_data(self.session, telegram_user, referrer_id=referrer_id)

        if is_new:
            logger.info(
                f"New user registered: userID={user.userID}, telegramID={user.telegramID}, upline={user.upline}")

        return user, is_new

    def accept_eula(self, user: User, eula_version: str = "1.0") -> None:
        """
        Mark EULA as accepted for user.
        Updates user.personalData with EULA acceptance info and commits.

        Args:
            user: User object
            eula_version: Version of EULA accepted (default: "1.0")
        """
        if not user.personalData:
            user.personalData = {}

        user.personalData['eulaAccepted'] = True
        user.personalData['eulaVersion'] = eula_version
        user.personalData['eulaAcceptedAt'] = datetime.now(timezone.utc).isoformat()

        self.session.commit()
        logger.info(f"EULA accepted for user {user.userID} (version {eula_version})")

    def check_eula_accepted(self, user: User) -> bool:
        """
        Check if user has accepted EULA.

        Args:
            user: User object

        Returns:
            bool: True if EULA accepted, False otherwise
        """
        if not user.personalData:
            return False

        return user.personalData.get('eulaAccepted', False)

    async def check_channel_subscriptions(
            self,
            bot: Bot,
            user: User
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """
        Check if user is subscribed to required channels.
        Checks channels for user's language, falls back to English if needed.

        Args:
            bot: Bot instance for API calls
            user: User object

        Returns:
            Tuple[bool, List[Dict]]: (all_subscribed, not_subscribed_channels)
        """
        # Get required channels from config
        required_channels = Config.get(Config.REQUIRED_CHANNELS)

        if not required_channels:
            logger.debug("No required channels configured, skipping subscription check")
            return True, []

        user_lang = user.lang or 'en'

        # Filter channels by user's language
        lang_channels = [c for c in required_channels if c.get("lang") == user_lang]

        # Fallback to English if no channels for user's language
        if not lang_channels:
            logger.debug(f"No channels found for language '{user_lang}', using English channels")
            lang_channels = [c for c in required_channels if c.get("lang") == "en"]

        if not lang_channels:
            logger.warning("No channels found even after fallback to English")
            return True, []

        logger.debug(f"Checking {len(lang_channels)} channels for user {user.telegramID}")

        not_subscribed = []

        # Check each channel
        for channel in lang_channels:
            try:
                chat_id = channel.get("chat_id")
                if not chat_id:
                    logger.warning(f"Channel missing chat_id: {channel}")
                    continue

                # Get user's membership status
                member = await bot.get_chat_member(chat_id=chat_id, user_id=user.telegramID)

                # Check if user is subscribed (not left, kicked, or restricted)
                if member.status in ['left', 'kicked', 'restricted']:
                    not_subscribed.append(channel)
                    logger.debug(f"User {user.telegramID} not subscribed to {chat_id} (status: {member.status})")
                else:
                    logger.debug(f"User {user.telegramID} subscribed to {chat_id} (status: {member.status})")

            except Exception as e:
                # Log error but don't block user if channel check fails
                logger.error(f"Error checking subscription for {channel.get('chat_id')}: {e}")
                # Don't add to not_subscribed - assume subscribed on error

        all_subscribed = len(not_subscribed) == 0

        if all_subscribed:
            logger.info(f"User {user.telegramID} subscribed to all required channels")
        else:
            logger.info(f"User {user.telegramID} missing {len(not_subscribed)} channel subscriptions")

        return all_subscribed, not_subscribed