# jetup/email_system/__init__.py
"""
Email system for JETUP bot.
Handles email verification and notifications.
"""
import logging

from email_system.services.email_service import EmailService

logger = logging.getLogger(__name__)

__all__ = ['EmailService']