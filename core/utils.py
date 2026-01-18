# jetup/core/utils.py
"""
Utility functions and classes for Jetup bot.
Hybrid version combining helpbot's clean architecture with talentir's advanced features.
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional, Union, Any
from aiogram.types import Message, CallbackQuery
from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# ADVANCED SAFEDICT - Critical for PostgreSQL Decimal handling
# ═══════════════════════════════════════════════════════════════════════════

class SafeDict(dict):
    """
    Advanced safe dictionary for template formatting.

    Features:
    - Handles missing keys gracefully (returns {key} instead of raising KeyError)
    - Automatic Decimal → float conversion for PostgreSQL compatibility
    - Format specifier support for numbers ({value:.2f}, {value:,d})
    - Null-safe formatting

    Examples:
        >>> sd = SafeDict({'price': Decimal('123.456'), 'qty': 5})
        >>> "{price:.2f}".format_map(sd)  # "123.46"
        >>> "{qty:,d}".format_map(sd)     # "5"
        >>> "{missing}".format_map(sd)    # "{missing}"
    """

    def __missing__(self, key):
        """Handle missing keys with format specifier support."""
        try:
            # Split key and format specifier
            if ':' in key:
                base_key = key.split(':', 1)[0]
                format_spec = key.split(':', 1)[1]
            else:
                base_key = key
                format_spec = None

            # Check if base key exists
            if base_key in self:
                value = self[base_key]

                # Convert Decimal to float for formatting
                if isinstance(value, Decimal):
                    value = float(value)

                # Apply format specifier if present
                if format_spec:
                    # Handle numeric format specifiers
                    if 'f' in format_spec or 'd' in format_spec or ',' in format_spec:
                        try:
                            if value is None:
                                value = 0
                            elif not isinstance(value, (int, float)):
                                value = float(value)
                        except (ValueError, TypeError):
                            value = 0
                    return format(value, format_spec)

                return value

            # Key not found - return default value based on format spec
            if format_spec:
                if 'f' in format_spec or ',' in format_spec:  # Float format
                    return format(0, format_spec)
                elif 'd' in format_spec:  # Integer format
                    return format(0, format_spec)

            # Return placeholder for missing key
            return '{' + base_key + '}'

        except Exception as e:
            logger.warning(f"Error formatting key '{key}': {e}")
            return '{' + key + '}'

    def __getitem__(self, key):
        """
        Get item with automatic Decimal handling.

        Overrides default __getitem__ to handle Decimal formatting properly.
        """
        try:
            value = super().__getitem__(key)

            # Handle Decimal with format specifier
            if isinstance(value, Decimal) and ':' in key:
                base_key = key.split(':')[0]
                if base_key == key:  # No formatting
                    return value
                # Has formatting - convert to float
                format_spec = key.split(':', 1)[1]
                return format(float(value), format_spec)

            return value

        except KeyError:
            # Key not found, use __missing__
            return self.__missing__(key)


# ═══════════════════════════════════════════════════════════════════════════
# DECIMAL & TYPE CONVERSION UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def safe_float(value: Union[Decimal, float, int, str, None]) -> float:
    """
    Safely convert any value to float, handling Decimal, None, and other types.

    Args:
        value: Value to convert (Decimal, float, int, str, or None)

    Returns:
        float: Converted value or 0.0 if conversion fails

    Examples:
        >>> safe_float(Decimal('123.45'))
        123.45
        >>> safe_float(None)
        0.0
        >>> safe_float("invalid")
        0.0
    """
    if value is None:
        return 0.0
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except (ValueError, TypeError, InvalidOperation):
        logger.warning(f"Failed to convert {value} to float, returning 0.0")
        return 0.0


def safe_decimal(value: Union[Decimal, float, int, str, None]) -> Decimal:
    """
    Safely convert any value to Decimal.

    Args:
        value: Value to convert

    Returns:
        Decimal: Converted value or Decimal("0") if conversion fails

    Examples:
        >>> safe_decimal(123.45)
        Decimal('123.45')
        >>> safe_decimal(None)
        Decimal('0')
    """
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        logger.warning(f"Failed to convert {value} to Decimal, returning 0")
        return Decimal("0")


def safe_int(value: Union[int, float, str, None]) -> int:
    """
    Safely convert value to integer.

    Args:
        value: Value to convert

    Returns:
        int: Converted value or 0 if conversion fails
    """
    if value is None:
        return 0
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.warning(f"Failed to convert {value} to int, returning 0")
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# MESSAGE UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

async def safe_delete_message(message_or_callback: Union[Message, CallbackQuery]) -> None:
    """
    Safely delete a message from chat.
    Works with both Message and CallbackQuery objects.

    Args:
        message_or_callback: Message or CallbackQuery object to delete
    """
    try:
        message = message_or_callback.message if isinstance(message_or_callback, CallbackQuery) else message_or_callback

        await message.bot.delete_message(
            chat_id=message.chat.id,
            message_id=message.message_id
        )
    except TelegramAPIError as e:
        logger.debug(f"Failed to delete message: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error deleting message: {e}")


class FakeCallbackQuery:
    """
    Fake CallbackQuery object for handling text input through callback processing flow.

    Used when we need to process text messages using the same flow as callbacks.
    Provides minimal compatibility interface with real CallbackQuery.

    """

    def __init__(self, message: Message, data: Optional[str] = None):
        """
        Initialize fake callback query from message.

        Args:
            message: Original message object
            data: Optional callback data to simulate
        """
        self.message = message
        self.from_user = message.from_user
        self.data = data
        self.id = str(message.message_id)  # Fake callback query ID
        self.chat = message.chat

    async def answer(self, text: Optional[str] = None, show_alert: bool = False, **kwargs):
        """Fake answer method that does nothing (no popup to show)."""
        pass

    @property
    def message_id(self) -> int:
        """Message ID for compatibility."""
        return self.message.message_id


# ═══════════════════════════════════════════════════════════════════════════
# USER NOTES UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def get_user_note(user, key: str) -> Optional[str]:
    if not user.notes:
        return None

    try:
        if isinstance(user.notes, dict):
            return user.notes.get(key)
        elif isinstance(user.notes, str):
            notes = dict(note.split(':') for note in user.notes.split() if ':' in note)
            return notes.get(key)
    except Exception as e:
        logger.warning(f"Error parsing user notes: {e}")
        return None


def set_user_note(user, key: str, value: str) -> None:
    notes = {}
    if user.notes:
        try:
            if isinstance(user.notes, dict):
                notes = user.notes
            elif isinstance(user.notes, str):
                notes = dict(note.split(':') for note in user.notes.split() if ':' in note)
        except Exception as e:
            logger.warning(f"Error parsing existing user notes: {e}")

    notes[key] = value

    # Keep same type as original
    if isinstance(user.notes, dict) or user.notes is None:
        user.notes = notes
    else:
        user.notes = ' '.join(f'{k}:{v}' for k, v in notes.items())

# ═══════════════════════════════════════════════════════════════════════════
# EMAIL NORMALIZATION
# ═══════════════════════════════════════════════════════════════════════════

def normalize_email(email: str) -> str:
    """
    Normalize email for comparison.

    - Lowercase
    - Strip whitespace
    - Gmail: remove dots and +tag from local part

    Gmail treats these as identical:
    - user@gmail.com
    - u.s.e.r@gmail.com
    - user+tag@gmail.com
    - u.s.e.r+anything@gmail.com

    Args:
        email: Raw email string

    Returns:
        Normalized email string, or empty string if invalid

    Examples:
        >>> normalize_email("User@Gmail.COM")
        'user@gmail.com'
        >>> normalize_email("u.s.e.r@gmail.com")
        'user@gmail.com'
        >>> normalize_email("user+tag@gmail.com")
        'user@gmail.com'
        >>> normalize_email("user@example.com")
        'user@example.com'
    """
    if not email:
        return ""

    email = str(email).lower().strip()

    if '@gmail.com' in email:
        local, domain = email.split('@', 1)
        # Remove +tag (user+tag@gmail.com → user@gmail.com)
        if '+' in local:
            local = local.split('+')[0]
        # Remove dots (u.s.e.r → user)
        local = local.replace('.', '')
        return f"{local}@{domain}"

    return email


# ═══════════════════════════════════════════════════════════════════════════
# DATA PARSING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════

def parse_date(value: Any, date_format: str = "%Y-%m-%d %H:%M:%S") -> Optional[datetime]:
    """
    Parse a date value from various formats.

    Args:
        value: Value to parse (string, datetime, or None)
        date_format: Format string for parsing

    Returns:
        datetime object or None if parsing fails

    Examples:
        >>> parse_date("2024-01-15 10:30:00")
        datetime.datetime(2024, 1, 15, 10, 30, 0)
        >>> parse_date(None)
        None
    """
    if value is None or value == '':
        return None

    if isinstance(value, datetime):
        return value

    if isinstance(value, str):
        # Try different formats
        formats = [
            date_format,
            "%Y-%m-%d",
            "%d.%m.%Y",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S.%f"
        ]

        for fmt in formats:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

    return None


def parse_bool(value: Any) -> bool:
    """
    Parse boolean value from various formats.

    Args:
        value: Value to parse (bool, int, str, or None)

    Returns:
        bool: Parsed boolean value

    Examples:
        >>> parse_bool("true")
        True
        >>> parse_bool(1)
        True
        >>> parse_bool("false")
        False
    """
    if isinstance(value, bool):
        return value
    elif isinstance(value, int):
        return value == 1
    elif isinstance(value, str):
        return value.upper() in ("TRUE", "1", "YES", "Y")
    return False


def parse_int(value: Any) -> Optional[int]:
    """
    Parse integer value safely.

    Args:
        value: Value to parse

    Returns:
        int or None if parsing fails
    """
    if value is None or value == '':
        return None

    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def parse_float(value: Any) -> Optional[float]:
    """
    Parse float value safely.

    Args:
        value: Value to parse

    Returns:
        float or None if parsing fails
    """
    if value is None or value == '':
        return None

    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def clean_str(value: Any) -> Optional[str]:
    """
    Clean and normalize string value.

    Args:
        value: Value to clean

    Returns:
        Cleaned string or None if empty
    """
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned if cleaned else None


# ═══════════════════════════════════════════════════════════════════════════
# JSON FIELD UTILITIES (for new models with JSON fields)
# ═══════════════════════════════════════════════════════════════════════════

def safe_get_json_value(json_field: Optional[dict], *keys, default=None):
    """
    Safely get value from nested JSON field.

    Args:
        json_field: JSON dictionary
        *keys: Path to value (e.g., 'kyc', 'status')
        default: Default value if not found

    Returns:
        Value or default if not found

    """
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


def safe_set_json_value(obj, field_name: str, value: Any, *keys):
    """
    Safely set value in nested JSON field.

    Args:
        obj: SQLAlchemy model instance
        field_name: Name of JSON field
        value: Value to set
        *keys: Path to value

    """
    from sqlalchemy.orm.attributes import flag_modified

    # Get JSON field
    json_field = getattr(obj, field_name)
    if not json_field:
        json_field = {}
        setattr(obj, field_name, json_field)

    # Navigate to nested location
    current = json_field
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Set value
    if keys:
        current[keys[-1]] = value

    # Mark as modified for SQLAlchemy
    flag_modified(obj, field_name)


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    # SafeDict
    'SafeDict',

    # Type conversion
    'safe_float',
    'safe_decimal',
    'safe_int',

    # Message utilities
    'safe_delete_message',
    'FakeCallbackQuery',

    # User notes
    'get_user_note',
    'set_user_note',

    # Email
    'normalize_email',

    # Data parsing
    'parse_date',
    'parse_bool',
    'parse_int',
    'parse_float',
    'clean_str',

    # JSON fields
    'safe_get_json_value',
    'safe_set_json_value',
]