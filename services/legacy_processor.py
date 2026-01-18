# services/legacy_processor.py
"""
Legacy Migration Processor - Business Logic

Handles all migration processing:
- Creating purchases (V1: Darwin shares, V2: JETUP+AQUIX gifts)
- Assigning upliners/parents
- Sending notifications

Entry points:
1. process_user() - Called on email verification (instant)
2. process_batch() - Called from &legacy command (batch repair)
"""
import logging
from typing import Optional, Dict
from decimal import Decimal
from datetime import datetime, timezone

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models import User, Project, Purchase, ActiveBalance, Notification, Option
from models.legacy_migration import LegacyMigrationV1, LegacyMigrationV2
from core.db import get_db_session_ctx
from core.templates import MessageTemplates
from config import Config

logger = logging.getLogger(__name__)

# V2 Migration constants
OPTION_JETUP = 25
OPTION_AQUIX = 26
PROJECT_JETUP = 2
PROJECT_AQUIX = 3
COST_PER_SHARE_JETUP = Decimal("0.05")
COST_PER_SHARE_AQUIX = Decimal("0.03")
MINIMUM_GIFT_QTY = 84


class LegacyProcessor:
    """
    Business logic for legacy migration processing.
    """

    # =========================================================================
    # MAIN ENTRY POINT: EMAIL VERIFICATION
    # =========================================================================

    @staticmethod
    async def process_user(user: User, session: Session) -> Dict[str, int]:
        """
        Process user immediately when email is verified.
        Called from handlers/start.py on email verification.
        """
        stats = {'v1_processed': 0, 'v2_processed': 0, 'uplines_assigned': 0}

        try:
            email = LegacyProcessor._normalize_email(user.email)
            if not email:
                return stats

            logger.info(f"Processing legacy migration for {email}")

            # STAGE 1: Am I recipient?
            v1_count = await LegacyProcessor._process_as_recipient_v1(user, email, session)
            v2_count = await LegacyProcessor._process_as_recipient_v2(user, email, session)
            stats['v1_processed'] = v1_count
            stats['v2_processed'] = v2_count

            # STAGE 2: Am I upliner?
            uplines_v1 = await LegacyProcessor._process_as_upliner_v1(user, email, session)
            uplines_v2 = await LegacyProcessor._process_as_upliner_v2(user, email, session)
            stats['uplines_assigned'] = uplines_v1 + uplines_v2

            # STAGE 3: Who is my upliner?
            my_upline_v1 = await LegacyProcessor._process_my_upliner_v1(user, email, session)
            my_upline_v2 = await LegacyProcessor._process_my_upliner_v2(user, email, session)
            if my_upline_v1 or my_upline_v2:
                stats['uplines_assigned'] += 1

            if any(stats.values()):
                logger.info(
                    f"Legacy migration for {email}: "
                    f"V1={stats['v1_processed']}, V2={stats['v2_processed']}, "
                    f"uplines={stats['uplines_assigned']}"
                )

            return stats

        except Exception as e:
            logger.error(f"Error processing legacy for {user.email}: {e}", exc_info=True)
            return stats

    # =========================================================================
    # BATCH ENTRY POINT: &legacy COMMAND
    # =========================================================================

    @staticmethod
    async def process_batch() -> Dict[str, int]:
        """
        Process pending/stuck migrations in batch.
        Called from &legacy command.
        """
        stats = {
            'v1_processed': 0,
            'v2_processed': 0,
            'uplines_assigned': 0,
            'errors': 0
        }

        with get_db_session_ctx() as session:
            try:
                # ═══════════════════════════════════════════════════════════
                # BUILD EMAIL CACHE ONCE (avoid N+1 queries)
                # ═══════════════════════════════════════════════════════════
                users = session.query(User).filter(User.email.isnot(None)).all()
                email_cache = {}
                for u in users:
                    normalized = LegacyProcessor._normalize_email(u.email)
                    if normalized:
                        email_cache[normalized] = u
                logger.info(f"Built email cache: {len(email_cache)} users")

                # ═══════════════════════════════════════════════════════════
                # REPAIR 1: IsFound set, but PurchaseDone=0
                # ═══════════════════════════════════════════════════════════
                broken_v1 = session.query(LegacyMigrationV1).filter(
                    LegacyMigrationV1.IsFound.isnot(None),
                    LegacyMigrationV1.PurchaseDone == 0,
                    LegacyMigrationV1.status != 'error'
                ).all()

                for migration in broken_v1:
                    try:
                        user = session.query(User).filter_by(
                            userID=migration.IsFound
                        ).first()
                        if user:
                            result = await LegacyProcessor._create_v1_purchase(
                                user, migration, session
                            )
                            if result:
                                stats['v1_processed'] += 1
                    except Exception as e:
                        logger.error(f"Error repairing V1 {migration.migrationID}: {e}")
                        LegacyProcessor._record_error(migration, str(e), session)
                        stats['errors'] += 1

                broken_v2 = session.query(LegacyMigrationV2).filter(
                    LegacyMigrationV2.IsFound.isnot(None),
                    LegacyMigrationV2.PurchaseDone == 0,
                    LegacyMigrationV2.status != 'error'
                ).all()

                for migration in broken_v2:
                    try:
                        user = session.query(User).filter_by(
                            userID=migration.IsFound
                        ).first()
                        if user:
                            result = await LegacyProcessor._create_v2_gifts(
                                user, migration, session
                            )
                            if result:
                                stats['v2_processed'] += 1
                    except Exception as e:
                        logger.error(f"Error repairing V2 {migration.migrationID}: {e}")
                        LegacyProcessor._record_error(migration, str(e), session)
                        stats['errors'] += 1

                # ═══════════════════════════════════════════════════════════
                # REPAIR 2: IsFound=NULL, but user exists and verified
                # ═══════════════════════════════════════════════════════════
                pending_v1 = session.query(LegacyMigrationV1).filter(
                    LegacyMigrationV1.IsFound.is_(None),
                    LegacyMigrationV1.status == 'pending'
                ).all()

                for migration in pending_v1:
                    try:
                        normalized = LegacyProcessor._normalize_email(migration.email)
                        user = email_cache.get(normalized)
                        if user and user.emailConfirmed:
                            v1 = await LegacyProcessor._process_as_recipient_v1(
                                user, normalized, session
                            )
                            if v1:
                                stats['v1_processed'] += v1
                    except Exception as e:
                        logger.error(f"Error processing pending V1 {migration.migrationID}: {e}")
                        stats['errors'] += 1

                pending_v2 = session.query(LegacyMigrationV2).filter(
                    LegacyMigrationV2.IsFound.is_(None),
                    LegacyMigrationV2.status == 'pending'
                ).all()

                for migration in pending_v2:
                    try:
                        normalized = LegacyProcessor._normalize_email(migration.email)
                        user = email_cache.get(normalized)
                        if user and user.emailConfirmed:
                            v2 = await LegacyProcessor._process_as_recipient_v2(
                                user, normalized, session
                            )
                            if v2:
                                stats['v2_processed'] += v2
                    except Exception as e:
                        logger.error(f"Error processing pending V2 {migration.migrationID}: {e}")
                        stats['errors'] += 1

                # ═══════════════════════════════════════════════════════════
                # REPAIR 3: UplinerFound=0, but upliner now in system
                # ═══════════════════════════════════════════════════════════
                waiting_upliner_v1 = session.query(LegacyMigrationV1).filter(
                    LegacyMigrationV1.IsFound.isnot(None),
                    LegacyMigrationV1.UplinerFound == 0,
                    LegacyMigrationV1.status != 'error'
                ).all()

                for migration in waiting_upliner_v1:
                    try:
                        if migration.upliner and migration.upliner.upper() == 'SAME':
                            migration.UplinerFound = 1
                            LegacyProcessor._check_done(migration)
                            session.commit()
                            stats['uplines_assigned'] += 1
                            continue

                        if migration.upliner:
                            normalized = LegacyProcessor._normalize_email(migration.upliner)
                            upliner = email_cache.get(normalized)
                            if upliner and upliner.emailConfirmed:
                                referral = session.query(User).filter_by(
                                    userID=migration.IsFound
                                ).first()
                                if referral:
                                    result = await LegacyProcessor._assign_upliner(
                                        referral, upliner, migration, session
                                    )
                                    if result:
                                        stats['uplines_assigned'] += 1
                    except Exception as e:
                        logger.error(f"Error assigning upliner V1 {migration.migrationID}: {e}")
                        stats['errors'] += 1

                waiting_parent_v2 = session.query(LegacyMigrationV2).filter(
                    LegacyMigrationV2.IsFound.isnot(None),
                    LegacyMigrationV2.UplinerFound == 0,
                    LegacyMigrationV2.status != 'error'
                ).all()

                for migration in waiting_parent_v2:
                    try:
                        if migration.parent:
                            normalized = LegacyProcessor._normalize_email(migration.parent)
                            parent = email_cache.get(normalized)
                            if parent and parent.emailConfirmed:
                                referral = session.query(User).filter_by(
                                    userID=migration.IsFound
                                ).first()
                                if referral:
                                    result = await LegacyProcessor._assign_parent(
                                        referral, parent, migration, session
                                    )
                                    if result:
                                        stats['uplines_assigned'] += 1
                    except Exception as e:
                        logger.error(f"Error assigning parent V2 {migration.migrationID}: {e}")
                        stats['errors'] += 1

                session.commit()

            except Exception as e:
                logger.error(f"Error in process_batch: {e}", exc_info=True)
                stats['errors'] += 1

        return stats

    # =========================================================================
    # STAGE 1: AM I RECIPIENT?
    # =========================================================================

    @staticmethod
    async def _process_as_recipient_v1(
            user: User,
            email: str,
            session: Session
    ) -> int:
        """Process V1 records where I'm the recipient."""
        count = 0

        migrations = session.query(LegacyMigrationV1).filter(
            LegacyMigrationV1.email == email,
            LegacyMigrationV1.IsFound.is_(None),
            LegacyMigrationV1.status == 'pending'
        ).order_by(LegacyMigrationV1.gsRowIndex.asc()).all()

        for migration in migrations:
            try:
                migration.IsFound = user.userID
                result = await LegacyProcessor._create_v1_purchase(
                    user, migration, session
                )
                if result:
                    count += 1
            except Exception as e:
                logger.error(f"Error processing V1 {migration.migrationID}: {e}")
                LegacyProcessor._record_error(migration, str(e), session)

        return count

    @staticmethod
    async def _process_as_recipient_v2(
            user: User,
            email: str,
            session: Session
    ) -> int:
        """Process V2 records where I'm the recipient."""
        count = 0

        migrations = session.query(LegacyMigrationV2).filter(
            LegacyMigrationV2.email == email,
            LegacyMigrationV2.IsFound.is_(None),
            LegacyMigrationV2.status == 'pending'
        ).order_by(LegacyMigrationV2.gsRowIndex.asc()).all()

        for migration in migrations:
            try:
                migration.IsFound = user.userID
                result = await LegacyProcessor._create_v2_gifts(
                    user, migration, session
                )
                if result:
                    count += 1
            except Exception as e:
                logger.error(f"Error processing V2 {migration.migrationID}: {e}")
                LegacyProcessor._record_error(migration, str(e), session)

        return count

    # =========================================================================
    # STAGE 2: AM I UPLINER?
    # =========================================================================

    @staticmethod
    async def _process_as_upliner_v1(
            user: User,
            email: str,
            session: Session
    ) -> int:
        """Find referrals where I'm the upliner and assign upline."""
        count = 0

        migrations = session.query(LegacyMigrationV1).filter(
            LegacyMigrationV1.upliner == email,
            LegacyMigrationV1.IsFound.isnot(None),
            LegacyMigrationV1.UplinerFound == 0,
            LegacyMigrationV1.status != 'error'
        ).all()

        for migration in migrations:
            try:
                referral = session.query(User).filter_by(
                    userID=migration.IsFound
                ).first()

                if referral:
                    result = await LegacyProcessor._assign_upliner(
                        referral, user, migration, session
                    )
                    if result:
                        count += 1

            except Exception as e:
                logger.error(f"Error assigning upliner V1 {migration.migrationID}: {e}")

        return count

    @staticmethod
    async def _process_as_upliner_v2(
            user: User,
            email: str,
            session: Session
    ) -> int:
        """Find referrals where I'm the parent and assign upline."""
        count = 0

        migrations = session.query(LegacyMigrationV2).filter(
            LegacyMigrationV2.parent == email,
            LegacyMigrationV2.IsFound.isnot(None),
            LegacyMigrationV2.UplinerFound == 0,
            LegacyMigrationV2.status != 'error'
        ).all()

        for migration in migrations:
            try:
                referral = session.query(User).filter_by(
                    userID=migration.IsFound
                ).first()

                if referral:
                    result = await LegacyProcessor._assign_parent(
                        referral, user, migration, session
                    )
                    if result:
                        count += 1

            except Exception as e:
                logger.error(f"Error assigning parent V2 {migration.migrationID}: {e}")

        return count

    # =========================================================================
    # STAGE 3: WHO IS MY UPLINER?
    # =========================================================================

    @staticmethod
    async def _process_my_upliner_v1(
            user: User,
            email: str,
            session: Session
    ) -> bool:
        """Find my upliner from GS and assign. Last record = truth."""
        migration = session.query(LegacyMigrationV1).filter(
            LegacyMigrationV1.email == email,
            LegacyMigrationV1.upliner.isnot(None),
            LegacyMigrationV1.upliner != '',
            LegacyMigrationV1.UplinerFound == 0
        ).order_by(LegacyMigrationV1.gsRowIndex.desc()).first()

        if not migration:
            return False

        if migration.upliner.upper() == 'SAME':
            migration.UplinerFound = 1
            LegacyProcessor._check_done(migration)
            session.commit()
            return True

        upliner = LegacyProcessor._get_user_by_email(session, migration.upliner)
        if not upliner or not upliner.emailConfirmed:
            return False

        result = await LegacyProcessor._assign_upliner(
            user, upliner, migration, session
        )

        if result:
            other_records = session.query(LegacyMigrationV1).filter(
                LegacyMigrationV1.email == email,
                LegacyMigrationV1.migrationID != migration.migrationID,
                LegacyMigrationV1.UplinerFound == 0
            ).all()
            for rec in other_records:
                rec.UplinerFound = 1
                LegacyProcessor._check_done(rec)
            session.commit()

        return result

    @staticmethod
    async def _process_my_upliner_v2(
            user: User,
            email: str,
            session: Session
    ) -> bool:
        """Find my parent from GS (V2) and assign."""
        migration = session.query(LegacyMigrationV2).filter(
            LegacyMigrationV2.email == email,
            LegacyMigrationV2.parent.isnot(None),
            LegacyMigrationV2.parent != '',
            LegacyMigrationV2.UplinerFound == 0
        ).order_by(LegacyMigrationV2.gsRowIndex.desc()).first()

        if not migration:
            return False

        parent = LegacyProcessor._get_user_by_email(session, migration.parent)
        if not parent or not parent.emailConfirmed:
            return False

        result = await LegacyProcessor._assign_parent(
            user, parent, migration, session
        )

        if result:
            other_records = session.query(LegacyMigrationV2).filter(
                LegacyMigrationV2.email == email,
                LegacyMigrationV2.migrationID != migration.migrationID,
                LegacyMigrationV2.UplinerFound == 0
            ).all()
            for rec in other_records:
                rec.UplinerFound = 1
                LegacyProcessor._check_done(rec)
            session.commit()

        return result

    # =========================================================================
    # V1: CREATE PURCHASE (DARWIN)
    # =========================================================================

    @staticmethod
    async def _create_v1_purchase(
            user: User,
            migration: LegacyMigrationV1,
            session: Session
    ) -> bool:
        """Create V1 purchase with double-entry bookkeeping."""
        try:
            # PROTECTION: Check if already processed
            if migration.purchaseID:
                logger.info(f"V1: Migration {migration.migrationID} already has purchase")
                migration.PurchaseDone = 1
                LegacyProcessor._check_done(migration)
                session.commit()
                return False

            # Check existing purchase by same parameters
            existing_purchase = session.query(Purchase).filter(
                Purchase.userID == user.userID,
                Purchase.projectName == migration.project,
                Purchase.packQty == migration.qty
            ).first()

            if existing_purchase:
                logger.warning(
                    f"V1: Purchase already exists for {user.email}, linking"
                )
                migration.purchaseID = existing_purchase.purchaseID
                migration.PurchaseDone = 1
                LegacyProcessor._check_done(migration)
                session.commit()
                return False

            # SPECIAL CASE: qty=None (only change upliner)
            if migration.qty is None:
                migration.PurchaseDone = 1
                LegacyProcessor._check_done(migration)
                session.commit()
                logger.info(f"V1: Migration {migration.migrationID} - qty=None, marked done")
                return True

            # Find project and option
            project = session.query(Project).filter_by(
                projectName=migration.project
            ).first()

            if not project:
                raise ValueError(f"Project '{migration.project}' not found")

            option = session.query(Option).filter_by(
                projectID=project.projectID
            ).first()

            if not option:
                raise ValueError(f"No options for project '{migration.project}'")

            total_price = Decimal(str(option.costPerShare)) * migration.qty

            # STEP 1: Create Purchase
            purchase = Purchase()
            purchase.userID = user.userID
            purchase.projectID = project.projectID
            purchase.projectName = project.projectName
            purchase.optionID = option.optionID
            purchase.packQty = migration.qty
            purchase.packPrice = total_price
            purchase.ownerTelegramID = user.telegramID
            purchase.ownerEmail = user.email

            session.add(purchase)
            session.flush()

            # STEP 2: Create ActiveBalance (credit)
            balance = ActiveBalance()
            balance.userID = user.userID
            balance.firstname = user.firstname
            balance.surname = user.surname
            balance.amount = total_price
            balance.status = 'done'
            balance.reason = f'legacy_migration={purchase.purchaseID}'
            balance.link = ''
            balance.notes = (
                f'Legacy shares migration: {migration.qty} shares of '
                f'{migration.project} at ${option.costPerShare}/share'
            )
            balance.ownerTelegramID = user.telegramID
            balance.ownerEmail = user.email

            session.add(balance)

            # STEP 3: Update migration
            migration.purchaseID = purchase.purchaseID
            migration.PurchaseDone = 1
            LegacyProcessor._check_done(migration)

            session.commit()

            # STEP 4: Send notification
            await LegacyProcessor._send_purchase_notification(user, purchase, migration)

            logger.info(
                f"V1: Created purchase {purchase.purchaseID} for {user.email} "
                f"({migration.qty} shares, ${total_price})"
            )
            return True

        except Exception as e:
            logger.error(f"Error in _create_v1_purchase: {e}", exc_info=True)
            LegacyProcessor._record_error(migration, str(e), session)
            return False

    # =========================================================================
    # V2: CREATE GIFTS (JETUP + AQUIX)
    # =========================================================================

    @staticmethod
    async def _create_v2_gifts(
            user: User,
            migration: LegacyMigrationV2,
            session: Session
    ) -> bool:
        """Create V2 double gift (JETUP + AQUIX)."""
        try:
            # PROTECTION: Check if already processed
            if migration.jetupPurchaseID and migration.aquixPurchaseID:
                logger.info(f"V2: Migration {migration.migrationID} already has purchases")
                migration.PurchaseDone = 1
                LegacyProcessor._check_done(migration)
                session.commit()
                return False

            # SPECIAL CASE: value=None (only change parent)
            if migration.value is None:
                migration.PurchaseDone = 1
                LegacyProcessor._check_done(migration)
                session.commit()
                logger.info(f"V2: Migration {migration.migrationID} - value=None, marked done")
                return True

            # Calculate quantities
            value = Decimal(str(migration.value)) if migration.value else Decimal("0")

            if value == 0:
                jetup_qty = MINIMUM_GIFT_QTY
                aquix_qty = MINIMUM_GIFT_QTY
            else:
                jetup_qty = int(value / COST_PER_SHARE_JETUP)
                aquix_qty = int(value / COST_PER_SHARE_AQUIX)

            jetup_amount = Decimal(str(jetup_qty)) * COST_PER_SHARE_JETUP
            aquix_amount = Decimal(str(aquix_qty)) * COST_PER_SHARE_AQUIX

            # Get options
            jetup_option = session.query(Option).filter_by(optionID=OPTION_JETUP).first()
            aquix_option = session.query(Option).filter_by(optionID=OPTION_AQUIX).first()

            if not jetup_option or not aquix_option:
                raise ValueError(
                    f"JETUP or AQUIX options not found "
                    f"(JETUP={OPTION_JETUP}, AQUIX={OPTION_AQUIX})"
                )

            # JETUP: Purchase + ActiveBalance
            jetup_purchase = Purchase()
            jetup_purchase.userID = user.userID
            jetup_purchase.projectID = PROJECT_JETUP
            jetup_purchase.projectName = jetup_option.projectName
            jetup_purchase.optionID = OPTION_JETUP
            jetup_purchase.packQty = jetup_qty
            jetup_purchase.packPrice = jetup_amount
            jetup_purchase.ownerTelegramID = user.telegramID
            jetup_purchase.ownerEmail = user.email
            session.add(jetup_purchase)
            session.flush()

            jetup_balance = ActiveBalance()
            jetup_balance.userID = user.userID
            jetup_balance.firstname = user.firstname
            jetup_balance.surname = user.surname
            jetup_balance.amount = jetup_amount
            jetup_balance.status = 'done'
            jetup_balance.reason = f'legacy_migration={jetup_purchase.purchaseID}'
            jetup_balance.notes = f'V2 Migration: JETUP gift {jetup_qty} shares'
            jetup_balance.ownerTelegramID = user.telegramID
            jetup_balance.ownerEmail = user.email
            session.add(jetup_balance)

            # AQUIX: Purchase + ActiveBalance
            aquix_purchase = Purchase()
            aquix_purchase.userID = user.userID
            aquix_purchase.projectID = PROJECT_AQUIX
            aquix_purchase.projectName = aquix_option.projectName
            aquix_purchase.optionID = OPTION_AQUIX
            aquix_purchase.packQty = aquix_qty
            aquix_purchase.packPrice = aquix_amount
            aquix_purchase.ownerTelegramID = user.telegramID
            aquix_purchase.ownerEmail = user.email
            session.add(aquix_purchase)
            session.flush()

            aquix_balance = ActiveBalance()
            aquix_balance.userID = user.userID
            aquix_balance.firstname = user.firstname
            aquix_balance.surname = user.surname
            aquix_balance.amount = aquix_amount
            aquix_balance.status = 'done'
            aquix_balance.reason = f'legacy_migration={aquix_purchase.purchaseID}'
            aquix_balance.notes = f'V2 Migration: AQUIX gift {aquix_qty} shares'
            aquix_balance.ownerTelegramID = user.telegramID
            aquix_balance.ownerEmail = user.email
            session.add(aquix_balance)

            # Update migration
            migration.jetupPurchaseID = jetup_purchase.purchaseID
            migration.aquixPurchaseID = aquix_purchase.purchaseID
            migration.PurchaseDone = 1
            LegacyProcessor._check_done(migration)

            session.commit()

            logger.info(
                f"V2: Created gifts for {user.email}: "
                f"{jetup_qty} JETUP (${jetup_amount}) + {aquix_qty} AQUIX (${aquix_amount})"
            )
            return True

        except Exception as e:
            logger.error(f"Error in _create_v2_gifts: {e}", exc_info=True)
            LegacyProcessor._record_error(migration, str(e), session)
            return False

    # =========================================================================
    # ASSIGN UPLINER/PARENT
    # =========================================================================

    @staticmethod
    async def _assign_upliner(
            referral: User,
            upliner: User,
            migration: LegacyMigrationV1,
            session: Session
    ) -> bool:
        """Assign upliner to referral (V1)."""
        try:
            old_upline = referral.upline

            if old_upline != upliner.telegramID:
                logger.info(
                    f"V1: Changing upliner for {referral.email} "
                    f"from {old_upline} to {upliner.telegramID}"
                )
                referral.upline = upliner.telegramID

            migration.UplinerFound = 1
            LegacyProcessor._check_done(migration)
            session.commit()

            await LegacyProcessor._send_upliner_notification(referral, upliner)

            return True

        except Exception as e:
            logger.error(f"Error assigning upliner: {e}")
            return False

    @staticmethod
    async def _assign_parent(
            referral: User,
            parent: User,
            migration: LegacyMigrationV2,
            session: Session
    ) -> bool:
        """Assign parent to referral (V2)."""
        try:
            old_upline = referral.upline

            if old_upline != parent.telegramID:
                logger.info(
                    f"V2: Changing parent for {referral.email} "
                    f"from {old_upline} to {parent.telegramID}"
                )
                referral.upline = parent.telegramID

            migration.UplinerFound = 1
            LegacyProcessor._check_done(migration)
            session.commit()

            await LegacyProcessor._send_upliner_notification(referral, parent)

            return True

        except Exception as e:
            logger.error(f"Error assigning parent: {e}")
            return False

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    @staticmethod
    async def _send_purchase_notification(
            user: User,
            purchase: Purchase,
            migration
    ):
        """Send notification when purchase is created."""
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_purchase_created_user',
                {
                    'firstname': user.firstname,
                    'qty': migration.qty,
                    'project_name': migration.project,
                    'purchase_id': purchase.purchaseID
                },
                lang=user.lang or 'en'
            )

            notification = Notification(
                source="legacy_migration",
                text=text,
                buttons=buttons,
                targetType="user",
                targetValue=str(user.userID),
                priority=2,
                category="legacy",
                importance="normal",
                parseMode="HTML"
            )

            with get_db_session_ctx() as notif_session:
                notif_session.add(notification)
                notif_session.commit()

        except Exception as e:
            logger.error(f"Error sending purchase notification: {e}")

    @staticmethod
    async def _send_upliner_notification(referral: User, upliner: User):
        """Send notifications to both referral and upliner."""
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_user',
                {'firstname': referral.firstname, 'upliner_name': upliner.firstname},
                lang=referral.lang or 'en'
            )
            notif_referral = Notification(
                source="legacy_migration",
                text=text,
                buttons=buttons,
                targetType="user",
                targetValue=str(referral.userID),
                priority=2,
                category="legacy",
                importance="normal",
                parseMode="HTML"
            )

            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_upliner',
                {'firstname': upliner.firstname, 'user_name': referral.firstname},
                lang=upliner.lang or 'en'
            )
            notif_upliner = Notification(
                source="legacy_migration",
                text=text,
                buttons=buttons,
                targetType="user",
                targetValue=str(upliner.userID),
                priority=2,
                category="legacy",
                importance="normal",
                parseMode="HTML"
            )

            with get_db_session_ctx() as notif_session:
                notif_session.add(notif_referral)
                notif_session.add(notif_upliner)
                notif_session.commit()

        except Exception as e:
            logger.error(f"Error sending upliner notifications: {e}")

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Normalize email: lowercase, strip, Gmail dot handling."""
        if not email:
            return ""

        email = str(email).lower().strip()

        if '@gmail.com' in email:
            local, domain = email.split('@', 1)
            local = local.replace('.', '')
            return f"{local}@{domain}"

        return email

    @staticmethod
    def _get_user_by_email(session: Session, email: str) -> Optional[User]:
        """Get user by normalized email. Used in process_user (single user)."""
        normalized = LegacyProcessor._normalize_email(email)
        if not normalized:
            return None

        # For single lookups, query directly
        users = session.query(User).filter(User.email.isnot(None)).all()

        for user in users:
            if LegacyProcessor._normalize_email(user.email) == normalized:
                return user

        return None

    @staticmethod
    def _check_done(migration):
        """Check if migration is fully done and update status."""
        if (migration.IsFound and
            migration.PurchaseDone == 1 and
            migration.UplinerFound == 1):
            migration.status = 'done'
            migration.processedAt = datetime.now(timezone.utc)

    @staticmethod
    def _record_error(migration, error: str, session: Session):
        """Record error on migration."""
        migration.errorCount = (migration.errorCount or 0) + 1
        migration.lastError = str(error)[:500]

        if migration.errorCount > 5:
            migration.status = 'error'

        flag_modified(migration, 'errorCount')
        flag_modified(migration, 'lastError')
        session.commit()