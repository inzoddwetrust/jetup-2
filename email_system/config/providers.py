# jetup/email_system/config/providers.py
"""
Email provider configurations.
"""
import logging
from enum import Enum
from typing import Dict, Any

logger = logging.getLogger(__name__)


class EmailProvider(Enum):
    """Available email providers."""
    MAILGUN = "mailgun"
    SMTP = "smtp"


class EmailProviderConfig:
    """Email provider configuration manager."""

    @staticmethod
    def get_mailgun_config(config) -> Dict[str, Any]:
        """
        Get Mailgun configuration.

        Args:
            config: Config instance

        Returns:
            Dict with Mailgun settings
        """
        from config import Config

        return {
            "api_key": Config.get(Config.MAILGUN_API_KEY),
            "domain": Config.get(Config.MAILGUN_DOMAIN),
            "from_email": Config.get(Config.MAILGUN_FROM_EMAIL),
        }

    @staticmethod
    def get_smtp_config(config) -> Dict[str, Any]:
        """
        Get SMTP configuration.

        Args:
            config: Config instance

        Returns:
            Dict with SMTP settings
        """
        from config import Config

        return {
            "host": Config.get(Config.SMTP_HOST),
            "port": Config.get(Config.SMTP_PORT, 587),
            "username": Config.get(Config.SMTP_USERNAME),
            "password": Config.get(Config.SMTP_PASSWORD),
            "use_tls": Config.get(Config.SMTP_USE_TLS, True),
            "from_email": Config.get(Config.SMTP_FROM_EMAIL),
        }

    @staticmethod
    def detect_available_provider() -> EmailProvider:
        """
        Detect which email provider is configured.

        Returns:
            EmailProvider enum
        """
        from config import Config

        # Check Mailgun first
        if Config.get(Config.MAILGUN_API_KEY) and Config.get(Config.MAILGUN_DOMAIN):
            logger.info("Email provider: Mailgun")
            return EmailProvider.MAILGUN

        # Check SMTP
        if Config.get(Config.SMTP_HOST) and Config.get(Config.SMTP_USERNAME):
            logger.info("Email provider: SMTP")
            return EmailProvider.SMTP

        logger.warning("No email provider configured!")
        return None