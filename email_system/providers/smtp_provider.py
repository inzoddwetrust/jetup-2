# jetup/email_system/providers/smtp_provider.py
"""
SMTP email provider using aiosmtplib.
"""
import logging
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


class SMTPProvider:
    """SMTP provider for general email domains."""

    def __init__(self, host: str, port: int, username: str, password: str):
        """
        Initialize SMTP provider.

        Args:
            host: SMTP server host
            port: SMTP server port
            username: SMTP username
            password: SMTP password
        """
        self.smtp_host = host
        self.smtp_port = port
        self.username = username
        self.password = password

        logger.info(f"SMTPProvider initialized: {host}:{port}")

    async def send_email(
            self,
            to: str,
            subject: str,
            html_body: str,
            text_body: str = None
    ) -> bool:
        """
        Send email via SMTP.

        Args:
            to: Recipient email
            subject: Email subject
            html_body: HTML body
            text_body: Plain text body (optional)

        Returns:
            True if sent successfully
        """
        try:
            logger.info(f"Sending email via SMTP to {to}")

            # Create message
            message = MIMEMultipart('alternative')
            message['From'] = f"JETUP <{self.username}>"
            message['To'] = to
            message['Subject'] = subject

            # Add text part if provided
            if text_body:
                text_part = MIMEText(text_body, 'plain', 'utf-8')
                message.attach(text_part)

            # Add HTML part
            html_part = MIMEText(html_body, 'html', 'utf-8')
            message.attach(html_part)

            # Send via aiosmtplib
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.username,
                password=self.password,
                start_tls=True,
                use_tls=False,
                timeout=30,
                validate_certs=False
            )

            logger.info(f"✅ Email sent successfully via SMTP to {to}")
            return True

        except aiosmtplib.SMTPException as e:
            logger.error(f"SMTP error while sending email to {to}: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error while sending email via SMTP to {to}: {e}")
            logger.exception("Full traceback:")
            return False

    async def test_connection(self) -> bool:
        """
        Test connection to SMTP server.

        Returns:
            True if connection successful
        """
        try:
            logger.info(f"Testing SMTP connection to {self.smtp_host}:{self.smtp_port}")

            # Create test message
            test_message = MIMEText("Test", 'plain', 'utf-8')
            test_message['From'] = f"Test <{self.username}>"
            test_message['To'] = "test@example.com"
            test_message['Subject'] = "Connection test"

            # Try to connect and authenticate
            await aiosmtplib.send(
                test_message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.username,
                password=self.password,
                start_tls=True,
                use_tls=False,
                timeout=10,
                validate_certs=False
            )

            logger.info("SMTP connection test successful")
            return True

        except aiosmtplib.SMTPRecipientsRefused:
            # This is expected - we use fake recipient
            logger.info("SMTP connection test successful (recipients refused as expected)")
            return True
        except Exception as e:
            # If error is about recipient, not connection - consider success
            if "recipient" in str(e).lower():
                logger.info("SMTP connection test successful (recipient error ignored)")
                return True

            logger.error(f"SMTP connection test failed: {e}")
            return False