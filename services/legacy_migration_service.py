# services/legacy_migration_service.py
"""
Legacy Migration Service - EVENT-DRIVEN ARCHITECTURE

Processes legacy users from PostgreSQL cache on email verification event.
Much faster than polling Google Sheets every 10 minutes.

Entry points:
1. process_user_on_email_verify() - Called when user verifies email (INSTANT)
2. process_batch() - Background fallback for old users (HOURLY)
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

# V2 Migration constants (from old code)
OPTION_JETUP = 25
OPTION_AQUIX = 26
PROJECT_JETUP = 2
PROJECT_AQUIX = 3
COST_PER_SHARE_JETUP = Decimal("0.05")
COST_PER_SHARE_AQUIX = Decimal("0.03")
MINIMUM_GIFT_QTY = 84


class LegacyMigrationService:
    """
    Service for processing legacy migrations on email verification event.

    Architecture:
    - PostgreSQL stores migration records (imported from Google Sheets)
    - On email verify: instant SQL checks (no GS API calls)
    - Background processor: handles old users + retries
    """

    # =========================================================================
    # EVENT-DRIVEN ENTRY POINT (called from handlers/start.py)
    # =========================================================================

    @staticmethod
    async def process_user_on_email_verify(user: User, session: Session) -> Dict[str, int]:
        """
        Process user immediately when email is verified.

        This is THE MAIN INTEGRATION POINT - called from handlers/start.py

        Performs TWO checks:
        1. Am I recipient of legacy balances?
        2. Am I upliner for someone?

        Args:
            user: Verified user
            session: Active DB session

        Returns:
            Dict with counts: {v1_processed, v2_processed, uplines_assigned}
        """
        stats = {'v1_processed': 0, 'v2_processed': 0, 'uplines_assigned': 0}

        try:
            normalized_email = LegacyMigrationService._normalize_email(user.email)

            # CHECK #1: Am I recipient?
            await LegacyMigrationService._check_as_recipient(user, normalized_email, session, stats)

            # CHECK #2: Am I upliner?
            await LegacyMigrationService._check_as_upliner(user, normalized_email, session, stats)

            if any(stats.values()):
                logger.info(
                    f"Legacy migration for {user.email}: "
                    f"V1={stats['v1_processed']}, V2={stats['v2_processed']}, "
                    f"uplines={stats['uplines_assigned']}"
                )

            return stats

        except Exception as e:
            logger.error(f"Error in email verify migration for {user.email}: {e}", exc_info=True)
            return stats

    # =========================================================================
    # BACKGROUND PROCESSOR ENTRY POINT
    # =========================================================================

    @staticmethod
    async def process_batch(batch_size: int = 100) -> Dict[str, int]:
        """
        Process pending migrations in batch (background task).

        Use cases:
        - Users who registered BEFORE migration system deployed
        - Retry failed migrations
        - Cleanup incomplete migrations

        Args:
            batch_size: Number of records to process

        Returns:
            Dict with processing stats
        """
        stats = {
            'v1_processed': 0,
            'v2_processed': 0,
            'uplines_assigned': 0,
            'errors': 0
        }

        with get_db_session_ctx() as session:
            try:
                # Get pending V1 migrations (not completed or error)
                # Include: pending, user_found (old status), purchase_done
                v1_migrations = session.query(LegacyMigrationV1).filter(
                    LegacyMigrationV1.status.in_(['pending', 'user_found', 'purchase_done'])
                ).limit(batch_size).all()

                for migration in v1_migrations:
                    try:
                        user = LegacyMigrationService._get_user_by_email(session, migration.email)
                        if user and user.emailConfirmed:
                            result = await LegacyMigrationService._process_v1_migration(
                                migration, user, session
                            )
                            if result:
                                stats['v1_processed'] += 1
                    except Exception as e:
                        logger.error(f"Error processing V1 {migration.email}: {e}")
                        migration.errorCount += 1
                        migration.lastError = str(e)[:500]
                        if migration.errorCount > 5:
                            migration.status = 'error'
                        flag_modified(migration, 'errorCount')
                        flag_modified(migration, 'lastError')
                        stats['errors'] += 1

                # Get pending V2 migrations (not completed or error)
                # Include: pending, user_found (old status), purchase_done
                v2_migrations = session.query(LegacyMigrationV2).filter(
                    LegacyMigrationV2.status.in_(['pending', 'user_found', 'purchase_done'])
                ).limit(batch_size).all()

                logger.info(f"V2: Found {len(v2_migrations)} pending migrations to process")

                for migration in v2_migrations:
                    try:
                        logger.debug(f"V2: Processing migration {migration.migrationID} for {migration.email}")
                        user = LegacyMigrationService._get_user_by_email(session, migration.email)

                        if not user:
                            logger.debug(f"V2: User not found for {migration.email}")
                            continue

                        logger.debug(f"V2: User found (userID={user.userID}), emailConfirmed={user.emailConfirmed}")

                        if user and user.emailConfirmed:
                            logger.info(f"V2: Processing {migration.email} (userID={user.userID})")
                            result = await LegacyMigrationService._process_v2_migration(
                                migration, user, session
                            )
                            if result:
                                stats['v2_processed'] += 1
                        else:
                            logger.debug(f"V2: Email not confirmed for {migration.email}")
                    except Exception as e:
                        logger.error(f"Error processing V2 {migration.email}: {e}", exc_info=True)
                        migration.errorCount += 1
                        migration.lastError = str(e)[:500]
                        if migration.errorCount > 5:
                            migration.status = 'error'
                        flag_modified(migration, 'errorCount')
                        flag_modified(migration, 'lastError')
                        stats['errors'] += 1

                session.commit()

            except Exception as e:
                logger.error(f"Error in batch processing: {e}", exc_info=True)
                stats['errors'] += 1

        return stats

    # =========================================================================
    # CHECK #1: AM I RECIPIENT?
    # =========================================================================

    @staticmethod
    async def _check_as_recipient(
            user: User,
            normalized_email: str,
            session: Session,
            stats: Dict[str, int]
    ):
        """Check if user is recipient of legacy balances."""

        # V1: Find migrations for this email
        v1_migrations = session.query(LegacyMigrationV1).filter(
            LegacyMigrationV1.email == normalized_email,
            LegacyMigrationV1.status == 'pending'
        ).all()

        for migration in v1_migrations:
            try:
                result = await LegacyMigrationService._process_v1_migration(
                    migration, user, session
                )
                if result:
                    stats['v1_processed'] += 1
            except Exception as e:
                logger.error(f"Error processing V1 for {user.email}: {e}")

        # V2: Find migrations for this email
        v2_migrations = session.query(LegacyMigrationV2).filter(
            LegacyMigrationV2.email == normalized_email,
            LegacyMigrationV2.status == 'pending'
        ).all()

        for migration in v2_migrations:
            try:
                result = await LegacyMigrationService._process_v2_migration(
                    migration, user, session
                )
                if result:
                    stats['v2_processed'] += 1
            except Exception as e:
                logger.error(f"Error processing V2 for {user.email}: {e}")

    # =========================================================================
    # CHECK #2: AM I UPLINER?
    # =========================================================================

    @staticmethod
    async def _check_as_upliner(
            user: User,
            normalized_email: str,
            session: Session,
            stats: Dict[str, int]
    ):
        """Check if user is upliner for someone."""

        # V1: Find referrals where I'm the upliner
        v1_referrals = session.query(LegacyMigrationV1).filter(
            LegacyMigrationV1.upliner == normalized_email,
            LegacyMigrationV1.status.in_(['pending', 'purchase_done'])
        ).all()

        for migration in v1_referrals:
            try:
                result = await LegacyMigrationService._assign_v1_upliner(
                    migration, user, session
                )
                if result:
                    stats['uplines_assigned'] += 1
            except Exception as e:
                logger.error(f"Error assigning V1 upliner for {migration.email}: {e}")

        # V2: Find referrals where I'm the parent
        v2_referrals = session.query(LegacyMigrationV2).filter(
            LegacyMigrationV2.parent == normalized_email,
            LegacyMigrationV2.status.in_(['pending', 'purchase_done'])
        ).all()

        for migration in v2_referrals:
            try:
                result = await LegacyMigrationService._assign_v2_parent(
                    migration, user, session
                )
                if result:
                    stats['uplines_assigned'] += 1
            except Exception as e:
                logger.error(f"Error assigning V2 parent for {migration.email}: {e}")

    # =========================================================================
    # V1 PROCESSING (DARWIN RESTORATION)
    # =========================================================================

    @staticmethod
    async def _process_v1_migration(
            migration: LegacyMigrationV1,
            user: User,
            session: Session
    ) -> bool:
        """
        Process V1 migration: Create Purchase + ActiveBalance.

        Logic from old _create_purchase() function.
        """
        try:
            # Update userID if not set
            if not migration.userID:
                migration.userID = user.userID
                migration.userFoundAt = datetime.now(timezone.utc)

            # PROTECTION 1: Check if purchaseID already set
            if migration.purchaseID:
                logger.info(f"V1: Purchase already exists for {user.email} (purchaseID={migration.purchaseID})")
                return False

            # PROTECTION 2: Check if Purchase with same parameters already exists
            # (protects against duplicates after TRUNCATE)
            existing_purchase = session.query(Purchase).filter(
                Purchase.userID == user.userID,
                Purchase.projectName == migration.project,
                Purchase.packQty == migration.qty
            ).first()

            if existing_purchase:
                logger.warning(
                    f"V1: Purchase already exists for {user.email} "
                    f"(userID={user.userID}, project={migration.project}, qty={migration.qty}). "
                    f"Linking purchaseID={existing_purchase.purchaseID} to migration."
                )
                migration.purchaseID = existing_purchase.purchaseID
                migration.status = 'purchase_done'
                session.commit()
                return False

            # Find project
            project = session.query(Project).filter_by(
                projectName=migration.project
            ).first()

            if not project:
                logger.error(f"Project '{migration.project}' not found for {user.email}")
                migration.errorCount += 1
                migration.lastError = f"Project '{migration.project}' not found"
                flag_modified(migration, 'errorCount')
                flag_modified(migration, 'lastError')
                session.commit()
                return False

            # Find first option for project
            option = session.query(Option).filter_by(
                projectID=project.projectID
            ).first()

            if not option:
                logger.error(f"No options for project '{migration.project}'")
                migration.errorCount += 1
                migration.lastError = f"No options for project"
                flag_modified(migration, 'errorCount')
                flag_modified(migration, 'lastError')
                session.commit()
                return False

            # Calculate price
            total_price = Decimal(str(option.costPerShare * migration.qty))

            # Create Purchase
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
            session.flush()  # Get purchaseID

            # Create ActiveBalance record
            balance = ActiveBalance()
            balance.userID = user.userID
            balance.firstname = user.firstname
            balance.surname = user.surname
            balance.amount = total_price
            balance.status = 'done'
            balance.reason = f'legacy_migration={purchase.purchaseID}'  # OLD FORMAT - easier to search by purchaseID
            balance.link = ''
            balance.notes = (
                f'Legacy shares migration: {migration.qty} shares of '
                f'{project.projectName} at ${option.costPerShare}/share'
            )
            balance.ownerTelegramID = user.telegramID
            balance.ownerEmail = user.email

            session.add(balance)

            # Update migration: purchase created
            migration.purchaseID = purchase.purchaseID
            migration.status = 'purchase_done'  # Purchase done, upliner may be pending

            # Check if upliner assignment is needed
            default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
            upliner_needed = (
                    migration.upliner and
                    migration.upliner.upper() != 'SAME' and
                    migration.upliner.strip() != ''
            )

            if not upliner_needed:
                # No upliner or SAME keyword - use default or keep current
                if user.upline is None or user.upline == default_referrer_id:
                    # Set default referrer if no upline
                    user.upline = default_referrer_id
                # Already completed - no need to wait for upliner
                migration.status = 'completed'
                migration.completedAt = datetime.now(timezone.utc)
                logger.info(f"V1: No upliner needed for {user.email}, marked as completed")

            session.commit()

            # Send notification
            await LegacyMigrationService._send_purchase_notification(
                user, purchase, migration
            )

            logger.info(
                f"V1: Created purchase {purchase.purchaseID} for {user.email} "
                f"(${total_price})"
            )
            return True

        except Exception as e:
            logger.error(f"Error in _process_v1_migration for {user.email}: {e}")
            migration.errorCount += 1
            migration.lastError = str(e)[:500]
            if migration.errorCount > 5:
                migration.status = 'error'
            flag_modified(migration, 'errorCount')
            flag_modified(migration, 'lastError')
            session.commit()
            return False

    @staticmethod
    async def _assign_v1_upliner(
            migration: LegacyMigrationV1,
            upliner: User,
            session: Session
    ) -> bool:
        """
        Assign upliner to V1 migration referral.

        CRITICAL: FORCEFULLY changes upline (legacy data is truth).
        """
        try:
            # Find referral user
            referral = LegacyMigrationService._get_user_by_email(session, migration.email)

            if not referral:
                logger.debug(f"V1: Referral {migration.email} not registered yet")
                return False

            if not referral.emailConfirmed:
                logger.debug(f"V1: Referral {migration.email} email not verified yet")
                return False

            # Get default referrer
            default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
            old_upline = referral.upline

            # FORCEFULLY change upline
            if old_upline != upliner.telegramID:
                if old_upline and old_upline != default_referrer_id:
                    logger.info(
                        f"V1: FORCEFULLY changing upliner for {referral.email} "
                        f"from {old_upline} to {upliner.telegramID}"
                    )
                else:
                    logger.info(
                        f"V1: Setting upliner for {referral.email} to {upliner.telegramID}"
                    )

                referral.upline = upliner.telegramID
                migration.uplinerID = upliner.userID

                # If purchase already done, mark as completed
                if migration.status == 'purchase_done':
                    migration.status = 'completed'
                    migration.completedAt = datetime.now(timezone.utc)
                    logger.info(f"V1: Migration for {migration.email} completed (upliner assigned)")

                session.commit()

                # Send notifications
                await LegacyMigrationService._send_upliner_notifications(
                    referral, upliner
                )

            return True

        except Exception as e:
            logger.error(f"Error assigning V1 upliner for {migration.email}: {e}")
            return False

    # =========================================================================
    # V2 PROCESSING (AQUIX DOUBLE GIFT)
    # =========================================================================

    @staticmethod
    async def _process_v2_migration(
            migration: LegacyMigrationV2,
            user: User,
            session: Session
    ) -> bool:
        """
        Process V2 migration: Grant JETUP + AQUIX double gift.

        Logic from old _v2_grant_double_gift() function.
        """
        try:
            # Update userID if not set
            if not migration.userID:
                migration.userID = user.userID
                migration.userFoundAt = datetime.now(timezone.utc)
                migration.status = 'user_found'

            # PROTECTION 1: Check if balances already set
            if migration.jetupBalanceID or migration.aquixBalanceID:
                logger.info(f"V2: Gifts already created for {user.email}")
                return False

            # PROTECTION 2: Check if ActiveBalances with legacy_v2 reason already exist
            # (protects against duplicates after TRUNCATE)
            existing_jetup = session.query(ActiveBalance).filter(
                ActiveBalance.userID == user.userID,
                ActiveBalance.reason.like('legacy_v2%jetup%')
            ).first()

            existing_aquix = session.query(ActiveBalance).filter(
                ActiveBalance.userID == user.userID,
                ActiveBalance.reason.like('legacy_v2%aquix%')
            ).first()

            if existing_jetup or existing_aquix:
                logger.warning(
                    f"V2: ActiveBalances already exist for {user.email} "
                    f"(JETUP: {existing_jetup.paymentID if existing_jetup else 'None'}, "
                    f"AQUIX: {existing_aquix.paymentID if existing_aquix else 'None'}). "
                    f"Linking to migration."
                )
                if existing_jetup:
                    migration.jetupBalanceID = existing_jetup.paymentID
                if existing_aquix:
                    migration.aquixBalanceID = existing_aquix.paymentID
                migration.status = 'purchase_done' if existing_jetup and existing_aquix else 'user_found'
                session.commit()
                return False

            # Calculate quantities
            if migration.value == 0:
                jetup_qty = MINIMUM_GIFT_QTY
                aquix_qty = MINIMUM_GIFT_QTY
            else:
                jetup_qty = int(migration.value / COST_PER_SHARE_JETUP)
                aquix_qty = int(migration.value / COST_PER_SHARE_AQUIX)

            # Get options (ignore status - these are special legacy options)
            jetup_option = session.query(Option).filter_by(optionID=OPTION_JETUP).first()
            aquix_option = session.query(Option).filter_by(optionID=OPTION_AQUIX).first()

            logger.debug(f"V2: Options lookup - JETUP={jetup_option}, AQUIX={aquix_option}")

            if not jetup_option or not aquix_option:
                logger.error(
                    f"V2: JETUP or AQUIX options not found in DB. "
                    f"JETUP (optionID={OPTION_JETUP}): {jetup_option}, "
                    f"AQUIX (optionID={OPTION_AQUIX}): {aquix_option}"
                )
                migration.errorCount += 1
                migration.lastError = "JETUP or AQUIX options not found"
                flag_modified(migration, 'errorCount')
                flag_modified(migration, 'lastError')
                session.commit()
                return False

            # Create JETUP balance
            jetup_amount = Decimal(str(jetup_qty * COST_PER_SHARE_JETUP))
            jetup_balance = ActiveBalance()
            jetup_balance.userID = user.userID
            jetup_balance.firstname = user.firstname
            jetup_balance.surname = user.surname
            jetup_balance.amount = jetup_amount
            jetup_balance.status = 'done'
            jetup_balance.reason = 'legacy_v2_gift=jetup'  # OLD FORMAT
            jetup_balance.link = ''
            jetup_balance.notes = (
                f'V2 Migration Gift: {jetup_qty} JETUP shares at ${COST_PER_SHARE_JETUP}/share'
            )
            jetup_balance.ownerTelegramID = user.telegramID
            jetup_balance.ownerEmail = user.email

            session.add(jetup_balance)
            session.flush()

            # Create AQUIX balance
            aquix_amount = Decimal(str(aquix_qty * COST_PER_SHARE_AQUIX))
            aquix_balance = ActiveBalance()
            aquix_balance.userID = user.userID
            aquix_balance.firstname = user.firstname
            aquix_balance.surname = user.surname
            aquix_balance.amount = aquix_amount
            aquix_balance.status = 'done'
            aquix_balance.reason = 'legacy_v2_gift=aquix'  # OLD FORMAT
            aquix_balance.link = ''
            aquix_balance.notes = (
                f'V2 Migration Gift: {aquix_qty} AQUIX shares at ${COST_PER_SHARE_AQUIX}/share'
            )
            aquix_balance.ownerTelegramID = user.telegramID
            aquix_balance.ownerEmail = user.email

            session.add(aquix_balance)
            session.flush()

            # Update migration: gifts created
            migration.jetupBalanceID = jetup_balance.paymentID
            migration.aquixBalanceID = aquix_balance.paymentID
            migration.status = 'purchase_done'  # Gifts done, parent may be pending

            # Check if parent assignment is needed
            default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)
            parent_needed = (
                    migration.parent and
                    migration.parent.strip() != ''
            )

            if not parent_needed:
                # No parent - use default or keep current
                if user.upline is None or user.upline == default_referrer_id:
                    user.upline = default_referrer_id
                # Already completed - no need to wait for parent
                migration.status = 'completed'
                migration.completedAt = datetime.now(timezone.utc)
                logger.info(f"V2: No parent needed for {user.email}, marked as completed")

            session.commit()

            logger.info(
                f"V2: Granted double gift to {user.email}: "
                f"{jetup_qty} JETUP (${jetup_amount}) + {aquix_qty} AQUIX (${aquix_amount})"
            )
            return True

        except Exception as e:
            logger.error(f"Error in _process_v2_migration for {user.email}: {e}")
            migration.errorCount += 1
            migration.lastError = str(e)[:500]
            if migration.errorCount > 5:
                migration.status = 'error'
            flag_modified(migration, 'errorCount')
            flag_modified(migration, 'lastError')
            session.commit()
            return False

    @staticmethod
    async def _assign_v2_parent(
            migration: LegacyMigrationV2,
            parent: User,
            session: Session
    ) -> bool:
        """Assign parent to V2 migration referral."""
        try:
            referral = LegacyMigrationService._get_user_by_email(session, migration.email)

            if not referral or not referral.emailConfirmed:
                return False

            old_upline = referral.upline

            if old_upline != parent.telegramID:
                logger.info(f"V2: Setting parent for {referral.email} to {parent.telegramID}")
                referral.upline = parent.telegramID
                migration.parentID = parent.userID

                # If gifts already created, mark as completed
                if migration.status == 'purchase_done':
                    migration.status = 'completed'
                    migration.completedAt = datetime.now(timezone.utc)
                    logger.info(f"V2: Migration for {migration.email} completed (parent assigned)")

                session.commit()

            return True

        except Exception as e:
            logger.error(f"Error assigning V2 parent for {migration.email}: {e}")
            return False

    # =========================================================================
    # NOTIFICATIONS
    # =========================================================================

    @staticmethod
    async def _send_purchase_notification(
            user: User,
            purchase: Purchase,
            migration: LegacyMigrationV1
    ):
        """Send notification when V1 purchase is created."""
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_purchase_created_user',
                {
                    'firstname': user.firstname,
                    'qty': migration.qty,
                    'project_name': migration.project,
                    'purchase_id': purchase.purchaseID
                },
                lang=user.lang
            )

            notification = Notification(
                source="legacy_migration",
                text=text,
                buttons=buttons,
                targetType="user",
                targetValue=str(user.userID),
                priority=2,
                category="legacy",
                importance="high",
                parseMode="HTML"
            )

            with get_db_session_ctx() as notif_session:
                notif_session.add(notification)
                notif_session.commit()

        except Exception as e:
            logger.error(f"Error sending purchase notification: {e}")

    @staticmethod
    async def _send_upliner_notifications(user: User, upliner: User):
        """Send notifications when upliner is assigned."""
        try:
            # User notification
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_user',
                {'firstname': user.firstname, 'upliner_name': upliner.firstname},
                lang=user.lang
            )
            user_notif = Notification(
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

            # Upliner notification
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_upliner',
                {'firstname': upliner.firstname, 'user_name': user.firstname},
                lang=upliner.lang
            )
            upliner_notif = Notification(
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
                notif_session.add(user_notif)
                notif_session.add(upliner_notif)
                notif_session.commit()

        except Exception as e:
            logger.error(f"Error sending upliner notifications: {e}")

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _normalize_email(email: str) -> str:
        """
        Normalize email (case-insensitive + Gmail dot handling).

        Same logic as old code.
        """
        if not email:
            return ""

        email = email.lower().strip()

        # Gmail special handling
        if '@gmail.com' in email:
            local, domain = email.split('@', 1)
            local = local.replace('.', '')
            return f"{local}@{domain}"

        return email

    @staticmethod
    def _get_user_by_email(session: Session, email: str) -> Optional[User]:
        """Get user by normalized email."""
        normalized = LegacyMigrationService._normalize_email(email)

        # Query all users and filter in Python (same as old code's cache)
        users = session.query(User).filter(User.email.isnot(None)).all()

        for user in users:
            if LegacyMigrationService._normalize_email(user.email) == normalized:
                return user

        return None