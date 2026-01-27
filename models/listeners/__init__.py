"""
SQLAlchemy Event Listeners Package.

Registers all event listeners for the application.
Import this module once during app startup to activate listeners.

Listeners:
    - balance_listeners: Sync User.balanceActive/Passive on journal changes
"""
import logging

logger = logging.getLogger(__name__)

_listeners_registered = False


def register_all_listeners():
    """
    Register all event listeners.

    Safe to call multiple times - listeners are registered only once.

    Call this from application startup, e.g.:
        from models.listeners import register_all_listeners
        register_all_listeners()
    """
    global _listeners_registered

    if _listeners_registered:
        logger.debug("Listeners already registered, skipping")
        return

    # Balance sync listeners
    from models.listeners.balance_listeners import (
        register_balance_listeners,
        register_balance_protection
    )

    register_balance_listeners()
    logger.info("Balance sync listeners registered (ActiveBalance, PassiveBalance)")

    register_balance_protection()
    logger.info("Balance protection listeners registered (direct modification warnings)")

    _listeners_registered = True
    logger.info("All event listeners registered successfully")