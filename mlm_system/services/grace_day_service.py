# mlm_system/services/grace_day_service.py
"""
Grace Day bonus service - handles +5% bonus for purchases on 1st of month.
Prepares loyalty counter for future Loyalty Program implementation.
"""
from decimal import Decimal
from typing import Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
import logging

from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from models.option import Option
from models.active_balance import ActiveBalance
from mlm_system.utils.time_machine import timeMachine

logger = logging.getLogger(__name__)

# Constants
GRACE_DAY_BONUS_PERCENTAGE = Decimal("0.05")  # 5%
LOYALTY_STREAK_REQUIRED = 3  # For future Loyalty Program


class GraceDayService:
    """Service for processing Grace Day bonuses and loyalty tracking."""

    def __init__(self, session: Session):
        self.session = session

    async def processGraceDayBonus(self, purchase: Purchase) -> Optional[Dict]:
        """
        Process Grace Day bonus for a purchase.

        Rules:
        - Only applies if purchase made on 1st of month (Grace Day)
        - Grants +5% bonus in OPTIONS (not money)
        - Updates loyalty streak counter
        - Creates Bonus record + ActiveBalance transactions + auto-Purchase

        Transaction flow:
        1. Create Bonus record (tracking)
        2. ActiveBalance (+bonus_amount) - credit
        3. Create Purchase (auto-purchase options)
        4. ActiveBalance (-bonus_amount) - debit

        Args:
            purchase: Purchase object

        Returns:
            Dict with bonus info if granted, None otherwise
        """
        # Check if today is Grace Day
        if not timeMachine.isGraceDay:
            logger.debug(
                f"Purchase {purchase.purchaseID} not on Grace Day, "
                f"skipping bonus"
            )
            return None

        user = purchase.user
        if not user:
            logger.error(f"User not found for purchase {purchase.purchaseID}")
            return None

        logger.info(
            f"Processing Grace Day bonus for purchase {purchase.purchaseID} "
            f"(user {user.userID}, amount ${purchase.packPrice})"
        )

        # Calculate bonus amount (5% of purchase price)
        bonus_amount = Decimal(str(purchase.packPrice)) * GRACE_DAY_BONUS_PERCENTAGE

        # Get option to calculate bonus quantity
        option = self.session.query(Option).filter_by(
            optionID=purchase.optionID
        ).first()

        if not option:
            logger.error(
                f"Option {purchase.optionID} not found for purchase {purchase.purchaseID}"
            )
            return None

        # Calculate bonus options quantity
        price_per_option = Decimal(str(option.packPrice)) / Decimal(str(option.packQty))
        bonus_qty = int(bonus_amount / price_per_option)

        if bonus_qty <= 0:
            logger.warning(
                f"Bonus amount ${bonus_amount} too small to grant options "
                f"for purchase {purchase.purchaseID}"
            )
            return None

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Create Bonus record (tracking only)
        # ═══════════════════════════════════════════════════════════
        bonus = await self._createBonusRecord(user, purchase, bonus_amount, bonus_qty)

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Create auto-purchase (ActiveBalance + Purchase)
        # ═══════════════════════════════════════════════════════════
        await self._createAutoPurchase(user, purchase, bonus_amount, bonus_qty, bonus.bonusID)

        # ═══════════════════════════════════════════════════════════
        # STEP 3: Update loyalty streak counter
        # ═══════════════════════════════════════════════════════════
        await self._updateLoyaltyStreak(user)

        self.session.commit()

        logger.info(
            f"✓ Grace Day bonus completed: ${bonus_amount} "
            f"({bonus_qty} options) for user {user.userID}"
        )

        return {
            "success": True,
            "bonusID": bonus.bonusID,
            "bonusAmount": bonus_amount,
            "bonusQty": bonus_qty,
            "loyaltyStreak": user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        }

    async def _createBonusRecord(
            self,
            user: User,
            purchase: Purchase,
            bonus_amount: Decimal,
            bonus_qty: int
    ) -> Bonus:
        """
        Create Bonus record for tracking.
        This represents the company's gift to the user.

        Args:
            user: User receiving bonus
            purchase: Original purchase that triggered bonus
            bonus_amount: Amount to grant
            bonus_qty: Number of options

        Returns:
            Created Bonus object
        """
        bonus = Bonus()
        bonus.userID = user.userID
        bonus.downlineID = None  # Not a commission from downline
        bonus.purchaseID = purchase.purchaseID

        # Denormalized data
        bonus.projectID = purchase.projectID
        bonus.optionID = purchase.optionID
        bonus.packQty = bonus_qty
        bonus.packPrice = bonus_amount

        # MLM specific
        bonus.commissionType = "grace_day"
        bonus.uplineLevel = None
        bonus.fromRank = user.rank
        bonus.sourceRank = None
        bonus.bonusRate = float(GRACE_DAY_BONUS_PERCENTAGE)
        bonus.bonusAmount = bonus_amount
        bonus.compressionApplied = 0

        # Status
        bonus.status = "paid"
        bonus.notes = f"Grace Day bonus (+5%) - {bonus_qty} options"

        # AuditMixin
        bonus.ownerTelegramID = user.telegramID
        bonus.ownerEmail = user.email

        self.session.add(bonus)
        self.session.flush()  # Get bonusID

        logger.debug(f"Created bonus record: bonusID={bonus.bonusID}, amount=${bonus_amount}")

        return bonus

    async def _createAutoPurchase(
            self,
            user: User,
            original_purchase: Purchase,
            bonus_amount: Decimal,
            bonus_qty: int,
            bonus_id: int
    ):
        """
        Create automatic purchase using bonus money.

        Transaction flow:
        1. ActiveBalance (+bonus_amount) - bonus credit from company
        2. Create Purchase record - auto-purchase options
        3. ActiveBalance (-bonus_amount) - debit for purchase

        Net effect on user.balanceActive: 0 (credit and debit cancel out)
        But user gets OPTIONS added to their portfolio.

        Args:
            user: User receiving bonus
            original_purchase: Purchase that triggered the bonus
            bonus_amount: Bonus amount
            bonus_qty: Number of options to purchase
            bonus_id: ID of the Bonus record
        """
        logger.debug(
            f"Creating auto-purchase for user {user.userID}: "
            f"${bonus_amount}, {bonus_qty} options"
        )

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Create Purchase record (auto-purchase)
        # ═══════════════════════════════════════════════════════════
        auto_purchase = Purchase()
        auto_purchase.userID = user.userID
        auto_purchase.projectID = original_purchase.projectID
        auto_purchase.optionID = original_purchase.optionID
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

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Create ActiveBalance transaction records
        # ═══════════════════════════════════════════════════════════

        # Record 1: Bonus credited (+bonus_amount)
        bonus_credit = ActiveBalance()
        bonus_credit.userID = user.userID
        bonus_credit.firstname = user.firstname
        bonus_credit.surname = user.surname
        bonus_credit.amount = bonus_amount
        bonus_credit.status = 'done'
        bonus_credit.reason = f'bonus={bonus_id}'
        bonus_credit.link = ''
        bonus_credit.notes = 'Grace Day bonus (+5%) - auto-purchase credit'

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
        purchase_debit.notes = 'Grace Day bonus (+5%) - auto-purchase debit'

        self.session.add(purchase_debit)

        logger.info(
            f"✓ Grace Day auto-purchase completed: {bonus_qty} options worth ${bonus_amount} "
            f"for user {user.userID}"
        )

    async def _updateLoyaltyStreak(self, user: User):
        """
        Update user's Grace Day loyalty streak counter.

        Loyalty Program rules (for future implementation):
        - 3 months in a row purchasing on Grace Day → +10% JetUp Tokens
        - Missing Grace Day resets counter to 0

        Args:
            user: User object
        """
        current_month = timeMachine.currentMonth

        # Initialize mlmVolumes if needed
        if not user.mlmVolumes:
            user.mlmVolumes = {}

        last_grace_day_month = user.mlmVolumes.get("lastGraceDayMonth")
        current_streak = user.mlmVolumes.get("graceDayStreak", 0)

        # Check if this is consecutive month
        if last_grace_day_month:
            # Parse last month (format: "2025-01")
            last_year, last_month_num = map(int, last_grace_day_month.split("-"))
            current_year, current_month_num = map(int, current_month.split("-"))

            # Calculate if consecutive
            is_consecutive = False
            if current_year == last_year:
                is_consecutive = (current_month_num == last_month_num + 1)
            elif current_year == last_year + 1 and last_month_num == 12:
                is_consecutive = (current_month_num == 1)

            if is_consecutive:
                # Increment streak
                current_streak += 1
                logger.info(
                    f"User {user.userID} Grace Day streak: {current_streak} months"
                )
            else:
                # Reset streak (missed at least one month)
                logger.info(
                    f"User {user.userID} Grace Day streak reset "
                    f"(last: {last_grace_day_month}, current: {current_month})"
                )
                current_streak = 1
        else:
            # First Grace Day purchase
            current_streak = 1
            logger.info(f"User {user.userID} started Grace Day streak")

        # Update user data
        user.mlmVolumes["graceDayStreak"] = current_streak
        user.mlmVolumes["lastGraceDayMonth"] = current_month
        user.mlmVolumes["lastGraceDayPurchaseAt"] = timeMachine.now.isoformat()

        # Check if qualified for Loyalty bonus (for future implementation)
        if current_streak >= LOYALTY_STREAK_REQUIRED:
            user.mlmVolumes["loyaltyQualified"] = True
            logger.info(
                f"🎖️ User {user.userID} qualified for Loyalty Program "
                f"({current_streak} months streak)"
            )
        else:
            user.mlmVolumes["loyaltyQualified"] = False

        # Mark as modified for SQLAlchemy to detect changes
        flag_modified(user, "mlmVolumes")

    async def checkLoyaltyQualification(self, user_id: int) -> Dict:
        """
        Check user's loyalty qualification status.
        For future Loyalty Program implementation.

        Args:
            user_id: User ID

        Returns:
            Dict with streak info and qualification status
        """
        user = self.session.query(User).filter_by(userID=user_id).first()
        if not user:
            return {"success": False, "error": "User not found"}

        if not user.mlmVolumes:
            return {
                "success": True,
                "qualified": False,
                "streak": 0,
                "lastMonth": None
            }

        return {
            "success": True,
            "qualified": user.mlmVolumes.get("loyaltyQualified", False),
            "streak": user.mlmVolumes.get("graceDayStreak", 0),
            "lastMonth": user.mlmVolumes.get("lastGraceDayMonth"),
            "requiredStreak": LOYALTY_STREAK_REQUIRED
        }

    async def resetMonthlyStreaks(self):
        """
        Reset Grace Day streaks for users who didn't purchase on Grace Day.
        Should be called on 2nd of month by scheduler.

        This ensures that users who miss Grace Day get their streak reset.
        """
        current_month = timeMachine.currentMonth

        # Get all users with active streaks
        users = self.session.query(User).filter(
            User.mlmVolumes.isnot(None)
        ).all()

        reset_count = 0

        for user in users:
            if not user.mlmVolumes:
                continue

            last_grace_day_month = user.mlmVolumes.get("lastGraceDayMonth")
            current_streak = user.mlmVolumes.get("graceDayStreak", 0)

            # Skip if no streak
            if current_streak == 0:
                continue

            # Skip if already purchased this month
            if last_grace_day_month == current_month:
                continue

            # Reset streak (user missed Grace Day)
            logger.info(
                f"Resetting Grace Day streak for user {user.userID} "
                f"(missed {current_month})"
            )

            user.mlmVolumes["graceDayStreak"] = 0
            user.mlmVolumes["loyaltyQualified"] = False
            flag_modified(user, "mlmVolumes")

            reset_count += 1

        if reset_count > 0:
            self.session.commit()
            logger.info(f"Reset Grace Day streaks for {reset_count} users")

        return {
            "success": True,
            "resetsCount": reset_count
        }