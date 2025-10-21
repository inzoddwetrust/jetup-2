# mlm_system/events/handlers.py
"""
Event handlers for MLM system.
Process events from the event bus.
"""
import logging
from typing import Dict, Any

from core.db import get_session
from models.purchase import Purchase
from mlm_system.services.commission_service import CommissionService
from mlm_system.services.volume_service import VolumeService
from mlm_system.services.investment_bonus_service import InvestmentBonusService

logger = logging.getLogger(__name__)


async def handle_purchase_completed(data: Dict[str, Any]):
    """
    Handle PURCHASE_COMPLETED event.

    This event triggers THREE independent processes:
    1. Volume updates (PV, FV, TV with 50% rule)
    2. Investment bonus check and processing
    3. Commission calculations (differential, compression, bonuses)

    Args:
        data: Event data with 'purchaseId' key
    """
    purchase_id = data.get("purchaseId")

    if not purchase_id:
        logger.error("PURCHASE_COMPLETED event missing purchaseId")
        return

    logger.info(f"Processing MLM for purchase {purchase_id}")

    session = get_session()

    try:
        # Get purchase object
        purchase = session.query(Purchase).filter_by(
            purchaseID=purchase_id
        ).first()

        if not purchase:
            logger.error(f"Purchase {purchase_id} not found")
            return

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Update volumes (PV, FV, queue TV recalculation)
        # ═══════════════════════════════════════════════════════════
        try:
            volume_service = VolumeService(session)
            await volume_service.updatePurchaseVolumes(purchase)
            logger.info(f"✓ Volumes updated for purchase {purchase_id}")
        except Exception as e:
            logger.error(
                f"Error updating volumes for purchase {purchase_id}: {e}",
                exc_info=True
            )
            # Don't return - continue to process bonuses

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Check and process investment bonus
        # ═══════════════════════════════════════════════════════════
        investment_bonus_amount = None
        try:
            bonus_service = InvestmentBonusService(session)
            investment_bonus_amount = await bonus_service.processPurchaseBonus(purchase)

            if investment_bonus_amount:
                logger.info(
                    f"✓ Investment bonus processed: ${investment_bonus_amount} "
                    f"for purchase {purchase_id}"
                )
            else:
                logger.debug(f"No investment bonus for purchase {purchase_id}")

        except Exception as e:
            logger.error(
                f"Error processing investment bonus for purchase {purchase_id}: {e}",
                exc_info=True
            )
            # Don't return - continue to process commissions

        # ═══════════════════════════════════════════════════════════
        # STEP 3: Calculate and distribute MLM commissions
        # ═══════════════════════════════════════════════════════════
        try:
            commission_service = CommissionService(session)
            result = await commission_service.processPurchase(purchase_id)

            if result.get("success"):
                logger.info(
                    f"✓ MLM commissions processed for purchase {purchase_id}: "
                    f"{len(result.get('commissions', []))} commissions, "
                    f"total ${result.get('totalDistributed', 0)}"
                )
            else:
                logger.error(
                    f"✗ MLM commission processing failed for purchase {purchase_id}: "
                    f"{result.get('error', 'Unknown error')}"
                )
        except Exception as e:
            logger.error(
                f"Error processing commissions for purchase {purchase_id}: {e}",
                exc_info=True
            )
            # Don't return - we already processed volumes and bonuses

        # ═══════════════════════════════════════════════════════════
        # STEP 4: Send notification to user if bonus was granted
        # ═══════════════════════════════════════════════════════════
        if investment_bonus_amount:
            try:
                await _send_investment_bonus_notification(
                    session,
                    purchase,
                    investment_bonus_amount
                )
            except Exception as e:
                logger.error(
                    f"Error sending investment bonus notification: {e}",
                    exc_info=True
                )
                # Don't fail the whole process if notification fails

        # Commit all changes
        session.commit()

        logger.info(f"✓ MLM processing complete for purchase {purchase_id}")

    except Exception as e:
        logger.error(
            f"Critical error in MLM processing for purchase {purchase_id}: {e}",
            exc_info=True
        )
        session.rollback()

    finally:
        session.close()


async def _send_investment_bonus_notification(
        session,
        purchase: Purchase,
        bonus_amount
):
    """
    Send notification to user about investment bonus.

    This is a "silent" notification - just informing about the gift.
    Does NOT trigger any further MLM processing.

    Args:
        session: Database session
        purchase: Original purchase that triggered bonus
        bonus_amount: Bonus amount granted
    """
    from core.di import get_service
    from core.message_manager import MessageManager
    from mlm_system.utils.investment_helpers import get_tier_info
    from models.user import User

    try:
        user = purchase.user

        # Get tier information for display
        from mlm_system.services.investment_bonus_service import InvestmentBonusService
        bonus_service = InvestmentBonusService(session)
        total_purchased = await bonus_service._calculateTotalPurchased(
            user.userID,
            purchase.projectID
        )
        tier_info = get_tier_info(total_purchased)

        # Get message manager from DI
        message_manager = get_service(MessageManager)

        if not message_manager:
            logger.warning("MessageManager not available for notification")
            return

        # Send notification
        await message_manager.send_template(
            user=user,
            template_key='/investment/bonus_granted',
            variables={
                'bonus_amount': float(bonus_amount),
                'project_name': purchase.projectName,
                'total_purchased': float(total_purchased),
                'tier_percentage': tier_info['current_tier']['bonus_percentage'],
                'total_bonus': tier_info['current_tier']['total_bonus'],
                'next_tier': tier_info.get('next_tier')
            }
        )

        logger.info(f"Investment bonus notification sent to user {user.userID}")

    except Exception as e:
        logger.error(f"Failed to send investment bonus notification: {e}", exc_info=True)
        # Don't raise - notification failure shouldn't break the flow