# jetup/email_system/providers/__init__.py
"""
Email providers for JETUP bot.
"""
from email_system.providers.smtp_provider import SMTPProvider
from email_system.providers.mailgun_provider import MailgunProvider

__all__ = ['SMTPProvider', 'MailgunProvider']