# jetup-2/config.py
"""
Configuration management for Jetup bot.
Loads from .env and Google Sheets, validates critical keys.

Enhanced with dynamic values support for:
- Crypto rates (BNB, ETH, TRX) - auto-update every 5 minutes
- Statistics (users, projects, invested total) - auto-update periodically
"""
import os
import json
import asyncio
import logging
from typing import Any, Dict, List, Callable, Optional
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Configuration error exception."""
    pass


class Config:
    """
    Configuration manager with static and dynamic values.

    Static values: Loaded from .env, immutable
    Dynamic values: Auto-updated periodically (crypto rates, stats)

    Usage:
        # Load from .env
        Config.initialize_from_env()

        # Get static value
        token = Config.get(Config.API_TOKEN)

        # Get dynamic value (with auto-update check)
        rates = await Config.get_dynamic(Config.CRYPTO_RATES)

        # Register dynamic value
        Config.register_dynamic(
            Config.CRYPTO_RATES,
            get_crypto_rates_func,
            interval=300  # 5 minutes
        )
    """

    # ═══════════════════════════════════════════════════════════════════════
    # STATIC CONFIGURATION KEYS (from .env)
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
    INVESTMENT_BONUS_TIERS = "INVESTMENT_BONUS_TIERS"
    RANK_CONFIG = "RANK_CONFIG"

    # Payment & Wallets
    WALLET_TRC = "WALLET_TRC"
    WALLET_ETH = "WALLET_ETH"
    WALLETS = "WALLETS"
    STABLECOINS = "STABLECOINS"
    TX_BROWSERS = "TX_BROWSERS"
    WITHDRAWAL_FEE = "WITHDRAWAL_FEE"
    WITHDRAWAL_MIN = "WITHDRAWAL_MIN"

    # Blockchain APIs
    ETHERSCAN_API_KEY = "ETHERSCAN_API_KEY"
    BSCSCAN_API_KEY = "BSCSCAN_API_KEY"
    TRON_API_KEY = "TRON_API_KEY"

    # Webhook (Google Sheets Sync)
    WEBHOOK_SECRET_KEY = "WEBHOOK_SECRET_KEY"
    WEBHOOK_PORT = "WEBHOOK_PORT"
    WEBHOOK_HOST = "WEBHOOK_HOST"
    WEBHOOK_HEALTH_TOKEN = "WEBHOOK_HEALTH_TOKEN"
    WEBHOOK_RATE_LIMIT_REQUESTS = "WEBHOOK_RATE_LIMIT_REQUESTS"
    WEBHOOK_RATE_LIMIT_WINDOW = "WEBHOOK_RATE_LIMIT_WINDOW"
    WEBHOOK_ALLOWED_IPS = "WEBHOOK_ALLOWED_IPS"

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
    # DYNAMIC CONFIGURATION KEYS (auto-updated)
    # ═══════════════════════════════════════════════════════════════════════

    # Crypto rates (updated every 5 minutes)
    CRYPTO_RATES = "crypto_rates"

    # Statistics (updated periodically)
    USERS_COUNT = "users_count"
    PROJECTS_COUNT = "projects_count"
    INVESTED_TOTAL = "invested_total"
    SORTED_PROJECTS = "sorted_projects"

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

    # Static values from .env
    _config: Dict[str, Any] = {}
    _initialized: bool = False

    # Dynamic values with auto-update
    _dynamic_values: Dict[str, Any] = {}
    _update_functions: Dict[str, Callable] = {}
    _update_intervals: Dict[str, int] = {}
    _last_updates: Dict[str, datetime] = {}
    _is_updating: Dict[str, bool] = {}  # Prevent concurrent updates

    # Update loop control
    _update_loop_task: Optional[asyncio.Task] = None
    _update_loop_running: bool = False

    # ═══════════════════════════════════════════════════════════════════════
    # STATIC CONFIGURATION METHODS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def initialize_from_env(cls) -> None:
        """
        Load configuration from .env file.

        Raises:
            ConfigurationError: If critical keys are missing
        """
        try:
            load_dotenv()
            logger.info("Loading configuration from .env...")

            # ─────────────────────────────────────────────────────────────────
            # Telegram Bot
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.API_TOKEN] = os.getenv("API_TOKEN")

            admin_ids_str = os.getenv("ADMIN_USER_IDS", "")
            cls._config[cls.ADMIN_USER_IDS] = [
                int(uid.strip()) for uid in admin_ids_str.split(",") if uid.strip()
            ]

            # ─────────────────────────────────────────────────────────────────
            # Database
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.DATABASE_URL] = os.getenv("DATABASE_URL")

            # ─────────────────────────────────────────────────────────────────
            # Google Services
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.GOOGLE_SHEET_ID] = os.getenv("GOOGLE_SHEET_ID")
            cls._config[cls.GOOGLE_CREDENTIALS_PATH] = os.getenv(
                "GOOGLE_CREDENTIALS_PATH",
                "/opt/jetup/creds/google_credentials.json"
            )

            # ─────────────────────────────────────────────────────────────────
            # Email - Mailgun
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.MAILGUN_API_KEY] = os.getenv("MAILGUN_API_KEY")
            cls._config[cls.MAILGUN_DOMAIN] = os.getenv("MAILGUN_DOMAIN")
            cls._config[cls.MAILGUN_FROM_EMAIL] = os.getenv(
                "MAILGUN_FROM_EMAIL",
                "noreply@jetup.info"
            )
            cls._config[cls.MAILGUN_REGION] = os.getenv("MAILGUN_REGION", "eu")
            cls._config[cls.SECURE_EMAIL_DOMAINS] = os.getenv(
                "SECURE_EMAIL_DOMAINS",
                "@t-online.de,@gmx.de,@web.de"
            )

            # ─────────────────────────────────────────────────────────────────
            # Email - SMTP
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.SMTP_HOST] = os.getenv("SMTP_HOST", "mail.jetup.info")
            cls._config[cls.SMTP_PORT] = int(os.getenv("SMTP_PORT", "587"))
            cls._config[cls.SMTP_USERNAME] = os.getenv("SMTP_USERNAME")
            cls._config[cls.SMTP_PASSWORD] = os.getenv("SMTP_PASSWORD")
            cls._config[cls.SMTP_USE_TLS] = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
            cls._config[cls.SMTP_FROM_EMAIL] = os.getenv(
                "SMTP_FROM_EMAIL",
                "noreply@jetup.info"
            )

            # ─────────────────────────────────────────────────────────────────
            # BookStack
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.BOOKSTACK_URL] = os.getenv(
                "BOOKSTACK_URL",
                "https://jetup.info"
            )
            cls._config[cls.BOOKSTACK_TOKEN_ID] = os.getenv("BOOKSTACK_TOKEN_ID")
            cls._config[cls.BOOKSTACK_TOKEN_SECRET] = os.getenv("BOOKSTACK_TOKEN_SECRET")

            # ─────────────────────────────────────────────────────────────────
            # MLM System
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.DEFAULT_REFERRER_ID] = int(
                os.getenv("DEFAULT_REFERRER_ID", "0")
            )

            # Strategy coefficients (JSON format)
            strategy_str = os.getenv(
                "STRATEGY_COEFFICIENTS",
                '{"manual": 1.0, "safe": 4.5, "aggressive": 11.0, "risky": 25.0}'
            )
            try:
                cls._config[cls.STRATEGY_COEFFICIENTS] = json.loads(strategy_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse STRATEGY_COEFFICIENTS: {e}")
                cls._config[cls.STRATEGY_COEFFICIENTS] = {
                    "manual": 1.0,
                    "safe": 4.5,
                    "aggressive": 11.0,
                    "risky": 25.0
                }

            # Investment bonus tiers (parsed from JSON string)
            tiers_str = os.getenv("INVESTMENT_BONUS_TIERS")
            if tiers_str:
                try:
                    tiers_dict = json.loads(tiers_str)
                    # Convert string keys to Decimal for precision
                    cls._config[cls.INVESTMENT_BONUS_TIERS] = {
                        Decimal(k): Decimal(str(v)) for k, v in tiers_dict.items()
                    }
                    logger.info(f"✓ Loaded {len(tiers_dict)} investment bonus tiers from .env")
                except (json.JSONDecodeError, ValueError) as e:
                    logger.error(f"Error parsing INVESTMENT_BONUS_TIERS: {e}")
                    # Set default tiers on error
                    cls._config[cls.INVESTMENT_BONUS_TIERS] = {
                        Decimal("1000"): Decimal("0.05"),
                        Decimal("5000"): Decimal("0.10"),
                        Decimal("25000"): Decimal("0.15"),
                        Decimal("125000"): Decimal("0.20")
                    }
                    logger.warning("Using default investment bonus tiers")
            else:
                # Default tiers if not configured in .env
                cls._config[cls.INVESTMENT_BONUS_TIERS] = {
                    Decimal("1000"): Decimal("0.05"),
                    Decimal("5000"): Decimal("0.10"),
                    Decimal("25000"): Decimal("0.15"),
                    Decimal("125000"): Decimal("0.20")
                }
                logger.info("✓ Using default investment bonus tiers (not configured in .env)")

            # ─────────────────────────────────────────────────────────────────
            # Payment & Wallets
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.WALLET_TRC] = os.getenv("WALLET_TRC")
            cls._config[cls.WALLET_ETH] = os.getenv("WALLET_ETH")

            # Wallets (JSON format)
            wallets_str = os.getenv("WALLETS", "{}")
            try:
                cls._config[cls.WALLETS] = json.loads(wallets_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse WALLETS JSON: {e}")
                cls._config[cls.WALLETS] = {}

            # Stablecoins (JSON format)
            stablecoins_str = os.getenv("STABLECOINS", '["USDT-ERC20", "USDT-BSC20", "USDT-TRC20"]')
            try:
                cls._config[cls.STABLECOINS] = json.loads(stablecoins_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse STABLECOINS JSON: {e}")
                cls._config[cls.STABLECOINS] = ["USDT-ERC20", "USDT-BSC20", "USDT-TRC20"]

            # Transaction browsers (JSON format)
            tx_browsers_str = os.getenv(
                "TX_BROWSERS",
                '{"ETH": "https://etherscan.io/tx/", "BSC": "https://bscscan.com/tx/", "TRX": "https://tronscan.org/#/transaction/"}'
            )
            try:
                cls._config[cls.TX_BROWSERS] = json.loads(tx_browsers_str)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse TX_BROWSERS JSON: {e}")
                cls._config[cls.TX_BROWSERS] = {
                    "ETH": "https://etherscan.io/tx/",
                    "BSC": "https://bscscan.com/tx/",
                    "TRX": "https://tronscan.org/#/transaction/"
                }

            # ─────────────────────────────────────────────────────────────────
            # Blockchain APIs
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.ETHERSCAN_API_KEY] = os.getenv("ETHERSCAN_API_KEY")
            cls._config[cls.BSCSCAN_API_KEY] = os.getenv("BSCSCAN_API_KEY")
            cls._config[cls.TRON_API_KEY] = os.getenv("TRON_API_KEY")

            # ─────────────────────────────────────────────────────────────────
            # Webhook (Google Sheets Sync)
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.WEBHOOK_SECRET_KEY] = os.getenv("WEBHOOK_SECRET_KEY")
            cls._config[cls.WEBHOOK_PORT] = int(os.getenv("WEBHOOK_PORT", "8080"))
            cls._config[cls.WEBHOOK_HOST] = os.getenv("WEBHOOK_HOST", "127.0.0.1")
            cls._config[cls.WEBHOOK_HEALTH_TOKEN] = os.getenv("WEBHOOK_HEALTH_TOKEN")
            cls._config[cls.WEBHOOK_RATE_LIMIT_REQUESTS] = int(os.getenv("WEBHOOK_RATE_LIMIT_REQUESTS", "30"))
            cls._config[cls.WEBHOOK_RATE_LIMIT_WINDOW] = int(os.getenv("WEBHOOK_RATE_LIMIT_WINDOW", "60"))

            webhook_ips = os.getenv("WEBHOOK_ALLOWED_IPS", "")
            cls._config[cls.WEBHOOK_ALLOWED_IPS] = [
                ip.strip() for ip in webhook_ips.split(",") if ip.strip()
            ]

            # ─────────────────────────────────────────────────────────────────
            # System
            # ─────────────────────────────────────────────────────────────────
            cls._config[cls.SYSTEM_READY] = False
            cls._config[cls.BOT_USERNAME] = None

            # Mark as initialized
            cls._initialized = True
            logger.info("✓ Configuration loaded from .env")

        except Exception as e:
            logger.error(f"Failed to load configuration: {e}", exc_info=True)
            raise ConfigurationError(f"Configuration initialization failed: {e}")

    @classmethod
    async def initialize_dynamic_from_sheets(cls) -> None:
        """
        Load dynamic configuration from Google Sheets (Config tab).

        This loads values like:
        - REQUIRED_CHANNELS
        - RANK_CONFIG
        - FAQ_URL
        - SOCIAL_LINKS
        - ADMIN_LINKS
        """
        try:
            from services.data_importer import ConfigImporter

            logger.info("Loading dynamic configuration from Google Sheets...")

            config_data = await ConfigImporter.import_config(
                sheet_id=cls.get(cls.GOOGLE_SHEET_ID),
                sheet_name="Config"
            )

            # Update config with loaded values
            for key, value in config_data.items():
                cls._config[key] = value
                logger.debug(f"Loaded from sheets: {key}")

            logger.info(f"✓ Loaded {len(config_data)} configuration values from Google Sheets")

        except Exception as e:
            logger.error(f"Failed to load configuration from Google Sheets: {e}")
            # Non-critical error - continue with defaults

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """
        Get a static configuration value by key.

        Args:
            key: Configuration key
            default: Default value if key not found

        Returns:
            The configuration value or default

        Note:
            For dynamic values (crypto_rates, statistics), use get_dynamic() instead.
        """
        if not cls._initialized:
            logger.warning(f"Config accessed before initialization: {key}")

        return cls._config.get(key, default)

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """
        Set a static configuration value.

        Args:
            key: Configuration key
            value: Configuration value

        Note:
            This sets static values only. For dynamic values, use register_dynamic().
        """
        cls._config[key] = value
        logger.debug(f"Set config: {key}")

    @classmethod
    async def validate_critical_keys(cls) -> None:
        """
        Validate that all critical configuration keys are set.

        Raises:
            ConfigurationError: If any critical key is missing or invalid
        """
        missing = []

        for key in cls.CRITICAL_KEYS:
            value = cls.get(key)
            if value is None or (isinstance(value, (list, dict)) and not value):
                missing.append(key)

        if missing:
            error_msg = f"Missing critical configuration keys: {missing}"
            logger.critical(error_msg)
            raise ConfigurationError(error_msg)

        logger.info("✓ All critical configuration keys are valid")

    # ═══════════════════════════════════════════════════════════════════════
    # DYNAMIC CONFIGURATION METHODS
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    def register_dynamic(
        cls,
        key: str,
        update_func: Callable,
        interval: int = 300
    ) -> None:
        """
        Register a dynamic value with auto-update.

        Args:
            key: Configuration key (e.g., Config.CRYPTO_RATES)
            update_func: Async or sync function that returns new value
            interval: Update interval in seconds (default: 300 = 5 minutes)

        Example:
            Config.register_dynamic(
                Config.CRYPTO_RATES,
                get_crypto_rates,
                interval=300
            )
        """
        cls._update_functions[key] = update_func
        cls._update_intervals[key] = interval
        cls._is_updating[key] = False
        cls._last_updates[key] = datetime.min.replace(tzinfo=timezone.utc)

        logger.info(f"Registered dynamic value: {key} with {interval}s interval")

    @classmethod
    async def get_dynamic(cls, key: str, force_refresh: bool = False) -> Any:
        """
        Get a dynamic configuration value with auto-update check.

        Args:
            key: Configuration key (e.g., Config.CRYPTO_RATES)
            force_refresh: Force immediate update regardless of TTL

        Returns:
            The current value or None if not available

        Example:
            rates = await Config.get_dynamic(Config.CRYPTO_RATES)
            if rates:
                btc_rate = rates.get('BTC')
        """
        # Check if value needs update
        if force_refresh or cls._needs_update(key):
            await cls._update_value(key)

        return cls._dynamic_values.get(key)

    @classmethod
    def _needs_update(cls, key: str) -> bool:
        """
        Check if a dynamic value needs to be updated based on TTL.

        Args:
            key: Configuration key

        Returns:
            True if value is missing or TTL expired
        """
        # Value not set yet
        if key not in cls._dynamic_values:
            return True

        # No update function registered
        if key not in cls._update_intervals:
            return False

        # Check TTL
        last_update = cls._last_updates.get(key, datetime.min.replace(tzinfo=timezone.utc))
        interval = cls._update_intervals[key]
        now = datetime.now(timezone.utc)

        elapsed = (now - last_update).total_seconds()
        needs_update = elapsed > interval

        if needs_update:
            logger.debug(f"Value {key} needs update (age: {elapsed:.1f}s, TTL: {interval}s)")

        return needs_update

    @classmethod
    async def _update_value(cls, key: str) -> None:
        """
        Update a dynamic value by calling its update function.

        Args:
            key: Configuration key to update

        Note:
            This method is thread-safe and prevents concurrent updates
            of the same key.
        """
        # No update function registered
        if key not in cls._update_functions:
            logger.warning(f"No update function for {key}")
            return

        # Already updating - skip
        if cls._is_updating.get(key, False):
            logger.debug(f"Update already in progress for {key}, skipping")
            return

        try:
            cls._is_updating[key] = True
            update_func = cls._update_functions[key]

            logger.debug(f"Updating dynamic value: {key}")

            # Call update function (may be async or sync)
            result = update_func()

            # If result is coroutine, await it
            if asyncio.iscoroutine(result):
                new_value = await result
            else:
                new_value = result

            # Update value if not None
            if new_value is not None:
                cls._dynamic_values[key] = new_value
                cls._last_updates[key] = datetime.now(timezone.utc)
                logger.info(f"✓ Updated dynamic value: {key}")
            else:
                logger.warning(f"Update function for {key} returned None, keeping old value")

        except Exception as e:
            logger.error(f"Error updating dynamic value {key}: {e}", exc_info=True)

        finally:
            cls._is_updating[key] = False

    @classmethod
    async def refresh_all_dynamic(cls) -> None:
        """
        Force refresh all registered dynamic values immediately.

        Useful during initialization or after configuration changes.
        """
        logger.info("Refreshing all dynamic values...")

        for key in cls._update_functions.keys():
            try:
                await cls._update_value(key)
            except Exception as e:
                logger.error(f"Error refreshing {key}: {e}")

        logger.info("✓ All dynamic values refreshed")

    @classmethod
    async def start_update_loop(cls) -> None:
        """
        Start the background update loop for dynamic values.

        This should be called after all dynamic values are registered.
        The loop will run until stop_update_loop() is called.
        """
        if cls._update_loop_running:
            logger.warning("Update loop already running")
            return

        cls._update_loop_running = True
        logger.info("Starting dynamic values update loop")

        try:
            while cls._update_loop_running:
                # Update all values that need refreshing
                for key in list(cls._update_functions.keys()):
                    if cls._needs_update(key):
                        try:
                            await cls._update_value(key)
                        except Exception as e:
                            logger.error(f"Error in update loop for {key}: {e}")

                # Sleep until next check (use minimum interval / 2)
                if cls._update_intervals:
                    min_interval = min(cls._update_intervals.values())
                    sleep_time = min(60, min_interval / 2)  # Check at least every 60s
                else:
                    sleep_time = 60

                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("Update loop cancelled")
        except Exception as e:
            logger.error(f"Update loop error: {e}", exc_info=True)
        finally:
            cls._update_loop_running = False
            logger.info("Update loop stopped")

    @classmethod
    def stop_update_loop(cls) -> None:
        """
        Stop the background update loop.

        This should be called during bot shutdown.
        """
        cls._update_loop_running = False
        if cls._update_loop_task:
            cls._update_loop_task.cancel()
            cls._update_loop_task = None
        logger.info("Stopped dynamic values update loop")

    @classmethod
    def get_dynamic_info(cls) -> Dict[str, Dict[str, Any]]:
        """
        Get information about all dynamic values.

        Returns:
            Dictionary with details about each dynamic value:
            {
                'crypto_rates': {
                    'value': {...},
                    'last_update': datetime,
                    'interval': 300,
                    'age': 123.5,
                    'needs_update': False
                },
                ...
            }
        """
        result = {}
        now = datetime.now(timezone.utc)

        for key in cls._update_functions.keys():
            last_update = cls._last_updates.get(key, datetime.min.replace(tzinfo=timezone.utc))
            age = (now - last_update).total_seconds()
            interval = cls._update_intervals.get(key, 0)

            result[key] = {
                'value': cls._dynamic_values.get(key),
                'last_update': last_update,
                'interval': interval,
                'age': age,
                'needs_update': cls._needs_update(key),
                'is_updating': cls._is_updating.get(key, False)
            }

        return result


# Export for convenience
__all__ = ['Config', 'ConfigurationError']