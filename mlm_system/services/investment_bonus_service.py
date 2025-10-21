# mlm_system/services/investment_bonus_service.py
"""
Investment bonus service.
Handles cumulative purchase bonuses with automatic reinvestment.
"""
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
import logging

from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from models.option import Option
from models.active_balance import ActiveBalance
from mlm_system.utils.investment_helpers import (
    calculate_expected_bonus,
    get_tier_info
)

logger = logging.getLogger(__name__)


class InvestmentBonusService:
    """
    Service for calculating and processing investment package bonuses.

    Business Logic:
    - Bonuses are calculated PER PROJECT (not total across all projects)
    - When user reaches a tier: bonus = (tier_percent * total) - already_granted
    - Bonus is immediately converted to automatic purchase of same project
    - All transactions are atomic to maintain balance consistency

    Example Flow:
    1. User buys $1000 of Project A (total: $1400)
    2. Tier reached: $1000 → 5%
    3. Expected bonus: $1400 * 0.05 = $70
    4. Already granted: $0
    5. New bonus: $70
    6. Auto-purchase: +$70 to Active Balance → Purchase $70 options
    """

    def __init__(self, session: Session):
        self.session = session

    async def processPurchaseBonus(self, purchase: Purchase) -> Optional[Decimal]:
        """
        Check if purchase triggers investment bonus and process it.

        This is called AFTER the main purchase is completed.

        Args:
            purchase: The purchase that was just made

        Returns:
            Bonus amount if granted, None otherwise
        """
        try:
            user = purchase.user
            project_id = purchase.projectID

            logger.info(
                f"Checking investment bonus for user {user.userID}, "
                f"project {project_id}, purchase ${purchase.packPrice}"
            )

            # Step 1: Calculate total purchased for this project
            total_purchased = await self._calculateTotalPurchased(user.userID, project_id)

            # Step 2: Calculate already granted bonuses
            already_granted = await self._calculateAlreadyGranted(user.userID, project_id)

            # Step 3: Determine if bonus should be granted
            bonus_amount = await self._determineBonus(total_purchased, already_granted)

            if bonus_amount <= 0:
                logger.debug(
                    f"No bonus for user {user.userID}: "
                    f"total=${total_purchased}, granted=${already_granted}"
                )
                return None

            logger.info(
                f"Investment bonus triggered: user={user.userID}, "
                f"total=${total_purchased}, already_granted=${already_granted}, "
                f"new_bonus=${bonus_amount}"
            )

            # Step 4: Create Bonus record (money from company)
            await self._createBonusRecord(user, purchase, bonus_amount)

            # Step 5: Create automatic purchase using bonus
            await self._createAutoPurchase(user, purchase, bonus_amount)

            logger.info(
                f"✓ Investment bonus processed: ${bonus_amount} for user {user.userID}"
            )

            return bonus_amount

        except Exception as e:
            logger.error(
                f"Error processing investment bonus for purchase {purchase.purchaseID}: {e}",
                exc_info=True
            )
            return None

    async def _calculateTotalPurchased(self, user_id: int, project_id: int) -> Decimal:
        """
        Get total amount purchased for this project by user.
        Includes both regular purchases and bonus auto-purchases.

        Args:
            user_id: User ID
            project_id: Project ID

        Returns:
            Total amount purchased
        """
        total = self.session.query(
            func.sum(Purchase.packPrice)
        ).filter(
            Purchase.userID == user_id,
            Purchase.projectID == project_id
        ).scalar()

        return total or Decimal("0")

    async def _calculateAlreadyGranted(self, user_id: int, project_id: int) -> Decimal:
        """
        Get total bonuses already granted for this project.

        Args:
            user_id: User ID
            project_id: Project ID

        Returns:
            Total bonus amount already granted
        """
        granted = self.session.query(
            func.sum(Bonus.bonusAmount)
        ).filter(
            Bonus.userID == user_id,
            Bonus.projectID == project_id,
            Bonus.commissionType == "investment_package"
        ).scalar()

        return granted or Decimal("0")

    async def _determineBonus(
            self,
            total_purchased: Decimal,
            already_granted: Decimal
    ) -> Decimal:
        """
        Calculate bonus amount based on tiers.

        Logic:
        - Calculate expected total bonus for current total_purchased
        - Subtract already_granted
        - If positive → grant the difference

        Args:
            total_purchased: Total amount purchased
            already_granted: Total bonus already granted

        Returns:
            Bonus amount to grant (0 if no bonus)

        Example:
            total_purchased = $5000
            already_granted = $200 (from 4x $1000 tiers)
            expected = $5000 * 0.10 = $500
            bonus = $500 - $200 = $300
        """
        # Calculate expected total bonus at this purchase level
        expected_total = calculate_expected_bonus(total_purchased)

        # Calculate new bonus (difference)
        new_bonus = expected_total - already_granted

        # Round to 2 decimal places
        new_bonus = new_bonus.quantize(Decimal("0.01"))

        if new_bonus > 0:
            logger.debug(
                f"Bonus calculation: total=${total_purchased}, "
                f"expected=${expected_total}, granted=${already_granted}, "
                f"new=${new_bonus}"
            )

        return max(new_bonus, Decimal("0"))

    async def _createBonusRecord(
            self,
            user: User,
            original_purchase: Purchase,
            bonus_amount: Decimal
    ):
        """
        Create Bonus record (money from company).

        This represents the company's gift to the user.

        Args:
            user: User receiving bonus
            original_purchase: Purchase that triggered the bonus
            bonus_amount: Amount to grant
        """
        # Get tier info for notes
        total_purchased = await self._calculateTotalPurchased(
            user.userID,
            original_purchase.projectID
        )
        tier_info = get_tier_info(total_purchased)

        # Create bonus record
        bonus = Bonus()
        bonus.userID = user.userID
        bonus.downlineID = None  # No downline, this is company gift
        bonus.purchaseID = original_purchase.purchaseID

        # Denormalized data
        bonus.projectID = original_purchase.projectID
        bonus.optionID = original_purchase.optionID
        bonus.packQty = None  # Will be set in auto-purchase
        bonus.packPrice = bonus_amount

        # MLM specific
        bonus.commissionType = "investment_package"
        bonus.uplineLevel = None
        bonus.fromRank = user.rank
        bonus.sourceRank = None
        bonus.bonusRate = float(tier_info["current_tier"]["bonus_percentage"] / 100)
        bonus.bonusAmount = bonus_amount
        bonus.compressionApplied = 0

        # Status
        bonus.status = "paid"
        bonus.notes = (
            f"Investment bonus: ${total_purchased} tier "
            f"({tier_info['current_tier']['bonus_percentage']:.1f}% cumulative)"
        )

        # AuditMixin fields
        bonus.ownerTelegramID = user.telegramID
        bonus.ownerEmail = user.email

        self.session.add(bonus)
        self.session.flush()  # Get bonusID

        logger.debug(f"Created bonus record: bonusID={bonus.bonusID}, amount=${bonus_amount}")

    async def _createAutoPurchase(
            self,
            user: User,
            original_purchase: Purchase,
            bonus_amount: Decimal
    ):
        """
        Create automatic purchase using bonus money.

        Transaction flow:
        1. +bonus_amount to Active Balance (from Bonus - company money)
        2. -bonus_amount from Active Balance (to Purchase)
        3. Create Purchase record
        4. Create ActiveBalance transaction records

        Args:
            user: User receiving auto-purchase
            original_purchase: Original purchase (for project info)
            bonus_amount: Amount to spend on auto-purchase
        """
        project_id = original_purchase.projectID

        # ═══════════════════════════════════════════════════════════════════
        # STEP 1: Calculate option quantity at base price
        # ═══════════════════════════════════════════════════════════════════

        # Get cheapest (first) option for this project to determine base price
        first_option = self.session.query(Option).filter(
            Option.projectID == project_id,
            Option.isActive == True
        ).order_by(Option.packPrice.asc()).first()

        if not first_option:
            logger.error(f"No active options found for project {project_id}")
            raise ValueError(f"No active options for project {project_id}")

        # Calculate price per option (base price without bulk discounts)
        price_per_option = Decimal(str(first_option.packPrice)) / Decimal(str(first_option.packQty))

        # Calculate quantity for bonus amount
        bonus_qty = int(bonus_amount / price_per_option)

        if bonus_qty <= 0:
            logger.warning(f"Bonus amount ${bonus_amount} too small for project {project_id}")
            return

        logger.debug(
            f"Auto-purchase calculation: ${bonus_amount} / ${price_per_option} = {bonus_qty} options"
        )

        # ═══════════════════════════════════════════════════════════════════
        # STEP 2: Update user's Active Balance (bonus in, purchase out)
        # ═══════════════════════════════════════════════════════════════════

        # Net effect is 0, but we record both transactions for audit trail
        # No actual change needed to user.balanceActive

        # ═══════════════════════════════════════════════════════════════════
        # STEP 3: Create Purchase record
        # ═══════════════════════════════════════════════════════════════════

        auto_purchase = Purchase()
        auto_purchase.userID = user.userID
        auto_purchase.projectID = project_id
        auto_purchase.optionID = first_option.optionID
        auto_purchase.projectName = original_purchase.projectName
        auto_purchase.packQty = bonus_qty
        auto_purchase.packPrice = bonus_amount

        # AuditMixin fields
        auto_purchase.ownerTelegramID = user.telegramID
        auto_purchase.ownerEmail = user.email

        self.session.add(auto_purchase)
        self.session.flush()  # Get purchaseID

        logger.debug(
            f"Created auto-purchase: purchaseID={auto_purchase.purchaseID}, "
            f"qty={bonus_qty}, price=${bonus_amount}"
        )

        # ═══════════════════════════════════════════════════════════════════
        # STEP 4: Create ActiveBalance transaction records
        # ═══════════════════════════════════════════════════════════════════

        # Record 1: Bonus credited (+bonus_amount)
        bonus_credit = ActiveBalance()
        bonus_credit.userID = user.userID
        bonus_credit.firstname = user.firstname
        bonus_credit.surname = user.surname
        bonus_credit.amount = bonus_amount
        bonus_credit.status = 'done'
        bonus_credit.reason = f'purchase={auto_purchase.purchaseID}'
        bonus_credit.link = ''
        bonus_credit.notes = 'Investment bonus auto-purchase (credit)'

        self.session.add(bonus_credit)

        # Record 2: Purchase debit (-bonus_amount)
        purchase_debit = ActiveBalance()
        purchase_debit.userID = user.userID
        purchase_debit.firstname = user.firstname
        purchase_debit.surname = user.surname
        purchase_debit.amount = -bonus_amount
        purchase_debit.status = 'done'
        purchase_debit.reason = f'purchase={auto_purchase.purchaseID}'
        purchase_debit.link = ''
        purchase_debit.notes = 'Investment bonus auto-purchase (debit)'

        self.session.add(purchase_debit)

        logger.info(
            f"✓ Auto-purchase completed: {bonus_qty} options worth ${bonus_amount} "
            f"for user {user.userID}"
        )