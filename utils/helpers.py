from typing import Tuple
from models import User
import logging
from aiogram.types import Message, CallbackQuery
from config import REQUIRED_CHANNELS
from datetime import datetime, timezone

from decimal import Decimal
from typing import Optional, Union

def safe_float(value: Union[Decimal, float, int, str, None]) -> float:
    """Safely convert any value to float, handling Decimal, None, and other types."""
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0

def safe_decimal(value: Union[Decimal, float, int, str, None]) -> Decimal:
    """Safely convert any value to Decimal."""
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError):
        return Decimal("0")

async def safe_delete_message(message_or_callback: Union[Message, CallbackQuery]) -> None:
    """
    Безопасно удаляет сообщение из чата.
    Работает как с Message, так и с CallbackQuery.

    Args:
        message_or_callback: Message или CallbackQuery объект
    """
    try:
        message = message_or_callback.message if isinstance(message_or_callback, CallbackQuery) else message_or_callback

        await message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id
        )
    except Exception as e:
        logging.warning(f"Failed to delete message: {e}")


async def get_user_from_update(update: Union[Message, CallbackQuery], session) -> Tuple[Optional[User], bool]:
    """
    Получает объект пользователя из базы данных.

    Args:
        update: Message или CallbackQuery объект
        session: SQLAlchemy session

    Returns:
        Tuple[Optional[User], bool]: (user, success)
        - user: объект пользователя или None
        - success: True если пользователь найден
    """
    telegram_id = update.from_user.id
    user = session.query(User).filter_by(telegramID=telegram_id).first()

    if not user:
        # Пользователь не найден, но не отправляем сообщение
        # Это нормальная ситуация для новых пользователей, использующих /start
        # Сообщение будет отправлено, только если это не обработчик /start
        is_start_command = (isinstance(update, Message) and
                            update.text and
                            update.text.startswith('/start'))

        if not is_start_command:
            if isinstance(update, CallbackQuery):
                await update.message.answer("User not found")
            else:
                await update.answer("User not found")

        return None, False

    return user, True


async def check_user_subscriptions(bot, user_id: int, user_lang: str = "en") -> tuple:
    """
    Проверяет подписку пользователя на каналы из config.REQUIRED_CHANNELS с учетом языка

    Args:
        bot: экземпляр бота
        user_id: ID пользователя в Telegram
        user_lang: язык пользователя

    Returns:
        tuple: (все_подписки_есть, список_непройденных_каналов_с_учетом_языка)
    """
    not_subscribed = []

    # Определяем каналы для проверки
    lang_channels = [c for c in REQUIRED_CHANNELS if c.get("lang") == user_lang]

    # Если нет каналов на языке пользователя, используем английские
    if not lang_channels:
        lang_channels = [c for c in REQUIRED_CHANNELS if c.get("lang") == "en"]

    # Проверяем подписки
    for channel in lang_channels:
        try:
            chat_id = channel["chat_id"]
            member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)

            # Проверяем статус пользователя
            if member.status in ['left', 'kicked', 'restricted']:
                not_subscribed.append(channel)

        except Exception as e:
            # Логируем ошибку, но не добавляем канал в список обязательных
            logging.error(f"Error checking subscription for {channel['chat_id']}: {e}")

    return len(not_subscribed) == 0, not_subscribed


def is_email_confirmed(user: User) -> bool:
    """
    Check if user's email is confirmed.

    Args:
        user: User object

    Returns:
        bool: True if email is confirmed, False otherwise
    """
    if not user.emailVerification:
        return False
    return user.emailVerification.get('confirmed', False)


def set_email_last_sent(user: User, timestamp: datetime) -> None:
    """Set timestamp of last email sent"""
    if not user.emailVerification:
        user.emailVerification = {}
    user.emailVerification['sentAt'] = timestamp.isoformat()
    user.emailVerification['attempts'] = user.emailVerification.get('attempts', 0) + 1

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, 'emailVerification')


def get_email_last_sent(user: User) -> Optional[datetime]:
    """Get timestamp of last email sent"""
    if not user.emailVerification:
        return None

    sent_at = user.emailVerification.get('sentAt')
    if not sent_at:
        return None

    try:
        # Парсим ISO формат даты (должен включать timezone info)
        parsed_date = datetime.fromisoformat(sent_at)
        # Если дата без timezone, добавляем UTC
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        return parsed_date
    except (ValueError, TypeError):
        return None


def can_resend_email(user: User, cooldown_minutes: int = 5) -> Tuple[bool, Optional[int]]:
    """
    Check if user can resend email (cooldown check)

    Returns:
        Tuple[bool, Optional[int]]: (can_send, remaining_seconds)
    """
    last_sent = get_email_last_sent(user)
    if not last_sent:
        return True, None

    now = datetime.now(timezone.utc)  # ИСПРАВЛЕНО
    elapsed = now - last_sent
    cooldown_seconds = cooldown_minutes * 60

    if elapsed.total_seconds() >= cooldown_seconds:
        return True, None

    remaining = cooldown_seconds - int(elapsed.total_seconds())
    return False, remaining


class FakeMessage:
    def __init__(self, from_user, chat, reply_to_message=None, bot=None, args=None):
        self.from_user = from_user
        self.chat = chat
        self.reply_to_message = reply_to_message
        self.bot = bot
        self._args = args or ''
        self.text = None

    async def answer(self, text, **kwargs):
        """Эмулирует message.answer(), проксируя вызов к bot.send_message"""
        return await self.bot.send_message(
            chat_id=self.chat.id,
            text=text,
            **kwargs
        )

    async def reply(self, text, **kwargs):
        """Эмулирует message.reply()"""
        return await self.bot.send_message(
            chat_id=self.chat.id,
            reply_to_message_id=None,  # Не отвечаем ни на какое сообщение
            text=text,
            **kwargs
        )

    def get_args(self) -> str:
        """
        Эмулирует message.get_args()
        Возвращает аргументы команды
        """
        return self._args

    def safe_get_json_value(json_field, *keys, default=None):
        """Безопасное получение значения из вложенного JSON"""
        if not json_field:
            return default

        value = json_field
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
                if value is None:
                    return default
            else:
                return default
        return value

    def safe_set_json_value(obj, field_name, value, *keys):
        """Безопасная установка значения во вложенный JSON"""
        # Получаем JSON поле
        json_field = getattr(obj, field_name)
        if not json_field:
            json_field = {}
            setattr(obj, field_name, json_field)

        # Навигация до нужного уровня
        current = json_field
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]

        # Установка значения
        if keys:
            current[keys[-1]] = value

        # Обязательно помечаем SQLAlchemy что поле изменилось
        from sqlalchemy.orm.attributes import flag_modified
        flag_modified(obj, field_name)

    # Использование:
    # safe_set_json_value(user, 'personalData', True, 'dataFilled')
    # safe_set_json_value(user, 'personalData', 'verified', 'kyc', 'status')