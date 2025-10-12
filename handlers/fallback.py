# jetup/handlers/fallback.py
"""
Fallback handler for unhandled callbacks.
Must be registered LAST in handler registration order.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from models.user import User
from core.message_manager import MessageManager
from core.user_decorator import with_user

logger = logging.getLogger(__name__)

fallback_router = Router(name="fallback_router")


@fallback_router.callback_query()
@with_user
async def handle_unknown_callback(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager,
        state: FSMContext
):
    """
    Fallback handler for any unhandled callback queries.
    Logs warning and shows temporary message.
    """
    logger.warning(
        f"Unhandled callback from user {user.telegramID}: "
        f"data='{callback_query.data}', "
        f"state={await state.get_state()}"
    )

    await message_manager.send_template(
        user=user,
        template_key='/fallback',
        update=callback_query,
        variables={'callback_data': callback_query.data}
    )

    await callback_query.answer("TEMPORARY DISABLED!", show_alert=False)