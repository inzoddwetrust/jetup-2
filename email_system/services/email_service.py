# jetup/email_system/services/email_service.py
"""
Email service for sending verification and notification emails.
Manages multiple providers with smart routing based on domain.
"""
import logging
from typing import Dict, List, Any
from datetime import datetime, timezone

from models.user import User
from email_system.providers import SMTPProvider, MailgunProvider
from config import Config
from core.templates import MessageTemplates

logger = logging.getLogger(__name__)


class EmailService:
    """
    Service for sending emails via multiple providers.

    Features:
    - Smart provider selection based on domain
    - Secure domains routing (Mailgun for problematic domains)
    - Fallback between providers
    - Connection testing
    - Template-based emails from Google Sheets

    Usage:
        email_service = EmailService()
        await email_service.initialize()
        success = await email_service.send_email(
            to='user@example.com',
            subject_template_key='email/subject',
            body_template_key='email/body',
            variables={'name': 'John'},
            lang='en'
        )
    """

    def __init__(self):
        """Initialize email service."""
        self.providers: Dict[str, SMTPProvider | MailgunProvider] = {}
        self.secure_domains: List[str] = []
        self._initialized = False

    async def initialize(self) -> None:
        """
        Initialize providers and load configuration.
        Called during bot startup.
        """
        if self._initialized:
            logger.warning("EmailService already initialized")
            return

        logger.info("Initializing EmailService...")

        # Initialize SMTP provider
        smtp_host = Config.get(Config.SMTP_HOST)
        smtp_username = Config.get(Config.SMTP_USERNAME)
        smtp_password = Config.get(Config.SMTP_PASSWORD)

        logger.info(
            f"SMTP config check: host={smtp_host}, username={smtp_username}, password={'***' if smtp_password else 'EMPTY'}")

        if smtp_host and smtp_username and smtp_password:
            smtp_port = Config.get(Config.SMTP_PORT, 587)
            self.providers['smtp'] = SMTPProvider(
                host=smtp_host,
                port=smtp_port,
                username=smtp_username,
                password=smtp_password
            )
            logger.info(f"✓ SMTP provider added: {smtp_host}:{smtp_port}")
        else:
            logger.warning("SMTP provider not configured (missing credentials)")

        # Initialize Mailgun provider
        mailgun_api_key = Config.get(Config.MAILGUN_API_KEY)
        mailgun_domain = Config.get(Config.MAILGUN_DOMAIN)

        if mailgun_api_key and mailgun_domain:
            mailgun_region = Config.get('MAILGUN_REGION', 'eu')
            self.providers['mailgun'] = MailgunProvider(
                api_key=mailgun_api_key,
                domain=mailgun_domain,
                region=mailgun_region
            )
            logger.info(f"✓ Mailgun provider added: {mailgun_domain} ({mailgun_region})")
        else:
            logger.warning("Mailgun provider not configured (missing credentials)")

        # Load secure domains
        self._load_secure_domains()

        if not self.providers:
            logger.error("❌ No email providers configured!")
        else:
            logger.info(f"✓ EmailService initialized with {len(self.providers)} provider(s)")

        self._initialized = True

    def _load_secure_domains(self) -> None:
        """
        Load list of secure email domains from Config.
        These domains will use Mailgun instead of SMTP.
        """
        try:
            domains_str = Config.get('SECURE_EMAIL_DOMAINS', '')

            if domains_str:
                # Parse domains: "@t-online.de, @gmx.de" -> ["@t-online.de", "@gmx.de"]
                domains = [d.strip() for d in domains_str.split(',') if d.strip()]

                # Ensure all domains start with @
                self.secure_domains = [
                    d if d.startswith('@') else f'@{d}'
                    for d in domains
                ]

                logger.info(f"Loaded {len(self.secure_domains)} secure domains: {self.secure_domains}")
            else:
                self.secure_domains = []
                logger.info("No secure domains configured")

        except Exception as e:
            logger.warning(f"Could not load secure domains: {e}")
            self.secure_domains = []

    def reload_secure_domains(self) -> None:
        """
        Reload secure domains configuration.
        Called after &upconfig command.
        """
        logger.info("Reloading secure email domains configuration...")
        self._load_secure_domains()

    def _get_email_domain(self, email: str) -> str:
        """
        Extract domain from email address.

        Args:
            email: Email address

        Returns:
            Domain with @ prefix (e.g. "@gmail.com")
        """
        if '@' in email:
            return '@' + email.split('@')[1].lower()
        return ''

    def _select_provider_for_email(self, email: str) -> List[str]:
        """
        Select provider order based on recipient email domain.

        Logic:
        - Secure domains → Mailgun first, SMTP fallback
        - Regular domains → SMTP first, Mailgun fallback

        Args:
            email: Recipient email address

        Returns:
            List of provider names in priority order
        """
        domain = self._get_email_domain(email)

        # Check if domain is in secure list
        if domain in self.secure_domains:
            logger.info(f"Domain {domain} is in secure list, prioritizing Mailgun")
            provider_order = ['mailgun', 'smtp']
        else:
            logger.info(f"Domain {domain} is not in secure list, prioritizing SMTP")
            provider_order = ['smtp', 'mailgun']

        # Filter to only available providers
        available_order = [p for p in provider_order if p in self.providers]
        logger.info(f"Provider order for {email}: {available_order}")

        return available_order

    async def get_providers_status(self) -> Dict[str, bool]:
        """
        Get status of all providers.
        Used by admin testmail command.

        Returns:
            Dict mapping provider name to status (True if working)
        """
        status = {}

        for provider_name, provider in self.providers.items():
            try:
                if hasattr(provider, 'test_connection'):
                    status[provider_name] = await provider.test_connection()
                else:
                    status[provider_name] = False
            except Exception as e:
                logger.error(f"Error testing {provider_name}: {e}")
                status[provider_name] = False

        return status

    async def send_email(
            self,
            to: str,
            subject_template_key: str,
            body_template_key: str,
            variables: Dict[str, Any],
            lang: str = 'en'
    ) -> bool:
        """
        Universal method to send templated email.

        Args:
            to: Recipient email address
            subject_template_key: Template key for subject (from Google Sheets)
            body_template_key: Template key for body (from Google Sheets)
            variables: Variables for template substitution
            lang: Language code

        Returns:
            True if email sent successfully
        """
        if not self.providers:
            logger.error("No email providers configured")
            return False

        if not to:
            logger.error("Recipient email not provided")
            return False

        try:
            logger.info(
                f"Preparing email to {to} (templates: {subject_template_key}, {body_template_key}, lang: {lang})")

            # Get templates from Google Sheets
            subject_text, _ = await MessageTemplates.get_raw_template(
                subject_template_key,
                variables,
                lang=lang
            )

            body_html, _ = await MessageTemplates.get_raw_template(
                body_template_key,
                variables,
                lang=lang
            )

            logger.info(f"Templates loaded for language: {lang}")

            # Get provider order for this email
            provider_order = self._select_provider_for_email(to)

            if not provider_order:
                logger.error("No available providers for sending email")
                return False

            # Try providers in order
            for provider_name in provider_order:
                provider = self.providers[provider_name]

                logger.info(f"Attempting to send via {provider_name}...")

                success = await provider.send_email(
                    to=to,
                    subject=subject_text,
                    html_body=body_html,
                    text_body=None
                )

                if success:
                    logger.info(
                        f"✅ Email sent successfully "
                        f"to {to} via {provider_name}"
                    )
                    return True
                else:
                    logger.warning(
                        f"Failed to send via {provider_name}, "
                        f"trying next provider..."
                    )

            # All providers failed
            logger.error(f"❌ Failed to send email to {to} via all providers")
            return False

        except Exception as e:
            logger.error(f"Error sending email to {to}: {e}", exc_info=True)
            return False

    def can_resend_email(self, user: User, cooldown_minutes: int = 5) -> tuple[bool, int]:
        """
        Check if user can resend verification email (cooldown check).

        Args:
            user: User object
            cooldown_minutes: Cooldown period in minutes

        Returns:
            Tuple (can_send: bool, remaining_seconds: int)
        """
        if not user.emailVerification or 'sentAt' not in user.emailVerification:
            return True, 0

        try:
            sent_at_str = user.emailVerification['sentAt']
            sent_at = datetime.fromisoformat(sent_at_str.replace('Z', '+00:00'))

            now = datetime.now(timezone.utc)
            elapsed = (now - sent_at).total_seconds()
            cooldown_seconds = cooldown_minutes * 60

            if elapsed >= cooldown_seconds:
                return True, 0
            else:
                remaining = int(cooldown_seconds - elapsed)
                return False, remaining

        except Exception as e:
            logger.error(f"Error checking email cooldown: {e}")
            return True, 0  # Allow sending if error

    def get_config_info(self) -> Dict[str, any]:
        """
        Get email configuration info for admin commands.

        Returns:
            Dict with configuration details
        """
        return {
            'smtp': {
                'configured': 'smtp' in self.providers,
                'host': Config.get(Config.SMTP_HOST, 'Not configured'),
                'port': Config.get(Config.SMTP_PORT, 587),
            },
            'mailgun': {
                'configured': 'mailgun' in self.providers,
                'domain': Config.get(Config.MAILGUN_DOMAIN, 'Not configured'),
                'region': Config.get('MAILGUN_REGION', 'eu'),
            },
            'secure_domains': self.secure_domains,
            'providers_count': len(self.providers)
        }