# mlm_system/events/handlers.py
"""
Event handlers for MLM system.
Process events from the event bus.
"""
import logging
from typing import Dict, Any

from core.db import get_session
from mlm_system.services.commission_service import CommissionService

logger = logging.getLogger(__name__)


async def handle_purchase_completed(data: Dict[str, Any]):
    """
    Handle PURCHASE_COMPLETED event.
    Process all MLM commissions for the purchase.

    Args:
        data: Event data with 'purchaseId' key
    """
    purchase_id = data.get("purchaseId")

    if not purchase_id:
        logger.error("PURCHASE_COMPLETED event missing purchaseId")
        return

    logger.info(f"Processing MLM commissions for purchase {purchase_id}")

    session = get_session()

    try:
        # Create commission service and process purchase
        commission_service = CommissionService(session)
        result = await commission_service.processPurchase(purchase_id)

        # Commit all changes
        session.commit()

        if result.get("success"):
            logger.info(
                f"MLM processing complete for purchase {purchase_id}: "
                f"{len(result.get('commissions', []))} commissions, "
                f"total ${result.get('totalDistributed', 0)}"
            )
        else:
            logger.error(
                f"MLM processing failed for purchase {purchase_id}: "
                f"{result.get('error', 'Unknown error')}"
            )

    except Exception as e:
        logger.error(
            f"Error processing MLM for purchase {purchase_id}: {e}",
            exc_info=True
        )
        session.rollback()

    finally:
        session.close()