import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from decimal import Decimal
from sqlalchemy.orm import Session

from core.google_services import get_google_services
from models import User, Project, Purchase, ActiveBalance, Notification, Option
from core.db import get_db_session_ctx
from core.templates import MessageTemplates
from config import Config

logger = logging.getLogger(__name__)

LEGACY_SHEET_ID = "1mbaRSbOs0Hc98iJ3YnZnyqL5yxeSuPJCef5PFjPHpFg"


class MigrationStatus(Enum):
    PENDING = "pending"
    USER_FOUND = "user_found"
    UPLINER_ASSIGNED = "upliner_assigned"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class LegacyUserRecord:
    row_index: int
    email: str
    upliner: str
    project: str
    qty: int
    is_found: str
    upliner_found: str
    purchase_done: str
    error_count: int = 0
    last_error: str = ""

    @property
    def status(self) -> MigrationStatus:
        # Check if user found (either old format "1" or new format - userID)
        user_found = self.is_found and self.is_found != "" and self.is_found != "0"

        if user_found and self.upliner_found == "1" and self.purchase_done == "1":
            return MigrationStatus.COMPLETED
        elif self.error_count > 3:
            return MigrationStatus.ERROR
        else:
            return MigrationStatus.PENDING


@dataclass
class MigrationStats:
    total_records: int = 0
    users_found: int = 0
    upliners_assigned: int = 0
    purchases_created: int = 0
    completed: int = 0
    errors: int = 0
    error_details: List[Tuple[str, str]] = field(default_factory=list)

    def add_error(self, email: str, error: str):
        self.errors += 1
        self.error_details.append((email, error))
        logger.error(f"Migration error for {email}: {error}")


class LegacyUserProcessor:
    def __init__(self, check_interval: int = 600, batch_size: int = 50):
        """
        Initialize legacy user processor.

        Args:
            check_interval: Seconds between automatic processing runs (600 = 10 minutes)
            batch_size: Number of records to process in one batch (increased from 10 to 50)
        """
        self.check_interval = check_interval
        self.batch_size = batch_size
        self._running = False
        self._processing = False  # Flag for active processing (for lock)
        self._cache = None  # Cache for Google Sheets data
        self._cache_loaded_at = None  # Timestamp of last cache load

    @staticmethod
    def normalize_email(email: str) -> str:
        """
        Universal email normalization for case-insensitive search.
        For Gmail also removes dots in local part.
        """
        if not email:
            return ""

        email = email.lower().strip()

        # Special handling for Gmail
        if '@gmail.com' in email:
            local, domain = email.split('@', 1)
            local = local.replace('.', '')  # Remove dots
            return f"{local}@{domain}"

        return email

    async def start(self):
        if self._running:
            logger.warning("Legacy processor already running")
            return
        self._running = True
        logger.info("Starting legacy migration processor")
        await self._run_migration_loop()

    async def stop(self):
        self._running = False
        logger.info("Stopping legacy migration processor")

    async def _run_migration_loop(self):
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self._running:
            try:
                stats = await self._process_legacy_users()

                if any([stats.users_found, stats.upliners_assigned, stats.purchases_created]):
                    logger.info(
                        f"Migration progress: found={stats.users_found}, upliners={stats.upliners_assigned}, purchases={stats.purchases_created}")

                if stats.errors > 0:
                    consecutive_errors += 1
                    sleep_time = min(self.check_interval * (2 ** consecutive_errors), 3600)
                else:
                    consecutive_errors = 0
                    sleep_time = self.check_interval

                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive errors, stopping")
                    break

                await asyncio.sleep(sleep_time)

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Critical error in migration loop: {e}", exc_info=True)
                if consecutive_errors >= max_consecutive_errors:
                    break
                await asyncio.sleep(self.check_interval * consecutive_errors)

    async def _load_cache(self, force: bool = False):
        """
        Load all records from Google Sheets into memory cache.

        Args:
            force: Force reload even if cache exists
        """
        if not force and self._cache is not None:
            logger.debug("Using existing cache")
            return

        try:
            logger.info("Loading legacy users from Google Sheets to cache...")
            sheets_client, _ = get_google_services()
            sheet = sheets_client.open_by_key(LEGACY_SHEET_ID).worksheet("Users")
            records = sheet.get_all_records()

            self._cache = records
            self._cache_loaded_at = datetime.now()
            logger.info(f"Cache loaded: {len(records)} records at {self._cache_loaded_at}")

        except Exception as e:
            logger.error(f"Failed to load cache from Google Sheets: {e}", exc_info=True)
            raise

    async def _get_legacy_users(self) -> List[LegacyUserRecord]:
        """
        Load and parse legacy users from cached Google Sheets data.
        No duplicate filtering - each row is processed independently.
        """
        try:
            # Use cached data instead of loading from sheets
            if self._cache is None:
                await self._load_cache()

            records = self._cache

            if not records:
                logger.warning("No records found in cache")
                return []

            logger.info(f"Processing {len(records)} cached records")

            legacy_users = []

            for idx, record in enumerate(records, start=2):
                try:
                    # Validation
                    required_fields = ['email', 'project', 'qty']
                    if not all(record.get(field) for field in required_fields):
                        continue

                    email = record['email'].strip().lower()

                    # NO duplicate check - each row is independent

                    if '@' not in email or '.' not in email:
                        continue

                    try:
                        qty = int(record['qty'])
                        if qty <= 0:
                            continue
                    except (ValueError, TypeError):
                        continue

                    legacy_user = LegacyUserRecord(
                        row_index=idx,
                        email=email,
                        upliner=record.get('upliner', '').strip(),
                        project=record['project'].strip(),
                        qty=qty,
                        is_found=str(record.get('IsFound', '')),
                        upliner_found=str(record.get('UplinerFound', '')),
                        purchase_done=str(record.get('PurchaseDone', ''))
                    )

                    # Only add users that are not completed
                    if legacy_user.status != MigrationStatus.COMPLETED:
                        legacy_users.append(legacy_user)

                except Exception as e:
                    logger.error(f"Error parsing record {idx}: {e}")
                    continue

            logger.info(f"Found {len(legacy_users)} pending users from {len(records)} total")
            return legacy_users

        except Exception as e:
            logger.error(f"Error loading legacy users: {e}")
            return []

    async def _process_legacy_users(self) -> MigrationStats:
        """
        Process legacy users from Google Sheets.
        Uses per-user sessions for better isolation and commit control.
        """
        stats = MigrationStats()

        # Reload cache from sheets
        await self._load_cache(force=True)

        legacy_users = await self._get_legacy_users()
        if not legacy_users:
            return stats

        stats.total_records = len(legacy_users)

        # Process users in batches
        for i in range(0, len(legacy_users), self.batch_size):
            batch = legacy_users[i:i + self.batch_size]
            logger.info(f"Processing batch {i // self.batch_size + 1}: {len(batch)} users")

            for user in batch:
                with get_db_session_ctx() as session:
                    try:
                        success = await self._process_single_user(session, user)
                        if success:
                            if user.is_found and user.is_found != "" and user.is_found != "0":
                                if user.upliner_found == "1":
                                    if user.purchase_done == "1":
                                        stats.completed += 1
                                    else:
                                        stats.purchases_created += 1
                                else:
                                    stats.upliners_assigned += 1
                            else:
                                stats.users_found += 1
                    except Exception as e:
                        stats.add_error(user.email, str(e))
                        logger.error(f"Error processing user {user.email}: {e}", exc_info=True)

            # Sleep between batches to avoid overwhelming the system
            if i + self.batch_size < len(legacy_users):
                await asyncio.sleep(2)

        return stats

    def _get_user_from_legacy_record(self, session: Session, user: LegacyUserRecord) -> Optional[User]:
        """
        Get user from DB using legacy record with normalization support.
        Searches by normalized email for case-insensitive and Gmail-compatible matching.
        """
        # Normalize the email from the record
        normalized_email = self.normalize_email(user.email)

        # Get all users
        all_users = session.query(User).all()

        # Search by normalized email
        for db_user in all_users:
            if self.normalize_email(db_user.email) == normalized_email:
                return db_user

        return None

    async def _process_single_user(self, session: Session, user: LegacyUserRecord) -> bool:
        """
        Process a single legacy user through the migration pipeline.
        Each step checks the current state and proceeds accordingly.
        """
        try:
            # Step 1: Find user in DB
            user_found = user.is_found and user.is_found != "" and user.is_found != "0"
            if not user_found:
                if await self._find_user(session, user):
                    return True
                return False

            # Step 2: Assign upliner
            if user.upliner_found != "1" and user.upliner:
                if await self._assign_upliner(session, user):
                    return True
                return False

            # Step 3: Create purchase
            if user.purchase_done != "1":
                if await self._create_purchase(session, user):
                    return True
                return False

            return False

        except Exception as e:
            logger.error(f"Error in _process_single_user for {user.email}: {e}")
            return False

    async def _find_user(self, session: Session, user: LegacyUserRecord) -> bool:
        """
        Find user in database by email with normalization support.
        """
        try:
            db_user = self._get_user_from_legacy_record(session, user)
            if not db_user:
                logger.debug(f"User {user.email} (row {user.row_index}) not found in DB yet")
                return False

            logger.info(f"LEGACY: Found user {user.email} (row {user.row_index}) -> userID={db_user.userID}")
            await self._update_sheet(user.row_index, 'IsFound', str(db_user.userID))
            await self._send_welcome_notification(db_user, user)
            return True

        except Exception as e:
            logger.error(f"Error finding user {user.email} row {user.row_index}: {e}")
            return False

    async def _assign_upliner(self, session: Session, user: LegacyUserRecord) -> bool:
        """
        Assign upliner to user if specified in legacy data.
        """
        try:
            if not user.upliner:
                logger.debug(f"No upliner specified for {user.email}")
                return False

            # Get current user
            db_user = self._get_user_from_legacy_record(session, user)
            if not db_user:
                logger.debug(f"User {user.email} not found yet, will try again later")
                return False

            # Find upliner by email
            all_users = session.query(User).all()
            normalized_upliner_email = self.normalize_email(user.upliner)

            upliner = None
            for u in all_users:
                if self.normalize_email(u.email) == normalized_upliner_email:
                    upliner = u
                    break

            if not upliner:
                logger.warning(f"Upliner {user.upliner} not found for user {user.email}")
                return False

            # Check if upliner assignment is needed
            old_upline = db_user.upline if hasattr(db_user, 'upline') else None

            # Get default referrer ID from config
            default_referrer_id = Config.get(Config.DEFAULT_REFERRER_ID)

            if old_upline != upliner.telegramID:
                if old_upline and old_upline != default_referrer_id:
                    logger.info(
                        f"LEGACY: Changing upliner for {user.email} (row {user.row_index}) "
                        f"from {old_upline} to {upliner.telegramID}"
                    )
                else:
                    logger.info(
                        f"LEGACY: Setting upliner for {user.email} (row {user.row_index}) "
                        f"to {upliner.telegramID}"
                    )

                db_user.upline = upliner.telegramID
                session.commit()
                await self._send_upliner_notifications(db_user, upliner)
            else:
                logger.debug(f"User {db_user.email} already has correct upliner {upliner.telegramID}")

            await self._update_sheet(user.row_index, 'UplinerFound', '1')
            return True

        except Exception as e:
            logger.error(f"Error assigning upliner for {user.email} row {user.row_index}: {e}")
            return False

    async def _create_purchase(self, session: Session, user: LegacyUserRecord) -> bool:
        """
        Create a purchase for legacy user.
        Protection from duplicates is based on PurchaseDone flag in Google Sheets.
        """
        try:
            # Get user from DB using proper method
            db_user = self._get_user_from_legacy_record(session, user)
            if not db_user:
                logger.debug(f"User {user.email} not found yet, will try again later")
                return False

            # Find project
            project = session.query(Project).filter_by(projectName=user.project).first()
            if not project:
                logger.error(f"Project {user.project} not found for legacy user {user.email}")
                return False

            # Find first option for this project
            option = session.query(Option).filter_by(projectID=project.projectID).first()
            if not option:
                logger.error(f"No options found for project {user.project}")
                return False

            # Check if this is an additional purchase (for notes)
            has_other_legacy = session.query(ActiveBalance).filter(
                ActiveBalance.userID == db_user.userID,
                ActiveBalance.reason.like('legacy_migration=%')
            ).first() is not None

            # Create purchase with correct price
            total_price = Decimal(str(option.costPerShare * user.qty))

            # Create Purchase через setattr
            purchase = Purchase()
            purchase_fields = {
                'userID': db_user.userID,
                'projectID': project.projectID,
                'projectName': project.projectName,
                'optionID': option.optionID,
                'packQty': user.qty,
                'packPrice': total_price,
                'ownerTelegramID': db_user.telegramID,
                'ownerEmail': db_user.email
            }
            for field, value in purchase_fields.items():
                setattr(purchase, field, value)

            session.add(purchase)
            session.flush()

            # Prepare notes
            notes_text = f'Legacy shares migration'
            if has_other_legacy:
                notes_text += f' (additional purchase)'
            notes_text += f': {user.qty} shares of {project.projectName} at {option.costPerShare} per share'

            # Add balance record
            balance_record = ActiveBalance()
            balance_fields = {
                'userID': db_user.userID,
                'firstname': db_user.firstname,
                'surname': db_user.surname,
                'amount': total_price,
                'status': 'done',
                'reason': f'legacy_migration={purchase.purchaseID}',
                'link': '',
                'notes': notes_text,
                'ownerTelegramID': db_user.telegramID,
                'ownerEmail': db_user.email
            }
            for field, value in balance_fields.items():
                setattr(balance_record, field, value)

            session.add(balance_record)
            session.commit()

            await self._update_sheet(user.row_index, 'PurchaseDone', '1')
            await self._send_purchase_notification(db_user, purchase, user)

            logger.info(f"Created legacy purchase {purchase.purchaseID} for user {db_user.email} "
                        f"(${total_price})")
            return True

        except Exception as e:
            logger.error(f"Error creating legacy purchase for {user.email}: {e}")
            return False

    async def _update_sheet(self, row_index: int, field_name: str, value: str):
        field_columns = {'IsFound': 'F', 'UplinerFound': 'G', 'PurchaseDone': 'H'}

        if field_name not in field_columns:
            return

        for attempt in range(3):
            try:
                sheets_client, _ = get_google_services()
                sheet = sheets_client.open_by_key(LEGACY_SHEET_ID).worksheet("Users")
                cell_address = f"{field_columns[field_name]}{row_index}"
                sheet.update(cell_address, value)
                logger.debug(f"Updated sheet {cell_address} = {value}")
                return
            except Exception as e:
                if attempt == 2:
                    logger.error(f"Failed to update sheet {field_name}: {e}")
                else:
                    await asyncio.sleep(2 ** attempt)

    async def _send_welcome_notification(self, user: User, legacy_user: LegacyUserRecord):
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_user_welcome',
                {'firstname': user.firstname, 'project_name': legacy_user.project, 'qty': legacy_user.qty},
                lang=user.lang
            )

            notification = Notification(
                source="legacy_migration", text=text, buttons=buttons,
                targetType="user", targetValue=str(user.userID),
                priority=2, category="legacy", importance="high", parseMode="HTML"
            )

            with get_db_session_ctx() as session:
                session.add(notification)
                session.commit()
        except Exception as e:
            logger.error(f"Error sending legacy welcome notification: {e}")

    async def _send_upliner_notifications(self, user: User, upliner: User):
        try:
            # User notification
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_user',
                {'firstname': user.firstname, 'upliner_name': upliner.firstname},
                lang=user.lang
            )
            user_notification = Notification(
                source="legacy_migration", text=text, buttons=buttons,
                targetType="user", targetValue=str(user.userID),
                priority=2, category="legacy", importance="normal", parseMode="HTML"
            )

            # Upliner notification
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_upliner',
                {'firstname': upliner.firstname, 'user_name': user.firstname},
                lang=upliner.lang
            )
            upliner_notification = Notification(
                source="legacy_migration", text=text, buttons=buttons,
                targetType="user", targetValue=str(upliner.userID),
                priority=2, category="legacy", importance="normal", parseMode="HTML"
            )

            with get_db_session_ctx() as session:
                session.add(user_notification)
                session.add(upliner_notification)
                session.commit()
        except Exception as e:
            logger.error(f"Error sending upliner assigned notifications: {e}")

    async def _send_purchase_notification(self, user: User, purchase: Purchase, legacy_user: LegacyUserRecord):
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_purchase_created_user',
                {
                    'firstname': user.firstname, 'qty': legacy_user.qty,
                    'project_name': legacy_user.project, 'purchase_id': purchase.purchaseID
                },
                lang=user.lang
            )

            user_notification = Notification(
                source="legacy_migration", text=text, buttons=buttons,
                targetType="user", targetValue=str(user.userID),
                priority=2, category="legacy", importance="high", parseMode="HTML"
            )

            with get_db_session_ctx() as session:
                session.add(user_notification)
                session.commit()
        except Exception as e:
            logger.error(f"Error sending legacy purchase notifications: {e}")


legacy_processor = LegacyUserProcessor()