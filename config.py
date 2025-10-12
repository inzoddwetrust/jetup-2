# jetup/config.py
"""
Configuration management for Jetup bot.
Loads from .env and Google Sheets, validates critical keys.
"""
import os
import logging
from typing import Any, Dict
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Configuration error exception."""
    pass


class Config:
    """
    Configuration manager with static and dynamic values.

    Usage:
        # Load from .env
        Config.initialize_from_env()

        # Get value
        token = Config.get(Config.API_TOKEN)

        # Set dynamic value
        Config.set(Config.SYSTEM_READY, True)
    """

    # ═══════════════════════════════════════════════════════════════════════
    # CONFIGURATION KEYS
    # ═══════════════════════════════════════════════════════════════════════

    # Telegram Bot
    API_TOKEN = "API_TOKEN"
    ADMIN_USER_IDS = "ADMIN_USER_IDS"

    # Database
    DATABASE_URL = "DATABASE_URL"

    # Google Services
    GOOGLE_SHEET_ID = "GOOGLE_SHEET_ID"
    GOOGLE_CREDENTIALS_PATH = "GOOGLE_CREDENTIALS_PATH"

    # Email - Mailgun
    MAILGUN_API_KEY = "MAILGUN_API_KEY"
    MAILGUN_DOMAIN = "MAILGUN_DOMAIN"
    MAILGUN_FROM_EMAIL = "MAILGUN_FROM_EMAIL"

    # Email - SMTP
    SMTP_HOST = "SMTP_HOST"
    SMTP_PORT = "SMTP_PORT"
    SMTP_USERNAME = "SMTP_USERNAME"
    SMTP_PASSWORD = "SMTP_PASSWORD"
    SMTP_USE_TLS = "SMTP_USE_TLS"
    SMTP_FROM_EMAIL = "SMTP_FROM_EMAIL"

    # BookStack
    BOOKSTACK_URL = "BOOKSTACK_URL"
    BOOKSTACK_TOKEN_ID = "BOOKSTACK_TOKEN_ID"
    BOOKSTACK_TOKEN_SECRET = "BOOKSTACK_TOKEN_SECRET"

    # MLM System
    DEFAULT_REFERRER_ID = "DEFAULT_REFERRER_ID"

    # System
    SYSTEM_READY = "SYSTEM_READY"
    BOT_USERNAME = "BOT_USERNAME"

    # Channels (для проверки подписки)
    REQUIRED_CHANNELS = "REQUIRED_CHANNELS"

    # ═══════════════════════════════════════════════════════════════════════
    # CRITICAL KEYS (must be present)
    # ═══════════════════════════════════════════════════════════════════════

    CRITICAL_KEYS = [
        API_TOKEN,
        GOOGLE_SHEET_ID,
        GOOGLE_CREDENTIALS_PATH,
    ]

    # ═══════════════════════════════════════════════════════════════════════
    # STORAGE
    # ═══════════════════════════════════════════════════════════════════════

    _config: Dict[str, Any] = {}
    _initialized: bool = False

    # ═══════════════════════════════════════════════════════════════════════
    # METHODS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def initialize_from_env(cls) -> None:
        """
        Load configuration from .env file.

        Raises:
            ConfigurationError: If .env file not found or parsing fails
        """
        load_dotenv()

        logger.info("Loading configuration from environment...")

        try:
            # Telegram
            cls._config[cls.API_TOKEN] = os.getenv("API_TOKEN")

            admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
            if admin_ids_str:
                cls._config[cls.ADMIN_USER_IDS] = [
                    int(x.strip()) for x in admin_ids_str.split(',')
                ]
            else:
                cls._config[cls.ADMIN_USER_IDS] = []

            # Database
            cls._config[cls.DATABASE_URL] = os.getenv(
                "DATABASE_URL",
                "sqlite:///jetup.db"
            )

            # Google Services
            cls._config[cls.GOOGLE_SHEET_ID] = os.getenv("GOOGLE_SHEET_ID")
            cls._config[cls.GOOGLE_CREDENTIALS_PATH] = os.getenv(
                "GOOGLE_CREDENTIALS_PATH",
                "creds/google_credentials.json"
            )

            # Email - Mailgun
            cls._config[cls.MAILGUN_API_KEY] = os.getenv("MAILGUN_API_KEY")
            cls._config[cls.MAILGUN_DOMAIN] = os.getenv("MAILGUN_DOMAIN")
            cls._config[cls.MAILGUN_FROM_EMAIL] = os.getenv(
                "MAILGUN_FROM_EMAIL",
                "noreply@talentir.info"
            )

            # Email - SMTP
            cls._config[cls.SMTP_HOST] = os.getenv("SMTP_HOST")
            cls._config[cls.SMTP_PORT] = int(os.getenv("SMTP_PORT", "587"))
            cls._config[cls.SMTP_USERNAME] = os.getenv("SMTP_USERNAME")
            cls._config[cls.SMTP_PASSWORD] = os.getenv("SMTP_PASSWORD")
            cls._config[cls.SMTP_USE_TLS] = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
            cls._config[cls.SMTP_FROM_EMAIL] = os.getenv(
                "SMTP_FROM_EMAIL",
                "noreply@talentir.info"
            )

            # BookStack
            cls._config[cls.BOOKSTACK_URL] = os.getenv("BOOKSTACK_URL")
            cls._config[cls.BOOKSTACK_TOKEN_ID] = os.getenv("BOOKSTACK_TOKEN_ID")
            cls._config[cls.BOOKSTACK_TOKEN_SECRET] = os.getenv("BOOKSTACK_TOKEN_SECRET")

            # MLM
            cls._config[cls.DEFAULT_REFERRER_ID] = int(
                os.getenv("DEFAULT_REFERRER_ID", "526738615")
            )

            # Channels
            channels_str = os.getenv("REQUIRED_CHANNELS", "")
            if channels_str:
                cls._config[cls.REQUIRED_CHANNELS] = [
                    ch.strip() for ch in channels_str.split(',')
                ]
            else:
                cls._config[cls.REQUIRED_CHANNELS] = []

            # System
            cls._config[cls.SYSTEM_READY] = False
            cls._config[cls.BOT_USERNAME] = None

            cls._initialized = True
            logger.info("Configuration loaded from environment successfully")

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise ConfigurationError(f"Configuration loading failed: {e}")

    @classmethod
    async def validate_critical_keys(cls) -> None:
        """
        Validate that all critical configuration keys are present.

        Raises:
            ConfigurationError: If any critical key is missing
        """
        missing = []
        for key in cls.CRITICAL_KEYS:
            if not cls.get(key):
                missing.append(key)

        if missing:
            error_msg = f"Missing critical configuration keys: {', '.join(missing)}"
            logger.critical(error_msg)
            raise ConfigurationError(error_msg)

        logger.info("All critical configuration keys validated ✓")

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        return cls._config.get(key, default)

    @classmethod
    def set(cls, key: str, value: Any, source: str = "runtime") -> None:
        """
        Set configuration value (for dynamic updates).

        Args:
            key: Configuration key
            value: New value
            source: Source of the update (for logging)
        """
        cls._config[key] = value
        logger.debug(f"Config updated: {key} = {value} (source: {source})")

    @classmethod
    def get_all(cls) -> Dict[str, Any]:
        """
        Get all configuration values.

        Returns:
            Copy of configuration dictionary
        """
        return cls._config.copy()

    @classmethod
    def is_admin(cls, user_id: int) -> bool:
        """
        Check if user is admin.

        Args:
            user_id: Telegram user ID

        Returns:
            True if user is admin
        """
        admin_ids = cls.get(cls.ADMIN_USER_IDS, [])
        return user_id in admin_ids