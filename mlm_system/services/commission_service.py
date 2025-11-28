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

        COMPRESSION LOGIC (per TZ):
        - Inactive users are skipped (get $0)
        - Their differential is accumulated for next active user
        - BUT: lastPercentage is still updated to inactive user's rank
        - This ensures next active user gets differential from inactive's rank, not buyer's

        Example:
        - Buyer (0%) -> L4_A (4%, active) -> L3_A (8%, INACTIVE) -> L2_A (12%, active)
        - L4_A: 4% - 0% = 4% = $40
        - L3_A: 8% - 4% = 4% accumulated (but lastPercentage becomes 8%)
        - L2_A: 12% - 8% = 4% + 4% accumulated = 8% = $80
        - Total: $40 + $80 = $120 ❌ WRONG

        CORRECT:
        - L4_A: 4% - 0% = 4% = $40
        - L3_A: INACTIVE, skipped, accumulated = 4%
        - L2_A: 12% - 4% = 8% (NOT 12% - 8% because we don't update lastPercentage for inactive)
        - BUT we add accumulated: 8% differential, NOT 8% + 4%

        Actually per TZ Method A:
        - Inactive user is skipped completely
        - Next active user receives from where last PAID user left off
        - So L2_A should get 12% - 4% = 8% = $80 (NO extra compression)

        Let me re-read TZ...

        Per TZ "Compression Method A":
        - Inactive users are simply skipped
        - Their portion goes to the NEXT active user up the chain
        - The differential is calculated from last ACTIVE user's percentage

        So correct flow:
        - L4_A (4%, active): differential = 4% - 0% = 4%, gets $40, lastPaid = 4%
        - L3_A (8%, inactive): SKIPPED, gets $0
        - L2_A (12%, active): differential = 12% - 4% = 8%, gets $80, lastPaid = 12%
        - L1_A (15%, active): differential = 15% - 12% = 3%, gets $30
        - ROOT (18%, active): differential = 18% - 15% = 3%, gets $30
        - Total: $40 + $80 + $30 + $30 = $180 ✅
        """
        from mlm_system.utils.chain_walker import ChainWalker

        commissions = []
        lastPaidPercentage = Decimal("0")  # Track last PAID percentage (active users only)
        accumulated_compression = Decimal("0")  # Not used in Method A, but kept for system_compression

        walker = ChainWalker(self.session)

        def process_upline(upline_user: User, level: int) -> bool:
            """Process each upline user for commission calculation."""
            nonlocal lastPaidPercentage, accumulated_compression

            # Get user's rank percentage
            userPercentage = self._getUserRankPercentage(upline_user)

            # Check if upline is active
            if not upline_user.isActive:
                # INACTIVE: Record with $0, do NOT update lastPaidPercentage
                # The differential they "would have received" goes to next active user
                commissions.append({
                    "userId": upline_user.userID,
                    "percentage": Decimal("0"),
                    "amount": Decimal("0"),
                    "level": level,
                    "rank": upline_user.rank,
                    "isActive": False,
                    "compressed": True,
                    "compressionApplied": 1
                })

                logger.debug(
                    f"Skipping inactive user {upline_user.userID} (rank {upline_user.rank}, "
                    f"{float(userPercentage * 100):.1f}%), lastPaidPercentage stays at "
                    f"{float(lastPaidPercentage * 100):.1f}%"
                )

            else:
                # ACTIVE: Calculate differential from last PAID percentage
                differential = userPercentage - lastPaidPercentage

                if differential > 0:
                    amount = Decimal(str(purchase.packPrice)) * differential

                    commissions.append({
                        "userId": upline_user.userID,
                        "percentage": differential,
                        "amount": amount,
                        "level": level,
                        "rank": upline_user.rank,
                        "isActive": True,
                        "compressed": False,
                        "compressionApplied": 0
                    })

                    logger.debug(
                        f"Active user {upline_user.userID}: {float(userPercentage * 100):.1f}% - "
                        f"{float(lastPaidPercentage * 100):.1f}% = {float(differential * 100):.1f}% "
                        f"= ${amount}"
                    )

                    # Update lastPaidPercentage ONLY for active users who received payment
                    lastPaidPercentage = userPercentage

            # Stop at max percentage (18%)
            if lastPaidPercentage >= Decimal("0.18"):
                return False  # Stop walking

            return True  # Continue walking

        # Walk up the chain safely
        walker.walk_upline(purchase.user, process_upline)

        # ═══════════════════════════════════════════════════════════════════
        # SYSTEM COMPRESSION: Send remaining commission to ROOT
        # If chain didn't reach 18%, remainder goes to system wallet
        # ═══════════════════════════════════════════════════════════════════
        if lastPaidPercentage < Decimal("0.18"):
            default_ref_id = walker.get_default_referrer_id()
            root_user = self.session.query(User).filter_by(
                telegramID=default_ref_id
            ).first()

            if root_user:
                # Calculate remaining percentage up to 18%
                remaining_percentage = Decimal("0.18") - lastPaidPercentage

                if remaining_percentage > 0:
                    amount = Decimal(str(purchase.packPrice)) * remaining_percentage

                    # Check if ROOT already has a commission entry
                    root_has_commission = any(
                        c["userId"] == root_user.userID and c["isActive"]
                        for c in commissions
                    )

                    if root_has_commission:
                        # Add to existing ROOT commission
                        for c in commissions:
                            if c["userId"] == root_user.userID and c["isActive"]:
                                c["amount"] += amount
                                c["percentage"] += remaining_percentage
                                c["isSystemRoot"] = True
                                logger.info(
                                    f"Added system compression to existing ROOT commission: "
                                    f"+${amount} ({float(remaining_percentage * 100):.1f}%)"
                                )
                                break
                    else:
                        # Create new system_compression entry
                        commissions.append({
                            "userId": root_user.userID,
                            "percentage": remaining_percentage,
                            "amount": amount,
                            "level": len(commissions) + 1,
                            "rank": root_user.rank,
                            "isActive": True,
                            "compressed": False,
                            "isSystemRoot": True,
                            "commissionType": "system_compression"
                        })

                        logger.info(
                            f"System compression to root user {root_user.userID}: "
                            f"${amount} ({float(remaining_percentage * 100):.1f}%)"
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
        """
        Save commission to database as Bonus with PENDING status.

        Commission will be paid on 5th of next month by processMonthlyPayments().
        Creates notification to inform user about pending commission.
        """
        from models import Notification
        from core.templates import MessageTemplates

        # Create Bonus record
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

        # ✅ CHANGED: Status is now PENDING (not paid immediately)
        bonus.status = "pending"

        # AuditMixin
        user = self.session.query(User).filter_by(userID=commission["userId"]).first()
        if user:
            bonus.ownerTelegramID = user.telegramID
            bonus.ownerEmail = user.email

        self.session.add(bonus)
        self.session.flush()

        # ═══════════════════════════════════════════════════════════
        # System commission (root user) - no notification needed
        # ═══════════════════════════════════════════════════════════
        if commission.get("isSystemRoot"):
            logger.info(
                f"System commission ${commission['amount']} recorded "
                f"for root user {commission['userId']} (bonusID={bonus.bonusID}, status=pending)"
            )
            return

        # ═══════════════════════════════════════════════════════════
        # ✅ NEW: Create PENDING notification for user
        # ═══════════════════════════════════════════════════════════
        try:
            from mlm_system.utils.time_machine import timeMachine

            # Calculate next payment date (5th of next month)
            current_month = timeMachine.currentMonth  # e.g. "2025-01"
            year, month = map(int, current_month.split('-'))
            next_month = month + 1
            next_year = year
            if next_month > 12:
                next_month = 1
                next_year += 1
            payment_date = f"{next_year}-{next_month:02d}-05"

            # Get template
            text, buttons = await MessageTemplates.get_raw_template(
                '/mlm/differential_commission_pending',
                {
                    'bonus_amount': float(commission["amount"]),
                    'level': commission["level"],
                    'purchase_amount': float(purchase.packPrice),
                    'payment_date': payment_date,
                    'downline_name': purchase.user.firstname
                },
                lang=user.lang or 'en'
            )

            # Create notification
            notification = Notification(
                source="mlm_system",
                text=text,
                buttons=buttons,
                targetType="user",
                targetValue=str(commission["userId"]),
                priority=2,
                category="mlm",
                importance="medium",
                parseMode="HTML"
            )

            self.session.add(notification)

            logger.info(
                f"✓ Pending commission notification created for user {commission['userId']}: "
                f"${commission['amount']} (bonusID={bonus.bonusID})"
            )

        except Exception as notif_error:
            # Don't fail commission creation if notification fails
            logger.error(
                f"Failed to create pending notification for bonus {bonus.bonusID}: {notif_error}",
                exc_info=True
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