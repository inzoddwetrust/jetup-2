# mlm_system/events/handlers.py
"""
Event handlers for MLM system.
Process events from the event bus.
"""
import logging
from typing import Dict, Any

from core.db import get_session
from models.purchase import Purchase
from models.user import User
from mlm_system.services.commission_service import CommissionService
from mlm_system.services.volume_service import VolumeService
from mlm_system.services.investment_bonus_service import InvestmentBonusService
from mlm_system.services.grace_day_service import GraceDayService

logger = logging.getLogger(__name__)


async def handle_purchase_completed(data: Dict[str, Any]):
    """
    Handle PURCHASE_COMPLETED event.

    This event triggers FIVE independent processes:
    1. Volume updates (PV, FV, TV with 50% rule)
    2. Pioneer Bonus eligibility check
    3. Grace Day bonus check (+5% if purchased on 1st)
    4. Investment bonus check and processing
    5. Commission calculations (differential, compression, bonuses)

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
        # STEP 1.5: Check and grant Pioneer Bonus status
        # ═══════════════════════════════════════════════════════════
        pioneer_granted = False
        try:
            pioneer_granted = await _check_pioneer_bonus_eligibility(session, purchase)
            if pioneer_granted:
                logger.info(f"✓ Pioneer Bonus status granted for purchase {purchase_id}")
        except Exception as e:
            logger.error(
                f"Error checking pioneer bonus eligibility for purchase {purchase_id}: {e}",
                exc_info=True
            )
            # Don't fail - continue

        # ═══════════════════════════════════════════════════════════
        # ✨ NEW STEP 2: Grace Day Bonus (+5% if purchased on 1st)
        # ═══════════════════════════════════════════════════════════
        grace_day_granted = False
        try:
            grace_day_service = GraceDayService(session)
            grace_result = await grace_day_service.processGraceDayBonus(purchase)

            if grace_result:
                grace_day_granted = True
                logger.info(
                    f"✓ Grace Day bonus granted for purchase {purchase_id}: "
                    f"+${grace_result['bonusAmount']} "
                    f"({grace_result['bonusQty']} options), "
                    f"loyalty streak: {grace_result['loyaltyStreak']} months"
                )
            else:
                logger.debug(f"Purchase {purchase_id} not eligible for Grace Day bonus")

        except Exception as e:
            logger.error(
                f"Error processing Grace Day bonus for purchase {purchase_id}: {e}",
                exc_info=True
            )
            # Don't return - continue to process other bonuses

        # ═══════════════════════════════════════════════════════════
        # STEP 3: Check and process investment bonus
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
        # STEP 4: Calculate and distribute MLM commissions
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
        # STEP 5: Send notifications to user
        # ═══════════════════════════════════════════════════════════

        # Send pioneer bonus notification if granted
        if pioneer_granted:
            try:
                await _send_pioneer_bonus_notification(session, purchase)
            except Exception as e:
                logger.error(
                    f"Error sending pioneer bonus notification: {e}",
                    exc_info=True
                )

        # ✨ NEW: Send Grace Day notification if granted
        if grace_day_granted:
            try:
                await _send_grace_day_notification(session, purchase)
            except Exception as e:
                logger.error(
                    f"Error sending grace day notification: {e}",
                    exc_info=True
                )

        # Send investment bonus notification if granted
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


async def _check_pioneer_bonus_eligibility(session, purchase: Purchase) -> bool:
    """
    Check if purchase qualifies for Pioneer Bonus status.

    Pioneer Bonus Rules (from TZ):
    - First 50 customers with investment ≥5,000$
    - Permanent +4% bonus on all future commissions
    - Global counter stored in DEFAULT_REFERRER.mlmStatus

    Args:
        session: Database session
        purchase: Purchase object

    Returns:
        True if Pioneer status was granted, False otherwise
    """
    from config import Config
    from mlm_system.config.ranks import PIONEER_MAX_COUNT
    from decimal import Decimal

    # Check minimum investment amount
    if purchase.packPrice < Decimal("5000"):
        logger.debug(
            f"Purchase {purchase.purchaseID} doesn't qualify for Pioneer Bonus "
            f"(amount ${purchase.packPrice} < $5000)"
        )
        return False

    user = purchase.user

    # Check if user already has pioneer status
    if user.mlmStatus and user.mlmStatus.get("hasPioneerBonus", False):
        logger.debug(f"User {user.userID} already has Pioneer Bonus status")
        return False

    # Get DEFAULT_REFERRER (root user) to check global counter
    default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)

    if not default_referrer_id:
        logger.error("DEFAULT_REFERRER_ID not configured, cannot check Pioneer Bonus")
        return False

    root_user = session.query(User).filter_by(
        telegramID=default_referrer_id
    ).first()

    if not root_user:
        logger.error(f"Root user {default_referrer_id} not found for Pioneer Bonus check")
        return False

    # Get global pioneer counter from root user
    root_mlm_status = root_user.mlmStatus or {}
    pioneer_count = root_mlm_status.get("pioneerPurchasesCount", 0)

    # Check if slots available
    if pioneer_count >= PIONEER_MAX_COUNT:
        logger.info(
            f"Pioneer Bonus slots full ({pioneer_count}/{PIONEER_MAX_COUNT}), "
            f"user {user.userID} not eligible"
        )
        return False

    # ✅ GRANT PIONEER STATUS

    # Update user status
    user_mlm_status = user.mlmStatus or {}
    user_mlm_status["hasPioneerBonus"] = True
    user_mlm_status["pioneerGrantedAt"] = purchase.createdAt.isoformat() if purchase.createdAt else None
    user_mlm_status["pioneerPurchaseId"] = purchase.purchaseID
    user.mlmStatus = user_mlm_status

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(user, 'mlmStatus')

    # Increment global counter
    root_mlm_status["pioneerPurchasesCount"] = pioneer_count + 1
    root_user.mlmStatus = root_mlm_status

    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(root_user, 'mlmStatus')

    session.commit()

    logger.info(
        f"🎖️ PIONEER BONUS GRANTED to user {user.userID} "
        f"(#{pioneer_count + 1}/{PIONEER_MAX_COUNT}) "
        f"for purchase ${purchase.packPrice}"
    )

    return True


async def _send_pioneer_bonus_notification(session, purchase: Purchase):
    """
    Send notification to user about Pioneer Bonus status.
    Uses Notification model for queued delivery.
    """
    from models.notification import Notification
    from core.templates import MessageTemplates
    from config import Config
    from mlm_system.config.ranks import PIONEER_MAX_COUNT

    try:
        user = purchase.user

        # Get pioneer count
        default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
        root_user = session.query(User).filter_by(
            telegramID=default_referrer_id
        ).first()

        pioneer_number = 0
        if root_user and root_user.mlmStatus:
            pioneer_number = root_user.mlmStatus.get("pioneerPurchasesCount", 0)

        # Get template
        text, buttons = await MessageTemplates.get_raw_template(
            '/mlm/pioneer_bonus_granted',
            {
                'purchase_amount': float(purchase.packPrice),
                'project_name': purchase.projectName or "JetUp",
                'pioneer_number': pioneer_number,
                'pioneer_max': PIONEER_MAX_COUNT,
                'bonus_percentage': 4.0
            },
            lang=user.lang or 'en'
        )

        # Create notification
        notification = Notification(
            source="mlm_system",
            text=text,
            buttons=buttons,
            targetType="user",
            targetValue=str(user.userID),
            priority=2,
            category="mlm",
            importance="high",
            parseMode="HTML"
        )

        session.add(notification)
        session.commit()

        logger.info(f"Pioneer bonus notification queued for user {user.userID}")

    except Exception as e:
        logger.error(f"Failed to create pioneer bonus notification: {e}", exc_info=True)


async def _send_grace_day_notification(session, purchase: Purchase):
    """
    Send notification to user about Grace Day bonus.
    Uses Notification model for queued delivery.
    """
    from models.notification import Notification
    from core.templates import MessageTemplates

    try:
        user = purchase.user

        # Get loyalty streak info
        loyalty_streak = 0
        if user.mlmVolumes:
            loyalty_streak = user.mlmVolumes.get("graceDayStreak", 0)

        # Get template
        text, buttons = await MessageTemplates.get_raw_template(
            '/mlm/grace_day_bonus_granted',
            {
                'purchase_amount': float(purchase.packPrice),
                'bonus_percentage': 5.0,
                'loyalty_streak': loyalty_streak,
                'loyalty_required': 3
            },
            lang=user.lang or 'en'
        )

        # Create notification
        notification = Notification(
            source="mlm_system",
            text=text,
            buttons=buttons,
            targetType="user",
            targetValue=str(user.userID),
            priority=2,
            category="mlm",
            importance="medium",
            parseMode="HTML"
        )

        session.add(notification)
        session.commit()

        logger.info(f"Grace Day bonus notification queued for user {user.userID}")

    except Exception as e:
        logger.error(f"Failed to create grace day notification: {e}", exc_info=True)


async def _send_investment_bonus_notification(
        session,
        purchase: Purchase,
        bonus_amount
):
    """
    Send notification to user about investment bonus.
    Uses Notification model for queued delivery.
    """
    from models.notification import Notification
    from core.templates import MessageTemplates
    from mlm_system.utils.investment_helpers import get_tier_info
    from mlm_system.services.investment_bonus_service import InvestmentBonusService

    try:
        user = purchase.user

        # Get tier information
        bonus_service = InvestmentBonusService(session)
        total_purchased = await bonus_service._calculateTotalPurchased(
            user.userID,
            purchase.projectID
        )
        tier_info = get_tier_info(total_purchased)

        # Format next tier info
        next_tier_vars = {}
        if tier_info.get('next_tier'):
            next_tier = tier_info['next_tier']
            next_tier_vars = {
                'has_next_tier': True,
                'next_threshold': next_tier['threshold'],
                'next_percentage': next_tier['bonus_percentage'],
                'amount_needed': next_tier['amount_needed']
            }
        else:
            next_tier_vars = {'has_next_tier': False}

        # Get template
        text, buttons = await MessageTemplates.get_raw_template(
            '/investment/bonus_granted',
            {
                'bonus_amount': float(bonus_amount),
                'project_name': purchase.projectName or "JetUp",
                'total_purchased': float(total_purchased),
                'tier_percentage': tier_info['current_tier']['bonus_percentage'],
                'total_bonus': tier_info['current_tier']['total_bonus'],
                **next_tier_vars
            },
            lang=user.lang or 'en'
        )

        # Create notification
        notification = Notification(
            source="mlm_system",
            text=text,
            buttons=buttons,
            targetType="user",
            targetValue=str(user.userID),
            priority=2,
            category="mlm",
            importance="high",
            parseMode="HTML"
        )

        session.add(notification)
        session.commit()

        logger.info(f"Investment bonus notification queued for user {user.userID}")

    except Exception as e:
        logger.error(f"Failed to create investment bonus notification: {e}", exc_info=True)