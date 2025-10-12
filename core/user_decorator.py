# jetup/core/user_decorator.py
"""
User decorator and middleware for automatically injecting user objects.
Simplified from helpbot - single database, no staff/operator logic.
"""
import logging
import functools
from typing import Callable, Any
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
from sqlalchemy.orm import Session

from core.db import get_session
from models.user import User

logger = logging.getLogger(__name__)


class UserMiddleware(BaseMiddleware):
    """
    Middleware for automatically getting user objects and injecting them into handlers.
    Also injects bot and message_manager from DI.

    NOTE: This middleware does NOT create users automatically.
    User creation is handled by handlers (e.g., /start with referral support).
    If user doesn't exist, user will be None in handler data.
    """

    def __init__(self, bot=None):
        """
        Initialize middleware.

        Args:
            bot: Bot instance (optional, for backwards compatibility)
        """
        self.bot = bot
        super().__init__()

    async def __call__(
            self,
            handler: Callable[[TelegramObject, dict[str, Any]], Any],
            event: TelegramObject,
            data: dict[str, Any]
    ) -> Any:
        """Process event and inject user data."""
        from core.di import get_service
        from core.message_manager import MessageManager

        # Get telegram user
        telegram_user = None
        if isinstance(event, (Message, CallbackQuery)):
            telegram_user = event.from_user

        if not telegram_user:
            logger.warning("No telegram user found in event")
            return await handler(event, data)

        # Get database session
        session = get_session()

        try:
            # Try to get existing user (DO NOT create)
            user = session.query(User).filter_by(telegramID=telegram_user.id).first()

            if not user:
                logger.debug(f"User {telegram_user.id} not found in database (will be created by handler if needed)")

            # Inject user and session
            data['user'] = user
            data['session'] = session

            # Inject bot (from __init__ or data)
            if self.bot:
                data['bot'] = self.bot

            # Inject message_manager from DI
            message_manager = get_service(MessageManager)
            if message_manager:
                data['message_manager'] = message_manager

            # Call handler
            result = await handler(event, data)

            # Commit session
            session.commit()

            return result

        except Exception as e:
            logger.error(f"Error in UserMiddleware: {e}", exc_info=True)
            session.rollback()
            raise
        finally:
            session.close()


def with_user(func: Callable = None):
    """
    Decorator for handlers that need user object.

    Backward compatibility with old code that expects user as first positional arg.

    Usage:
        @router.message(Command("start"))
        @with_user
        async def cmd_start(user: User, message: Message, session: Session):
            await message.answer(f"Hello {user.firstname}!")

    Or without decorator (new style):
        @router.message(Command("start"))
        async def cmd_start(message: Message, user: User, session: Session):
            await message.answer(f"Hello {user.firstname}!")
    """

    def decorator(handler_func: Callable) -> Callable:
        @functools.wraps(handler_func)
        async def wrapper(*args, **kwargs):
            # User is already injected by middleware
            return await handler_func(*args, **kwargs)

        return wrapper

    if func is None:
        return decorator
    return decorator(func)