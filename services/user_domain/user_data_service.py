# jetup/services/user_data_service.py
"""
User data collection service.
Manages personal data input flow with validation.
"""
import logging
import re
import secrets
import string
from datetime import datetime, timezone
from typing import Tuple, Any, Dict, Optional
from sqlalchemy.orm.attributes import flag_modified

from models.user import User

logger = logging.getLogger(__name__)


# ============================================================================
# FIELD VALIDATORS
# ============================================================================

class FieldValidator:
    """Validators for user input fields."""

    @staticmethod
    def validate_name(value: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate first and last names.
        Must be alphabetic and start with capital letter.
        """
        value = value.strip()
        if not value.isalpha() or not value[0].isupper():
            return False, None
        return True, value

    @staticmethod
    def validate_date(value: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate date in dd.mm.yyyy format.
        """
        try:
            parsed_date = datetime.strptime(value.strip(), "%d.%m.%Y")
            return True, parsed_date
        except ValueError:
            return False, None

    @staticmethod
    def validate_passport(value: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate passport number.
        Length between 6-20 characters, alphanumeric.
        """
        value = value.strip()
        if len(value) < 6 or len(value) > 20:
            return False, None

        # Remove spaces and special characters, keep only alphanumeric and /-
        cleaned = ''.join(c for c in value if c.isalnum() or c in '/-')
        if not cleaned:
            return False, None

        return True, cleaned

    @staticmethod
    def validate_phone(value: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate phone number.
        Must be digits only (optional + prefix).
        """
        value = value.strip()

        # Remove + prefix if present
        if value.startswith("+"):
            value = value[1:]

        if not value.isdigit():
            return False, None

        return True, value

    @staticmethod
    def validate_email(value: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate email address.
        Basic format check.
        """
        value = value.strip()
        if not re.match(r"[^@]+@[^@]+\.[^@]+", value):
            return False, None
        return True, value

    @staticmethod
    def validate_text(value: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate general text input (country, city, address).
        """
        value = value.strip()
        if not value:
            return False, None
        return True, value


# ============================================================================
# FIELD CONFIGURATION
# ============================================================================

FIELD_CONFIG = {
    'waiting_for_firstname': {
        'field': 'firstname',
        'validator': 'validate_name',
        'template_request': 'user_data_firstname',
        'template_error': 'user_data_firstname_error',
        'next_state': 'waiting_for_surname'
    },
    'waiting_for_surname': {
        'field': 'surname',
        'validator': 'validate_name',
        'template_request': 'user_data_surname',
        'template_error': 'user_data_surname_error',
        'next_state': 'waiting_for_birthday'
    },
    'waiting_for_birthday': {
        'field': 'birthday',
        'validator': 'validate_date',
        'template_request': 'user_data_birthday',
        'template_error': 'user_data_birthday_error',
        'next_state': 'waiting_for_passport'
    },
    'waiting_for_passport': {
        'field': 'passport',
        'validator': 'validate_passport',
        'template_request': 'user_data_passport',
        'template_error': 'user_data_passport_error',
        'next_state': 'waiting_for_country'
    },
    'waiting_for_country': {
        'field': 'country',
        'validator': 'validate_text',
        'template_request': 'user_data_country',
        'template_error': 'user_data_country_error',
        'next_state': 'waiting_for_city'
    },
    'waiting_for_city': {
        'field': 'city',
        'validator': 'validate_text',
        'template_request': 'user_data_city',
        'template_error': 'user_data_city_error',
        'next_state': 'waiting_for_address'
    },
    'waiting_for_address': {
        'field': 'address',
        'validator': 'validate_text',
        'template_request': 'user_data_address',
        'template_error': 'user_data_address_error',
        'next_state': 'waiting_for_phone'
    },
    'waiting_for_phone': {
        'field': 'phoneNumber',
        'validator': 'validate_phone',
        'template_request': 'user_data_phone',
        'template_error': 'user_data_phone_error',
        'next_state': 'waiting_for_email'
    },
    'waiting_for_email': {
        'field': 'email',
        'validator': 'validate_email',
        'template_request': 'user_data_email',
        'template_error': 'user_data_email_error',
        'next_state': 'waiting_for_confirmation'
    }
}


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_verification_token() -> str:
    """
    Generate 16-character token for email verification.

    Returns:
        Random alphanumeric token
    """
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(16))


def get_state_name(state_str: str) -> str:
    """
    Extract clean state name from FSM state string.

    Args:
        state_str: Full state string (e.g. "UserDataDialog:waiting_for_firstname")

    Returns:
        Clean state name (e.g. "waiting_for_firstname")
    """
    if ':' in state_str:
        return state_str.split(':')[1]
    return state_str


def find_previous_state(current_state_name: str) -> Optional[str]:
    """
    Find state that points to current state in FIELD_CONFIG.

    Args:
        current_state_name: Current state name

    Returns:
        Previous state name or None
    """
    # First state has no previous
    if current_state_name == 'waiting_for_firstname':
        return None

    # Search for state that points to current
    for state_name, config in FIELD_CONFIG.items():
        if config['next_state'] == current_state_name:
            return state_name

    logger.error(f"Previous state not found for {current_state_name}")
    return None


# ============================================================================
# USER DATA SERVICE
# ============================================================================

class UserDataService:
    """Service for managing user data collection flow."""

    @staticmethod
    def validate_input(value: str, validator_name: str) -> Tuple[bool, Optional[Any]]:
        """
        Validate user input using specified validator.

        Args:
            value: User input value
            validator_name: Name of validator method

        Returns:
            Tuple (is_valid: bool, processed_value: Any)
        """
        validator = getattr(FieldValidator, validator_name, None)
        if not validator:
            logger.error(f"Validator not found: {validator_name}")
            return False, None

        return validator(value)

    @staticmethod
    def format_birthday(birthday: datetime) -> str:
        """
        Format birthday for storage (string format for flexibility).

        Args:
            birthday: Birthday datetime

        Returns:
            Formatted string (dd.mm.yyyy)
        """
        return birthday.strftime('%d.%m.%Y')

    @staticmethod
    async def save_user_data(
            user: User,
            user_data: Dict[str, Any],
            session
    ) -> bool:
        """
        Save collected user data to database.

        Args:
            user: User object
            user_data: Dict with collected data
            session: Database session

        Returns:
            True if saved successfully
        """
        try:
            # Update user fields
            user.firstname = user_data.get('firstname')
            user.surname = user_data.get('surname')

            # Birthday as string
            birthday = user_data.get('birthday')
            if isinstance(birthday, datetime):
                user.birthday = UserDataService.format_birthday(birthday)
            else:
                user.birthday = birthday

            user.passport = user_data.get('passport')
            user.country = user_data.get('country')
            user.city = user_data.get('city')
            user.address = user_data.get('address')
            user.phoneNumber = user_data.get('phoneNumber')
            user.email = user_data.get('email')

            # Update personalData JSON field
            if not user.personalData:
                user.personalData = {}

            user.personalData['dataFilled'] = True
            user.personalData['filledAt'] = datetime.now(timezone.utc).isoformat()

            flag_modified(user, 'personalData')

            # Commit changes
            session.commit()
            session.refresh(user)

            logger.info(f"User data saved successfully for user {user.userID}")
            return True

        except Exception as e:
            session.rollback()
            logger.error(f"Error saving user data for user {user.userID}: {e}", exc_info=True)
            return False

    @staticmethod
    def initialize_email_verification(user: User, session) -> str:
        """
        Initialize email verification for user.
        Generates token and updates emailVerification field.

        Args:
            user: User object
            session: Database session

        Returns:
            Generated verification token
        """
        # Generate token
        token = generate_verification_token()

        # Initialize or update emailVerification field
        if not user.emailVerification:
            user.emailVerification = {}

        user.emailVerification['confirmed'] = False
        user.emailVerification['token'] = token
        user.emailVerification['sentAt'] = datetime.now(timezone.utc).isoformat()
        user.emailVerification['attempts'] = user.emailVerification.get('attempts', 0) + 1

        flag_modified(user, 'emailVerification')

        session.commit()

        logger.info(f"Email verification initialized for user {user.userID}")
        return token

    @staticmethod
    def initialize_old_email_verification(user: User, old_email: str, session) -> str:
        """
        Initialize old email verification for DARWIN migrated users.

        Args:
            user: User object
            old_email: Old email address from DARWIN
            session: Database session

        Returns:
            Generated verification token
        """
        # Generate token
        token = generate_verification_token()

        # Initialize or update emailVerification field
        if not user.emailVerification:
            user.emailVerification = {}

        user.emailVerification['old_email'] = old_email
        user.emailVerification['old_email_token'] = token
        user.emailVerification['old_email_confirmed'] = False
        user.emailVerification['old_email_sentAt'] = datetime.now(timezone.utc).isoformat()

        flag_modified(user, 'emailVerification')

        session.commit()

        logger.info(f"Old email verification initialized for user {user.userID}: {old_email}")
        return token