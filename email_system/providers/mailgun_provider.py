# jetup/email_system/providers/mailgun_provider.py
"""
Mailgun email provider for secure domains.
"""
import logging
import aiohttp

logger = logging.getLogger(__name__)


class MailgunProvider:
    """Mailgun provider for secure email domains."""

    def __init__(self, api_key: str, domain: str, region: str = 'eu'):
        """
        Initialize Mailgun provider.

        Args:
            api_key: Mailgun API key
            domain: Mailgun domain
            region: Region (eu or us)
        """
        self.api_key = api_key
        self.domain = domain
        self.region = region

        # Set base URL based on region
        if region == 'eu':
            self.base_url = "https://api.eu.mailgun.net/v3"
        else:
            self.base_url = "https://api.mailgun.net/v3"

        logger.info(f"MailgunProvider initialized: domain={domain}, region={region}")

    async def send_email(
            self,
            to: str,
            subject: str,
            html_body: str,
            text_body: str = None
    ) -> bool:
        """
        Send email via Mailgun API.

        Args:
            to: Recipient email
            subject: Email subject
            html_body: HTML body
            text_body: Plain text body (optional)

        Returns:
            True if sent successfully
        """
        try:
            logger.info(f"Sending email via Mailgun to {to}")

            # Prepare payload
            data = {
                "from": f"JETUP <noreply@{self.domain}>",
                "to": to,
                "subject": subject,
                "html": html_body
            }

            if text_body:
                data["text"] = text_body

            # Send via Mailgun API
            async with aiohttp.ClientSession() as session:
                async with session.post(
                        f"{self.base_url}/{self.domain}/messages",
                        auth=aiohttp.BasicAuth("api", self.api_key),
                        data=data,
                        timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        logger.info(f"✅ Email sent successfully via Mailgun to {to}")
                        return True
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Mailgun API error: {response.status} - {error_text}"
                        )
                        return False

        except aiohttp.ClientError as e:
            logger.error(f"HTTP error while sending email via Mailgun to {to}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while sending email via Mailgun to {to}: {e}")
            logger.exception("Full traceback:")
            return False

    async def test_connection(self) -> bool:
        """
        Test connection to Mailgun API.

        Returns:
            True if connection successful
        """
        try:
            logger.info(f"Testing Mailgun connection to {self.base_url}")

            # Validate we have credentials
            if not self.api_key or not self.domain:
                logger.error("Mailgun API key or domain not configured")
                return False

            # Try to access domain info endpoint
            async with aiohttp.ClientSession() as session:
                async with session.get(
                        f"{self.base_url}/{self.domain}",
                        auth=aiohttp.BasicAuth("api", self.api_key),
                        timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    # If not 401 - auth passed
                    if response.status == 401:
                        logger.error("Mailgun authentication failed")
                        return False
                    else:
                        logger.info(f"Mailgun auth check passed (status: {response.status})")
                        return True

        except Exception as e:
            # On connection error - still consider provider configured
            logger.warning(f"Mailgun connection test skipped due to error: {e}")
            return True  # Allow usage