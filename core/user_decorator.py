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
    """

    async def __call__(
            self,
            handler: Callable[[TelegramObject, dict[str, Any]], Any],
            event: TelegramObject,
            data: dict[str, Any]
    ) -> Any:
        """Process event and inject user data."""

        # Get telegram user
        telegram_user = None
        if isinstance(event, (Message, CallbackQuery)):
            telegram_user = event.from_user

        if not telegram_user:
            logger.warning("No telegram user found in event")
            return await handler(event, data)

        # Get or create user in database
        session = get_session()
        try:
            user = User.get_or_create(session, telegram_user)

            # Inject into data
            data['user'] = user
            data['session'] = session

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

    def decorator(handler: Callable) -> Callable:
        @functools.wraps(handler)
        async def wrapper(*args, **kwargs):
            # Extract user and session from kwargs (injected by middleware)
            user = kwargs.get('user')
            session = kwargs.get('session')

            if not user:
                logger.error(f"User not found in handler {handler.__name__}")
                return None

            # Old style: user as first positional argument
            # Find Message or CallbackQuery in args
            message_or_callback = None
            for arg in args:
                if isinstance(arg, (Message, CallbackQuery)):
                    message_or_callback = arg
                    break

            if message_or_callback:
                # Call with user as first arg (old style)
                return await handler(user, message_or_callback, session=session, **kwargs)
            else:
                # Call normally (new style)
                return await handler(*args, user=user, session=session, **kwargs)

        return wrapper

    # Support both @with_user and @with_user()
    if func is None:
        return decorator
    else:
        return decorator(func)