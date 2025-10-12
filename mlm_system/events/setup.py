# mlm_system/events/setup.py
"""
Setup MLM event handlers.
Register all event handlers with the event bus.
"""
import logging

from mlm_system.events.event_bus import eventBus, MLMEvents
from mlm_system.events.handlers import handle_purchase_completed

logger = logging.getLogger(__name__)


def setup_mlm_event_handlers():
    """
    Register all MLM event handlers with the event bus.

    This function should be called during bot initialization.
    """
    logger.info("Setting up MLM event handlers...")

    # Register purchase completed handler
    eventBus.subscribe(MLMEvents.PURCHASE_COMPLETED, handle_purchase_completed)
    logger.debug(f"Registered handler for {MLMEvents.PURCHASE_COMPLETED}")

    # TODO: Add more event handlers as needed:
    # eventBus.subscribe(MLMEvents.MONTH_ENDED, handle_month_ended)
    # eventBus.subscribe(MLMEvents.RANK_ACHIEVED, handle_rank_achieved)

    logger.info("MLM event handlers registered successfully")


def teardown_mlm_event_handlers():
    """
    Unregister all MLM event handlers.
    Useful for testing or shutdown.
    """
    logger.info("Tearing down MLM event handlers...")

    eventBus.unsubscribe(MLMEvents.PURCHASE_COMPLETED, handle_purchase_completed)

    logger.info("MLM event handlers unregistered")