# mlm_system/services/commission_service.py
"""
Commission calculation service - handles MLM differential commissions.
"""
from decimal import Decimal
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
import logging

from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from models.active_balance import ActiveBalance
from models.option import Option
from mlm_system.config.ranks import (
    RANK_CONFIG,
    Rank,
    PIONEER_BONUS_PERCENTAGE,
    REFERRAL_BONUS_PERCENTAGE,
    REFERRAL_BONUS_MIN_AMOUNT,
)

logger = logging.getLogger(__name__)


class CommissionService:
    """Service for calculating MLM commissions."""

    def __init__(self, session: Session):
        self.session = session

    async def processPurchase(self, purchaseId: int) -> Dict:
        """
        Process all commissions for a purchase.
        Main entry point replacing process_purchase_bonuses.
        """
        purchase = self.session.query(Purchase).filter_by(
            purchaseID=purchaseId
        ).first()

        if not purchase:
            logger.error(f"Purchase {purchaseId} not found")
            return {"success": False, "error": "Purchase not found"}

        results = {
            "success": True,
            "purchase": purchaseId,
            "commissions": [],
            "totalDistributed": Decimal("0")
        }

        # 1. Calculate differential commissions (includes compression to root)
        commissions = await self._calculateDifferentialCommissions(purchase)

        # 2. Apply Pioneer Bonus if applicable
        pioneeredCommissions = await self._applyPioneerBonus(
            commissions,
            purchase
        )

        # 3. Save all commissions to database
        for commission in pioneeredCommissions:
            await self._saveCommission(commission, purchase)
            results["totalDistributed"] += commission["amount"]
            results["commissions"].append(commission)

        # 4. Process referral bonus if applicable
        referralBonus = await self.processReferralBonus(purchase)
        if referralBonus:
            results["commissions"].append(referralBonus)
            results["totalDistributed"] += referralBonus["amount"]

        logger.info(
            f"Processed purchase {purchaseId}: "
            f"{len(results['commissions'])} commissions, "
            f"total {results['totalDistributed']}"
        )

        return results

    async def _calculateDifferentialCommissions(
            self,
            purchase: Purchase
    ) -> List[Dict]:
        """
        Calculate differential commissions up the chain.
        Uses ChainWalker for safe upline traversal.
        Accumulates compression and sends remainder to ROOT.
        """
        from mlm_system.utils.chain_walker import ChainWalker

        commissions = []
        lastPercentage = Decimal("0")
        accumulated_compression = Decimal("0")

        walker = ChainWalker(self.session)

        def process_upline(upline_user: User, level: int) -> bool:
            """Process each upline user for commission calculation."""
            nonlocal lastPercentage, accumulated_compression

            # Get user percentage
            userPercentage = self._getUserRankPercentage(upline_user)
            differential = userPercentage - lastPercentage

            # Check if upline is active
            if not upline_user.isActive:
                # Accumulate for compression
                if differential > 0:
                    accumulated_compression += differential

                commissions.append({
                    "userId": upline_user.userID,
                    "percentage": differential,
                    "amount": Decimal("0"),
                    "level": level,
                    "rank": upline_user.rank,
                    "isActive": False,
                    "compressed": True
                })

                logger.debug(
                    f"Compressing inactive user {upline_user.userID}, "
                    f"accumulating {float(differential * 100):.1f}%"
                )
            else:
                # Active user - gets their differential + accumulated compression
                if differential > 0 or accumulated_compression > 0:
                    total_percentage = differential + accumulated_compression
                    amount = Decimal(str(purchase.packPrice)) * total_percentage

                    commissions.append({
                        "userId": upline_user.userID,
                        "percentage": total_percentage,
                        "amount": amount,
                        "level": level,
                        "rank": upline_user.rank,
                        "isActive": True,
                        "compressed": False
                    })

                    if accumulated_compression > 0:
                        logger.info(
                            f"User {upline_user.userID} receives compression: "
                            f"+{float(accumulated_compression * 100):.1f}% "
                            f"(total {float(total_percentage * 100):.1f}%)"
                        )

                    lastPercentage = userPercentage
                    accumulated_compression = Decimal("0")  # Reset after distribution

            # Stop at max percentage
            if lastPercentage >= Decimal("0.18"):
                return False  # Stop walking

            return True  # Continue walking

        # Walk up the chain safely
        walker.walk_upline(purchase.user, process_upline)

        # ═══════════════════════════════════════════════════════════════════
        # CRITICAL: Send remaining commission to ROOT (system wallet)
        # ═══════════════════════════════════════════════════════════════════
        if accumulated_compression > 0 or lastPercentage < Decimal("0.18"):
            default_ref_id = walker.get_default_referrer_id()
            root_user = self.session.query(User).filter_by(
                telegramID=default_ref_id
            ).first()

            if root_user:
                # Calculate remaining percentage up to 18%
                remaining_percentage = Decimal("0.18") - lastPercentage
                total_to_root = accumulated_compression + remaining_percentage

                if total_to_root > 0:
                    amount = Decimal(str(purchase.packPrice)) * total_to_root

                    commissions.append({
                        "userId": root_user.userID,
                        "percentage": total_to_root,
                        "amount": amount,
                        "level": len(commissions) + 1,
                        "rank": root_user.rank,
                        "isActive": True,  # Root is ALWAYS treated as active
                        "compressed": False,
                        "isSystemRoot": True  # Mark as system commission
                    })

                    logger.info(
                        f"System commission to root user {root_user.userID}: "
                        f"${amount} ({float(total_to_root * 100):.1f}% - "
                        f"compression: {float(accumulated_compression * 100):.1f}%, "
                        f"remaining: {float(remaining_percentage * 100):.1f}%)"
                    )

        return commissions

    async def _applyPioneerBonus(
            self,
            commissions: List[Dict],
            purchase: Purchase
    ) -> List[Dict]:
        """
        Apply Pioneer Bonus (+4%) for users with pioneer status.

        Pioneer status is granted globally to first 50 customers with ≥5000$ investment.
        This is a PERMANENT bonus that applies to ALL their future commissions.
        """
        pioneeredCommissions = []

        for commission in commissions:
            user = self.session.query(User).filter_by(
                userID=commission["userId"]
            ).first()

            if not user:
                pioneeredCommissions.append(commission)
                continue

            # Check if user has pioneer status
            if user.mlmStatus and user.mlmStatus.get("hasPioneerBonus", False):
                # Add 4% bonus
                pioneer_amount = Decimal(str(purchase.packPrice)) * PIONEER_BONUS_PERCENTAGE
                commission["pioneerBonus"] = pioneer_amount
                commission["amount"] += pioneer_amount

                logger.info(
                    f"Pioneer bonus +${pioneer_amount} applied for user {user.userID} "
                    f"on purchase {purchase.purchaseID}"
                )

            pioneeredCommissions.append(commission)

        return pioneeredCommissions

    async def processReferralBonus(self, purchase: Purchase) -> Optional[Dict]:
        """
        Process Referral Bonus (1% for ≥5000$ purchases).

        Grants bonus in OPTIONS (not money).
        Transaction flow:
        1. Create Bonus record
        2. ActiveBalance (+bonus_amount) - credit
        3. Create Purchase (auto-purchase options)
        4. ActiveBalance (-bonus_amount) - debit
        """
        if purchase.packPrice < REFERRAL_BONUS_MIN_AMOUNT:
            return None

        user = purchase.user
        if not user.upline:
            return None

        upline_user = self.session.query(User).filter_by(
            telegramID=user.upline
        ).first()

        if not upline_user or not upline_user.isActive:
            return None

        bonus_amount = Decimal(str(purchase.packPrice)) * REFERRAL_BONUS_PERCENTAGE

        # Get option to calculate bonus quantity
        option = self.session.query(Option).filter_by(
            optionID=purchase.optionID
        ).first()

        if not option:
            logger.error(
                f"Option {purchase.optionID} not found for referral bonus "
                f"(purchase {purchase.purchaseID})"
            )
            return None

        # Calculate bonus options quantity
        price_per_option = Decimal(str(option.packPrice)) / Decimal(str(option.packQty))
        bonus_qty = int(bonus_amount / price_per_option)

        if bonus_qty <= 0:
            logger.warning(
                f"Referral bonus amount ${bonus_amount} too small to grant options "
                f"for purchase {purchase.purchaseID}"
            )
            return None

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Create Bonus record (tracking)
        # ═══════════════════════════════════════════════════════════
        bonus = Bonus()
        bonus.userID = upline_user.userID
        bonus.downlineID = user.userID
        bonus.purchaseID = purchase.purchaseID
        bonus.projectID = purchase.projectID
        bonus.optionID = purchase.optionID
        bonus.packQty = bonus_qty
        bonus.packPrice = bonus_amount
        bonus.commissionType = "referral"
        bonus.uplineLevel = 1
        bonus.fromRank = user.rank
        bonus.sourceRank = upline_user.rank
        bonus.bonusRate = float(REFERRAL_BONUS_PERCENTAGE)
        bonus.bonusAmount = bonus_amount
        bonus.status = "paid"
        bonus.notes = f"Referral bonus (1%) - {bonus_qty} options"
        bonus.ownerTelegramID = upline_user.telegramID
        bonus.ownerEmail = upline_user.email

        self.session.add(bonus)
        self.session.flush()

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Create auto-purchase (OPTIONS, not money!)
        # ═══════════════════════════════════════════════════════════
        await self._createReferralAutoPurchase(
            upline_user,
            purchase,
            bonus_amount,
            bonus_qty,
            bonus.bonusID
        )

        logger.info(
            f"✓ Referral bonus: ${bonus_amount} ({bonus_qty} options) "
            f"for user {upline_user.userID}"
        )

        return {
            "userId": upline_user.userID,
            "percentage": REFERRAL_BONUS_PERCENTAGE,
            "amount": bonus_amount,
            "level": 1,
            "rank": upline_user.rank,
            "isActive": True,
            "compressed": False,
            "isReferralBonus": True
        }

    async def _createReferralAutoPurchase(
            self,
            upline_user: User,
            original_purchase: Purchase,
            bonus_amount: Decimal,
            bonus_qty: int,
            bonus_id: int
    ):
        """
        Create automatic purchase using referral bonus.

        Transaction flow:
        1. Create Purchase record (auto-purchase options)
        2. ActiveBalance (+bonus_amount) - bonus credit from company
        3. ActiveBalance (-bonus_amount) - debit for purchase

        Net effect on user.balanceActive: 0 (credit and debit cancel out)
        But user gets OPTIONS added to their portfolio.

        Args:
            upline_user: User receiving referral bonus
            original_purchase: Purchase that triggered the bonus
            bonus_amount: Bonus amount (1% of purchase)
            bonus_qty: Number of options to purchase
            bonus_id: ID of the Bonus record
        """
        logger.debug(
            f"Creating referral auto-purchase for user {upline_user.userID}: "
            f"${bonus_amount}, {bonus_qty} options"
        )

        # ═══════════════════════════════════════════════════════════
        # STEP 1: Create Purchase record (auto-purchase)
        # ═══════════════════════════════════════════════════════════
        auto_purchase = Purchase()
        auto_purchase.userID = upline_user.userID
        auto_purchase.projectID = original_purchase.projectID
        auto_purchase.optionID = original_purchase.optionID
        auto_purchase.projectName = original_purchase.projectName
        auto_purchase.packQty = bonus_qty
        auto_purchase.packPrice = bonus_amount

        # AuditMixin fields
        auto_purchase.ownerTelegramID = upline_user.telegramID
        auto_purchase.ownerEmail = upline_user.email

        self.session.add(auto_purchase)
        self.session.flush()  # Get purchaseID

        logger.debug(
            f"Created referral auto-purchase: purchaseID={auto_purchase.purchaseID}, "
            f"qty={bonus_qty}, price=${bonus_amount}"
        )

        # ═══════════════════════════════════════════════════════════
        # STEP 2: Create ActiveBalance transaction records
        # ═══════════════════════════════════════════════════════════

        # Record 1: Bonus credited (+bonus_amount)
        bonus_credit = ActiveBalance()
        bonus_credit.userID = upline_user.userID
        bonus_credit.firstname = upline_user.firstname
        bonus_credit.surname = upline_user.surname
        bonus_credit.amount = bonus_amount
        bonus_credit.status = 'done'
        bonus_credit.reason = f'bonus={bonus_id}'
        bonus_credit.link = ''
        bonus_credit.notes = 'Referral bonus (1%) - auto-purchase credit'

        self.session.add(bonus_credit)

        # Record 2: Purchase debit (-bonus_amount)
        purchase_debit = ActiveBalance()
        purchase_debit.userID = upline_user.userID
        purchase_debit.firstname = upline_user.firstname
        purchase_debit.surname = upline_user.surname
        purchase_debit.amount = -bonus_amount
        purchase_debit.status = 'done'
        purchase_debit.reason = f'purchase={auto_purchase.purchaseID}'
        purchase_debit.link = ''
        purchase_debit.notes = 'Referral bonus (1%) - auto-purchase debit'

        self.session.add(purchase_debit)

        logger.info(
            f"✓ Referral auto-purchase completed: {bonus_qty} options worth ${bonus_amount} "
            f"for user {upline_user.userID}"
        )

    async def _saveCommission(
            self,
            commission: Dict,
            purchase: Purchase
    ):
        """Save commission to database as Bonus and update PassiveBalance."""
        bonus = Bonus()
        bonus.userID = commission["userId"]
        bonus.downlineID = purchase.userID
        bonus.purchaseID = purchase.purchaseID

        # Denormalized data
        bonus.projectID = purchase.projectID
        bonus.optionID = purchase.optionID
        bonus.packQty = purchase.packQty
        bonus.packPrice = purchase.packPrice

        # MLM specific
        bonus.uplineLevel = commission["level"]
        bonus.fromRank = purchase.user.rank
        bonus.sourceRank = commission["rank"]
        bonus.bonusRate = float(commission["percentage"])
        bonus.bonusAmount = commission["amount"]
        bonus.compressionApplied = 1 if commission.get("compressed") else 0

        # Determine commission type
        if commission.get("isSystemRoot"):
            bonus.commissionType = "system_compression"
            bonus.notes = "System commission (compression + remaining to 18%)"
        elif commission.get("isPioneerBonus"):
            bonus.commissionType = "pioneer"
            bonus.notes = "Pioneer bonus (+4%)"
        else:
            bonus.commissionType = "differential"
            bonus.notes = "Differential commission"

        bonus.status = "paid"

        # AuditMixin
        user = self.session.query(User).filter_by(userID=commission["userId"]).first()
        if user:
            bonus.ownerTelegramID = user.telegramID
            bonus.ownerEmail = user.email

        self.session.add(bonus)
        self.session.flush()

        # Update PassiveBalance
        if not commission.get("isSystemRoot"):
            # Regular user commission → PassiveBalance
            await self._updatePassiveBalance(
                commission["userId"],
                commission["amount"],
                bonus.bonusID
            )
        else:
            # System commission → recorded but not added to user balance
            logger.info(
                f"System commission ${commission['amount']} recorded "
                f"for root user {commission['userId']} (bonusID={bonus.bonusID})"
            )

    async def _updatePassiveBalance(
            self,
            userId: int,
            amount: Decimal,
            bonusId: int
    ):
        """Update user's passive balance."""
        from models.passive_balance import PassiveBalance

        user = self.session.query(User).filter_by(userID=userId).first()
        if not user:
            logger.error(f"User {userId} not found for passive balance update")
            return

        # Update user's passive balance total
        user.balancePassive = (user.balancePassive or Decimal("0")) + amount

        # Create PassiveBalance transaction record
        transaction = PassiveBalance()
        transaction.userID = userId
        transaction.firstname = user.firstname
        transaction.surname = user.surname
        transaction.amount = amount
        transaction.status = "done"
        transaction.reason = f"bonus={bonusId}"
        transaction.link = ""
        transaction.notes = "MLM commission"

        self.session.add(transaction)

        logger.info(f"Updated passive balance for user {userId}: +{amount} (bonus {bonusId})")

    def _getUserRankPercentage(self, user: User) -> Decimal:
        """Get commission percentage for user's rank."""
        try:
            rank_enum = Rank(user.rank.lower())
            return RANK_CONFIG()[rank_enum]["percentage"]  # ✅ CHANGED: Added ()
        except (ValueError, KeyError):
            logger.warning(f"Invalid rank '{user.rank}' for user {user.userID}, using START")
            return RANK_CONFIG()[Rank.START]["percentage"]  # ✅ CHANGED: Added ()