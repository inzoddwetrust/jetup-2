# jetup-2/config.py
"""
Configuration management for Jetup bot.
Loads from .env and Google Sheets, validates critical keys.
"""
import os
import logging
from typing import Any, Dict, List
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
    MAILGUN_REGION = "MAILGUN_REGION"
    SECURE_EMAIL_DOMAINS = "SECURE_EMAIL_DOMAINS"

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
    STRATEGY_COEFFICIENTS = "STRATEGY_COEFFICIENTS"

    # Payment & Wallets
    WALLET_TRC = "WALLET_TRC"
    WALLET_ETH = "WALLET_ETH"
    WALLETS = "WALLETS"
    STABLECOINS = "STABLECOINS"
    TX_BROWSERS = "TX_BROWSERS"

    # Blockchain APIs
    ETHERSCAN_API_KEY = "ETHERSCAN_API_KEY"
    BSCSCAN_API_KEY = "BSCSCAN_API_KEY"
    TRON_API_KEY = "TRON_API_KEY"

    # System
    SYSTEM_READY = "SYSTEM_READY"
    BOT_USERNAME = "BOT_USERNAME"

    # Channels (для проверки подписки)
    REQUIRED_CHANNELS = "REQUIRED_CHANNELS"

    # Help & Settings
    FAQ_URL = "FAQ_URL"
    SOCIAL_LINKS = "SOCIAL_LINKS"
    ADMIN_LINKS = "ADMIN_LINKS"

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
            import json

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
            cls._config[cls.MAILGUN_REGION] = os.getenv("MAILGUN_REGION", "eu")
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

            # Wallets and Payment Configuration
            cls._config[cls.WALLET_TRC] = os.getenv("WALLET_TRC")
            cls._config[cls.WALLET_ETH] = os.getenv("WALLET_ETH")

            cls._config[cls.WALLETS] = {
                "USDT-TRC20": cls._config[cls.WALLET_TRC],
                "TRX": cls._config[cls.WALLET_TRC],
                "ETH": cls._config[cls.WALLET_ETH],
                "BNB": cls._config[cls.WALLET_ETH],
                "USDT-BSC20": cls._config[cls.WALLET_ETH],
                "USDT-ERC20": cls._config[cls.WALLET_ETH]
            }

            cls._config[cls.STABLECOINS] = ["USDT-ERC20", "USDT-BSC20", "USDT-TRC20"]

            cls._config[cls.TX_BROWSERS] = {
                "ETH": "https://etherscan.io/tx/",
                "BNB": "https://bscscan.com/tx/",
                "USDT-ERC20": "https://etherscan.io/tx/",
                "USDT-BSC20": "https://bscscan.com/tx/",
                "TRX": "https://tronscan.org/#/transaction/",
                "USDT-TRC20": "https://tronscan.org/#/transaction/"
            }

            # Blockchain API Keys
            cls._config[cls.ETHERSCAN_API_KEY] = os.getenv("ETHERSCAN_API_KEY")
            cls._config[cls.BSCSCAN_API_KEY] = os.getenv("BSCSCAN_API_KEY")
            cls._config[cls.TRON_API_KEY] = os.getenv("TRON_API_KEY")

            # Channels (JSON format)
            channels_str = os.getenv("REQUIRED_CHANNELS", "[]")
            try:
                cls._config[cls.REQUIRED_CHANNELS] = json.loads(channels_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse REQUIRED_CHANNELS JSON: {e}")
                cls._config[cls.REQUIRED_CHANNELS] = []

            # Help & Settings - defaults (will be overridden by Google Sheets)
            cls._config[cls.FAQ_URL] = ""
            cls._config[cls.SOCIAL_LINKS] = {}
            cls._config[cls.ADMIN_LINKS] = []

            # System
            cls._config[cls.SYSTEM_READY] = False
            cls._config[cls.BOT_USERNAME] = None

            cls._initialized = True
            logger.info("Configuration loaded from environment successfully")

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            raise ConfigurationError(f"Configuration loading failed: {e}")

    @classmethod
    def get_channels_by_lang(cls, lang: str) -> List[Dict[str, str]]:
        """
        Get required channels filtered by language.

        Args:
            lang: Language code (en, de, ru)

        Returns:
            List of channel dicts for specified language
        """
        all_channels = cls.get(cls.REQUIRED_CHANNELS, [])
        return [ch for ch in all_channels if ch.get('lang') == lang]

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
    async def initialize_dynamic_from_sheets(cls) -> None:
        """
        Load dynamic configuration and data from Google Sheets.

        This method:
        1. Loads configuration variables from Config sheet
        2. Imports Projects and Options data
        3. Initializes StatsService for caching metrics

        Merges with .env configuration, Google Sheets values take precedence.

        Expected Config sheet format:
        | key | value | description |

        Raises:
            ConfigurationError: If critical error occurs during loading
        """
        try:
            from services.data_importer import ConfigImporter
            from services.imports import import_projects_and_options
            from services.stats_service import StatsService
            from core.di import register_service

            # ========================================================================
            # STEP 1: Load configuration variables
            # ========================================================================
            logger.info("Loading dynamic configuration from Google Sheets...")
            config_dict = await ConfigImporter.import_config()

            if not config_dict:
                logger.warning("No configuration loaded from Google Sheets")
                return

            logger.info(f"Loaded {len(config_dict)} configuration variables from Google Sheets")

            # Update known configuration keys
            updates = []

            if 'REQUIRED_CHANNELS' in config_dict:
                cls.set(cls.REQUIRED_CHANNELS, config_dict['REQUIRED_CHANNELS'], source="sheets")
                updates.append(f"REQUIRED_CHANNELS: {len(config_dict['REQUIRED_CHANNELS'])} channels")

            if 'DEFAULT_REFERRER_ID' in config_dict:
                cls.set(cls.DEFAULT_REFERRER_ID, config_dict['DEFAULT_REFERRER_ID'], source="sheets")
                updates.append(f"DEFAULT_REFERRER_ID: {config_dict['DEFAULT_REFERRER_ID']}")

            if 'STRATEGY_COEFFICIENTS' in config_dict:
                cls.set(cls.STRATEGY_COEFFICIENTS, config_dict['STRATEGY_COEFFICIENTS'], source="sheets")
                updates.append(f"STRATEGY_COEFFICIENTS: loaded")

            if 'FAQ_URL' in config_dict:
                cls.set(cls.FAQ_URL, config_dict['FAQ_URL'], source="sheets")
                updates.append(f"FAQ_URL: {config_dict['FAQ_URL']}")

            if 'SOCIAL_LINKS' in config_dict:
                cls.set(cls.SOCIAL_LINKS, config_dict['SOCIAL_LINKS'], source="sheets")
                updates.append(f"SOCIAL_LINKS: {len(config_dict['SOCIAL_LINKS'])} links")

            if 'ADMIN_LINKS' in config_dict:
                cls.set(cls.ADMIN_LINKS, config_dict['ADMIN_LINKS'], source="sheets")
                updates.append(f"ADMIN_LINKS: {len(config_dict['ADMIN_LINKS'])} admins")

            if 'WALLETS' in config_dict:
                cls.set('WALLETS', config_dict['WALLETS'], source="sheets")
                updates.append(f"WALLETS: {len(config_dict['WALLETS'])} configured")

            if 'SECURE_EMAIL_DOMAINS' in config_dict:
                cls.set('SECURE_EMAIL_DOMAINS', config_dict['SECURE_EMAIL_DOMAINS'], source="sheets")
                updates.append(f"SECURE_EMAIL_DOMAINS: {config_dict['SECURE_EMAIL_DOMAINS']}")

            for key, value in config_dict.items():
                if key not in ['REQUIRED_CHANNELS', 'DEFAULT_REFERRER_ID', 'FAQ_URL',
                               'SOCIAL_LINKS', 'ADMIN_LINKS', 'WALLETS', 'SECURE_EMAIL_DOMAINS',
                               'STRATEGY_COEFFICIENTS']:
                    cls.set(key, value, source="sheets")

            if updates:
                logger.info("Updated configuration from Google Sheets:")
                for update in updates:
                    logger.info(f"  - {update}")

            logger.info("✓ Configuration variables loaded")

            # ========================================================================
            # STEP 2: Import Projects and Options
            # ========================================================================
            logger.info("Importing Projects and Options from Google Sheets...")
            import_result = await import_projects_and_options()

            if import_result["success"]:
                logger.info(
                    f"✓ Projects: "
                    f"added={import_result['projects']['added']}, "
                    f"updated={import_result['projects']['updated']}, "
                    f"errors={import_result['projects']['errors']}"
                )
                logger.info(
                    f"✓ Options: "
                    f"added={import_result['options']['added']}, "
                    f"updated={import_result['options']['updated']}, "
                    f"errors={import_result['options']['errors']}"
                )

                # Log errors if any
                if import_result["error_messages"]:
                    logger.warning(f"Import errors: {len(import_result['error_messages'])}")
                    for error_msg in import_result["error_messages"][:3]:
                        logger.warning(f"  - {error_msg}")
                    if len(import_result["error_messages"]) > 3:
                        logger.warning(f"  ... and {len(import_result['error_messages']) - 3} more")
            else:
                logger.error("⚠️ Projects/Options import failed")
                for error_msg in import_result["error_messages"][:5]:
                    logger.error(f"  - {error_msg}")

            # ========================================================================
            # STEP 3: Initialize StatsService
            # ========================================================================
            logger.info("Initializing statistics service...")
            stats_service = StatsService()
            await stats_service.initialize()
            register_service(StatsService, stats_service)
            logger.info("✓ StatsService initialized and registered")

            logger.info("=" * 60)
            logger.info("✅ DYNAMIC CONFIGURATION LOADED SUCCESSFULLY")
            logger.info("=" * 60)

        except Exception as e:
            logger.error(f"Failed to load dynamic configuration: {e}", exc_info=True)
            logger.warning("⚠️ Continuing with .env configuration only")
            # Don't raise - allow bot to start with basic configuration

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