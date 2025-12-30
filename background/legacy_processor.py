# background/legacy_processor.py
"""
Legacy user migration processor.

Processes users from external Google Sheet (LEGACY_SHEET_ID) and:
1. Finds matching users in DB by email (with normalization)
2. Assigns upliners from legacy data
3. Creates purchases for legacy shares

Runs automatically every 10 minutes or manually via &legacy command.

V2 Migration (Return of Jedi) available via &legacy v2 command only.
"""
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

# V1 Legacy migration Google Sheet ID
LEGACY_SHEET_ID = "1mbaRSbOs0Hc98iJ3YnZnyqL5yxeSuPJCef5PFjPHpFg"

# V2 Migration Google Sheet ID (Return of Jedi)
LEGACY_V2_SHEET_ID = "16ev6awviK3UaXEY7tEYdbmW0D1nQSzJbXUFIaWK2UEc"

# V2 specific constants
OPTION_JETUP = 25
OPTION_AQUIX = 26
PROJECT_JETUP = 2
PROJECT_AQUIX = 3
COST_PER_SHARE_JETUP = Decimal("0.05")
COST_PER_SHARE_AQUIX = Decimal("0.03")
MINIMUM_GIFT_QTY = 84


# =============================================================================
# DATA STRUCTURES
# =============================================================================

class MigrationStatus(Enum):
    """Status of a legacy user record in migration pipeline."""
    PENDING = "pending"
    USER_FOUND = "user_found"
    UPLINER_ASSIGNED = "upliner_assigned"
    COMPLETED = "completed"
    ERROR = "error"


@dataclass
class LegacyUserRecord:
    """
    Represents a single row from the legacy Google Sheet.

    Sheet columns:
    - email: User email (required)
    - upliner: Upliner email (optional)
    - project: Project name (required)
    - qty: Number of shares (required)
    - IsFound: Flag set when user found in DB
    - UplinerFound: Flag set when upliner assigned
    - PurchaseDone: Flag set when purchase created
    """
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
        """Determine current migration status based on flags."""
        # Check if user found (either old format "1" or new format - userID)
        user_found = self.is_found and self.is_found != "" and self.is_found != "0"

        if user_found and self.upliner_found == "1" and self.purchase_done == "1":
            return MigrationStatus.COMPLETED
        elif self.error_count > 3:
            return MigrationStatus.ERROR
        else:
            return MigrationStatus.PENDING


@dataclass
class LegacyUserRecordV2:
    """V2 Migration record (Return of Jedi)."""
    row_index: int
    email: str
    parent: str
    value: int
    is_found: str
    upliner_found: str
    purchase_done: str
    error_count: int = 0
    last_error: str = ""

    @property
    def status(self) -> MigrationStatus:
        """Determine current migration status based on flags."""
        user_found = self.is_found and self.is_found != "" and self.is_found != "0"

        if user_found and self.upliner_found == "1" and self.purchase_done == "1":
            return MigrationStatus.COMPLETED
        elif self.error_count > 3:
            return MigrationStatus.ERROR
        else:
            return MigrationStatus.PENDING


@dataclass
class MigrationStats:
    """Statistics for a migration run."""
    # V1 stats (EXISTING - DO NOT RENAME)
    total_records: int = 0
    users_found: int = 0
    upliners_assigned: int = 0
    purchases_created: int = 0
    completed: int = 0
    errors: int = 0
    error_details: List[Tuple[str, str]] = field(default_factory=list)

    # V2 stats (NEW)
    v2_total: int = 0
    v2_users_found: int = 0
    v2_upliners_assigned: int = 0
    v2_gifts_granted: int = 0
    v2_completed: int = 0
    v2_errors: int = 0

    def add_error(self, email: str, error: str):
        """Record an error for a specific user."""
        self.errors += 1
        self.error_details.append((email, error))
        logger.error(f"Migration error for {email}: {error}")


# =============================================================================
# MAIN PROCESSOR CLASS
# =============================================================================

class LegacyUserProcessor:
    """
    Background processor for legacy user migration.

    Features:
    - Automatic processing every 10 minutes
    - Manual trigger via run_once()
    - Batch processing with configurable size
    - Email normalization (case-insensitive, Gmail dot handling)
    - Caching to reduce Google Sheets API calls
    - Exponential backoff on errors
    - V2 migration support (double gifts)
    """

    def __init__(self, check_interval: int = 600, batch_size: int = 50):
        """
        Initialize legacy user processor.

        Args:
            check_interval: Seconds between automatic processing runs (600 = 10 minutes)
            batch_size: Number of records to process in one batch
        """
        self.check_interval = check_interval
        self.batch_size = batch_size
        self._running = False
        self._processing = False

        # V1 cache
        self._cache = None
        self._cache_loaded_at = None

        # V2 cache
        self._v2_cache = None
        self._v2_cache_loaded_at = None

        # Email lookup cache (populated during processing)
        self._email_cache: Optional[dict] = None

    # =========================================================================
    # PUBLIC API
    # =========================================================================

    async def start(self):
        """Start automatic migration loop."""
        if self._running:
            logger.warning("Legacy processor already running")
            return
        self._running = True
        logger.info("Starting legacy migration processor")
        await self._run_migration_loop()

    async def stop(self):
        """Stop automatic migration loop."""
        self._running = False
        logger.info("Stopping legacy migration processor")

    async def run_once(self, migration: Optional[str] = None) -> MigrationStats:
        """
        Run migration once (for manual trigger via &legacy command).

        Args:
            migration: Optional filter - "v2" to run V2 only, None for original V1

        Returns:
            MigrationStats with processing results

        Raises:
            RuntimeError: If migration is already in progress
        """
        if self._processing:
            raise RuntimeError("Migration already in progress")

        self._processing = True
        try:
            if migration == "v2":
                # V2 migration only
                return await self._process_v2_users()
            else:
                # Default: original V1 migration only
                return await self._process_legacy_users()
        finally:
            self._processing = False
            self._email_cache = None

    # =========================================================================
    # EMAIL NORMALIZATION
    # =========================================================================

    @staticmethod
    def normalize_email(email: str) -> str:
        """
        Universal email normalization for case-insensitive search.
        For Gmail also removes dots in local part.

        Examples:
            "John.Doe@Gmail.COM" -> "johndoe@gmail.com"
            "User@Example.com" -> "user@example.com"
        """
        if not email:
            return ""

        email = email.lower().strip()

        # Special handling for Gmail - remove dots from local part
        if '@gmail.com' in email:
            local, domain = email.split('@', 1)
            local = local.replace('.', '')
            return f"{local}@{domain}"

        return email

    # =========================================================================
    # OPTIMIZED USER LOOKUP
    # =========================================================================

    def _build_email_cache(self, session: Session) -> dict:
        """
        Build email lookup cache for fast user search.

        Returns:
            Dict mapping normalized_email -> User object
        """
        if self._email_cache is not None:
            return self._email_cache

        logger.debug("Building email lookup cache...")

        # Load all users with only needed fields
        users = session.query(User).all()

        cache = {}
        for user in users:
            if user.email:
                normalized = self.normalize_email(user.email)
                cache[normalized] = user

        self._email_cache = cache
        logger.debug(f"Email cache built with {len(cache)} entries")

        return cache

    def _get_user_by_email(self, session: Session, email: str) -> Optional[User]:
        """
        Get user from DB by email with normalization support.
        Uses cached lookup for performance.

        Args:
            session: Database session
            email: Email to search (will be normalized)

        Returns:
            User object or None if not found
        """
        normalized_email = self.normalize_email(email)

        # Use cache if available
        cache = self._build_email_cache(session)
        return cache.get(normalized_email)

    def _get_user_from_legacy_record(self, session: Session, user: LegacyUserRecord) -> Optional[User]:
        """
        Get user from DB using legacy record.
        Wrapper around _get_user_by_email for compatibility.
        """
        return self._get_user_by_email(session, user.email)

    # =========================================================================
    # MIGRATION LOOP
    # =========================================================================

    async def _run_migration_loop(self):
        """Main migration loop with error handling and backoff."""
        consecutive_errors = 0
        max_consecutive_errors = 5

        while self._running:
            try:
                self._processing = True

                # Run V1 migration only (default behavior)
                stats = await self._process_legacy_users()

                self._processing = False
                self._email_cache = None

                if any([stats.users_found, stats.upliners_assigned, stats.purchases_created]):
                    logger.info(
                        f"Migration progress: found={stats.users_found}, "
                        f"upliners={stats.upliners_assigned}, "
                        f"purchases={stats.purchases_created}"
                    )

                if stats.errors > 0:
                    consecutive_errors += 1
                    sleep_time = min(self.check_interval * (2 ** consecutive_errors), 3600)
                else:
                    consecutive_errors = 0
                    sleep_time = self.check_interval

                if consecutive_errors >= max_consecutive_errors:
                    logger.error("Too many consecutive errors, stopping legacy processor")
                    break

                await asyncio.sleep(sleep_time)

            except Exception as e:
                self._processing = False
                consecutive_errors += 1
                logger.error(f"Critical error in migration loop: {e}", exc_info=True)
                if consecutive_errors >= max_consecutive_errors:
                    break
                await asyncio.sleep(self.check_interval * consecutive_errors)

    # =========================================================================
    # V1 CACHE MANAGEMENT
    # =========================================================================

    async def _load_cache(self, force: bool = False):
        """
        Load all records from Google Sheets into memory cache.

        Args:
            force: Force reload even if cache exists
        """
        if not force and self._cache is not None:
            logger.debug("Using existing Google Sheets cache")
            return

        try:
            logger.info("Loading legacy users from Google Sheets to cache...")

            sheets_client, _ = await get_google_services()

            def _read_sheet():
                sheet = sheets_client.open_by_key(LEGACY_SHEET_ID).worksheet("Users")
                return sheet.get_all_records()

            records = await asyncio.to_thread(_read_sheet)

            self._cache = records
            self._cache_loaded_at = datetime.now()
            logger.info(f"Cache loaded: {len(records)} records at {self._cache_loaded_at}")

        except Exception as e:
            logger.error(f"Failed to load cache from Google Sheets: {e}", exc_info=True)
            raise

    async def _get_legacy_users(self) -> List[LegacyUserRecord]:
        """
        Load and parse legacy users from cached Google Sheets data.
        Returns only users that are not yet completed.
        """
        try:
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
                    # Validation - check required fields
                    required_fields = ['email', 'project', 'qty']
                    if not all(record.get(field) for field in required_fields):
                        continue

                    email = record['email'].strip().lower()

                    # Basic email validation
                    if '@' not in email or '.' not in email:
                        continue

                    # Parse quantity
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

    # =========================================================================
    # V1 MAIN PROCESSING
    # =========================================================================

    async def _process_legacy_users(self) -> MigrationStats:
        """
        Process legacy users from Google Sheets.
        Uses batching and per-user sessions for isolation.
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
                        # Clear email cache for fresh data in each session
                        self._email_cache = None

                        result = await self._process_single_user(session, user)

                        if result == "user_found":
                            stats.users_found += 1
                        elif result == "purchase_created":
                            stats.purchases_created += 1
                        elif result == "completed":
                            stats.completed += 1

                    except Exception as e:
                        stats.add_error(user.email, str(e))
                        logger.error(f"Error processing user {user.email}: {e}", exc_info=True)

            # Sleep between batches to avoid overwhelming the system
            if i + self.batch_size < len(legacy_users):
                await asyncio.sleep(2)

        return stats

    async def _process_single_user(self, session: Session, user: LegacyUserRecord) -> Optional[str]:
        """
        Process a single legacy user through the migration pipeline.
        Each step checks the current state and proceeds accordingly.

        Steps are independent - purchase is created even if upliner assignment fails.

        Returns:
            String indicating what action was taken:
            - "user_found": User was found in DB
            - "purchase_created": Purchase was created (may or may not have upliner)
            - "completed": User already completed
            - None: No action taken
        """
        try:
            # Step 1: Find user in DB
            user_found = user.is_found and user.is_found != "" and user.is_found != "0"
            if not user_found:
                if await self._find_user(session, user):
                    return "user_found"
                return None

            # Step 2: Assign upliner (OPTIONAL - doesn't block Step 3)
            if user.upliner_found != "1" and user.upliner:
                try:
                    await self._assign_upliner(session, user)
                except Exception as e:
                    logger.warning(f"Could not assign upliner for {user.email}, continuing to purchase: {e}")

            # Step 3: Create purchase (ALWAYS runs if user is found)
            if user.purchase_done != "1":
                if await self._create_purchase(session, user):
                    return "purchase_created"
                return None

            return "completed"

        except Exception as e:
            logger.error(f"Error in _process_single_user for {user.email}: {e}")
            return None

    # =========================================================================
    # V1 STEP 1: FIND USER
    # =========================================================================

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

    # =========================================================================
    # V1 STEP 2: ASSIGN UPLINER
    # =========================================================================

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

            # Find upliner by email (using optimized lookup)
            upliner = self._get_user_by_email(session, user.upliner)

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

    # =========================================================================
    # V1 STEP 3: CREATE PURCHASE
    # =========================================================================

    async def _create_purchase(self, session: Session, user: LegacyUserRecord) -> bool:
        """
        Create a purchase for legacy user.
        Protection from duplicates is based on PurchaseDone flag in Google Sheets.
        """
        try:
            # Get user from DB
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

            # Create Purchase
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
            for field_name, value in purchase_fields.items():
                setattr(purchase, field_name, value)

            session.add(purchase)
            session.flush()

            # Prepare notes
            notes_text = 'Legacy shares migration'
            if has_other_legacy:
                notes_text += ' (additional purchase)'
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
            for field_name, value in balance_fields.items():
                setattr(balance_record, field_name, value)

            session.add(balance_record)
            session.commit()

            await self._update_sheet(user.row_index, 'PurchaseDone', '1')
            await self._send_purchase_notification(db_user, purchase, user)

            logger.info(
                f"Created legacy purchase {purchase.purchaseID} for user {db_user.email} "
                f"(${total_price})"
            )
            return True

        except Exception as e:
            logger.error(f"Error creating legacy purchase for {user.email}: {e}")
            return False

    # =========================================================================
    # V1 GOOGLE SHEETS UPDATE
    # =========================================================================

    async def _update_sheet(self, row_index: int, field_name: str, value: str):
        """
        Update a cell in the legacy Google Sheet.
        Retries up to 3 times with exponential backoff.
        """
        field_columns = {
            'IsFound': 'F',
            'UplinerFound': 'G',
            'PurchaseDone': 'H'
        }

        if field_name not in field_columns:
            logger.warning(f"Unknown field name: {field_name}")
            return

        for attempt in range(3):
            try:
                sheets_client, _ = await get_google_services()

                def _write_cell():
                    sheet = sheets_client.open_by_key(LEGACY_SHEET_ID).worksheet("Users")
                    cell_address = f"{field_columns[field_name]}{row_index}"
                    sheet.update(cell_address, [[value]])

                await asyncio.to_thread(_write_cell)
                logger.debug(f"Updated sheet {field_columns[field_name]}{row_index} = {value}")
                return
            except Exception as e:
                if attempt == 2:
                    logger.error(f"Failed to update sheet {field_name} after 3 attempts: {e}")
                else:
                    await asyncio.sleep(2 ** attempt)

    # =========================================================================
    # V1 NOTIFICATIONS
    # =========================================================================

    async def _send_welcome_notification(self, user: User, legacy_user: LegacyUserRecord):
        """Send welcome notification when user is found in DB."""
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_user_welcome',
                {
                    'firstname': user.firstname,
                    'project_name': legacy_user.project,
                    'qty': legacy_user.qty
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

            with get_db_session_ctx() as session:
                session.add(notification)
                session.commit()

        except Exception as e:
            logger.error(f"Error sending legacy welcome notification: {e}")

    async def _send_upliner_notifications(self, user: User, upliner: User):
        """Send notifications to both user and upliner when assignment is made."""
        try:
            # User notification
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_upliner_assigned_user',
                {
                    'firstname': user.firstname,
                    'upliner_name': upliner.firstname
                },
                lang=user.lang
            )
            user_notification = Notification(
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
                {
                    'firstname': upliner.firstname,
                    'user_name': user.firstname
                },
                lang=upliner.lang
            )
            upliner_notification = Notification(
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

            with get_db_session_ctx() as session:
                session.add(user_notification)
                session.add(upliner_notification)
                session.commit()

        except Exception as e:
            logger.error(f"Error sending upliner assigned notifications: {e}")

    async def _send_purchase_notification(self, user: User, purchase: Purchase, legacy_user: LegacyUserRecord):
        """Send notification when purchase is created."""
        try:
            text, buttons = await MessageTemplates.get_raw_template(
                'legacy_purchase_created_user',
                {
                    'firstname': user.firstname,
                    'qty': legacy_user.qty,
                    'project_name': legacy_user.project,
                    'purchase_id': purchase.purchaseID
                },
                lang=user.lang
            )

            user_notification = Notification(
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

            with get_db_session_ctx() as session:
                session.add(user_notification)
                session.commit()

        except Exception as e:
            logger.error(f"Error sending legacy purchase notifications: {e}")

    # =========================================================================
    # V2 PROCESSING (NEW)
    # =========================================================================

    async def _load_v2_cache(self, force: bool = False):
        """Load V2 records from Google Sheets."""
        if not force and self._v2_cache is not None:
            logger.debug("Using existing V2 cache")
            return

        try:
            logger.info("Loading V2 migration data from Google Sheets...")

            sheets_client, _ = await get_google_services()

            def _read_v2():
                sheet = sheets_client.open_by_key(LEGACY_V2_SHEET_ID).worksheet("Users")
                return sheet.get_all_records()

            records = await asyncio.to_thread(_read_v2)

            self._v2_cache = records
            self._v2_cache_loaded_at = datetime.now()
            logger.info(f"V2 cache loaded: {len(records)} records")

        except Exception as e:
            logger.error(f"Failed to load V2 cache: {e}", exc_info=True)
            raise

    async def _get_v2_users(self) -> List[LegacyUserRecordV2]:
        """Get pending V2 migration records."""
        try:
            if self._v2_cache is None:
                await self._load_v2_cache()

            records = self._v2_cache
            if not records:
                return []

            v2_users = []
            for idx, record in enumerate(records, start=2):
                try:
                    if not record.get('email'):
                        continue

                    email = record['email'].strip().lower()
                    if '@' not in email:
                        continue

                    value = 0
                    try:
                        value = int(record.get('value', 0))
                    except (ValueError, TypeError):
                        pass

                    user = LegacyUserRecordV2(
                        row_index=idx,
                        email=email,
                        parent=record.get('parent', '').strip(),
                        value=value,
                        is_found=str(record.get('IsFound', '')),
                        upliner_found=str(record.get('UplinerFound', '')),
                        purchase_done=str(record.get('PurchaseDone', ''))
                    )

                    if user.status != MigrationStatus.COMPLETED:
                        v2_users.append(user)

                except Exception as e:
                    logger.error(f"Error parsing V2 record {idx}: {e}")
                    continue

            logger.info(f"Found {len(v2_users)} pending V2 users")
            return v2_users

        except Exception as e:
            logger.error(f"Error loading V2 users: {e}")
            return []

    async def _process_v2_users(self) -> MigrationStats:
        """Process V2 migration users."""
        stats = MigrationStats()

        await self._load_v2_cache(force=True)
        v2_users = await self._get_v2_users()

        if not v2_users:
            return stats

        stats.v2_total = len(v2_users)

        for i in range(0, len(v2_users), self.batch_size):
            batch = v2_users[i:i + self.batch_size]
            logger.info(f"Processing V2 batch: {len(batch)} users")

            for user in batch:
                with get_db_session_ctx() as session:
                    try:
                        self._email_cache = None
                        result = await self._process_v2_single_user(session, user)

                        if result == "user_found":
                            stats.v2_users_found += 1
                        elif result == "upliner_assigned":
                            stats.v2_upliners_assigned += 1
                        elif result == "gifts_granted":
                            stats.v2_gifts_granted += 1
                        elif result == "completed":
                            stats.v2_completed += 1

                    except Exception as e:
                        stats.v2_errors += 1
                        logger.error(f"Error processing V2 user {user.email}: {e}", exc_info=True)

            if i + self.batch_size < len(v2_users):
                await asyncio.sleep(2)

        return stats

    async def _process_v2_single_user(self, session: Session, user: LegacyUserRecordV2) -> Optional[str]:
        """Process single V2 user."""
        try:
            user_found = user.is_found and user.is_found != "" and user.is_found != "0"

            if not user_found:
                if await self._v2_find_user(session, user):
                    return "user_found"
                return None

            if user.upliner_found != "1" and user.parent:
                if await self._v2_assign_upliner(session, user):
                    return "upliner_assigned"
                return None

            if user.purchase_done != "1":
                if await self._v2_grant_double_gift(session, user):
                    return "gifts_granted"
                return None

            return "completed"

        except Exception as e:
            logger.error(f"Error in _process_v2_single_user for {user.email}: {e}")
            return None

    async def _v2_find_user(self, session: Session, user: LegacyUserRecordV2) -> bool:
        """Find user for V2 migration."""
        try:
            db_user = self._get_user_by_email(session, user.email)
            if not db_user:
                logger.debug(f"V2: User {user.email} not found yet")
                return False

            logger.info(f"V2: Found user {user.email} -> userID={db_user.userID}")
            await self._update_v2_sheet(user.row_index, 'IsFound', str(db_user.userID))
            return True

        except Exception as e:
            logger.error(f"V2: Error finding user {user.email}: {e}")
            return False

    async def _v2_assign_upliner(self, session: Session, user: LegacyUserRecordV2) -> bool:
        """Assign upliner for V2 migration."""
        try:
            if not user.parent:
                logger.debug(f"V2: No parent for {user.email}")
                return False

            db_user = self._get_user_by_email(session, user.email)
            if not db_user:
                return False

            parent = self._get_user_by_email(session, user.parent)
            if not parent:
                logger.warning(f"V2: Parent {user.parent} not found for {user.email}")
                return False

            old_upline = db_user.upline if hasattr(db_user, 'upline') else None

            if old_upline != parent.telegramID:
                logger.info(f"V2: Setting parent for {user.email} to {parent.telegramID}")
                db_user.upline = parent.telegramID
                session.commit()

            await self._update_v2_sheet(user.row_index, 'UplinerFound', '1')
            return True

        except Exception as e:
            logger.error(f"V2: Error assigning parent for {user.email}: {e}")
            return False

    async def _v2_grant_double_gift(self, session: Session, user: LegacyUserRecordV2) -> bool:
        """Grant double gift (JETUP + AQUIX) for V2 migration."""
        try:
            db_user = self._get_user_by_email(session, user.email)
            if not db_user:
                return False

            # Calculate gift quantities
            if user.value == 0:
                jetup_qty = MINIMUM_GIFT_QTY
                aquix_qty = MINIMUM_GIFT_QTY
            else:
                jetup_qty = int(user.value / COST_PER_SHARE_JETUP)
                aquix_qty = int(user.value / COST_PER_SHARE_AQUIX)

            # Get options
            jetup_option = session.query(Option).filter_by(optionID=OPTION_JETUP).first()
            aquix_option = session.query(Option).filter_by(optionID=OPTION_AQUIX).first()

            if not jetup_option or not aquix_option:
                logger.error("V2: JETUP or AQUIX options not found")
                return False

            # Create JETUP balance
            jetup_balance = ActiveBalance()
            jetup_amount = Decimal(str(jetup_qty * COST_PER_SHARE_JETUP))
            jetup_fields = {
                'userID': db_user.userID,
                'firstname': db_user.firstname,
                'surname': db_user.surname,
                'amount': jetup_amount,
                'status': 'done',
                'reason': f'legacy_v2_gift=jetup',
                'link': '',
                'notes': f'V2 Migration Gift: {jetup_qty} JETUP shares at ${COST_PER_SHARE_JETUP}/share',
                'ownerTelegramID': db_user.telegramID,
                'ownerEmail': db_user.email
            }
            for field, value in jetup_fields.items():
                setattr(jetup_balance, field, value)
            session.add(jetup_balance)

            # Create AQUIX balance
            aquix_balance = ActiveBalance()
            aquix_amount = Decimal(str(aquix_qty * COST_PER_SHARE_AQUIX))
            aquix_fields = {
                'userID': db_user.userID,
                'firstname': db_user.firstname,
                'surname': db_user.surname,
                'amount': aquix_amount,
                'status': 'done',
                'reason': f'legacy_v2_gift=aquix',
                'link': '',
                'notes': f'V2 Migration Gift: {aquix_qty} AQUIX shares at ${COST_PER_SHARE_AQUIX}/share',
                'ownerTelegramID': db_user.telegramID,
                'ownerEmail': db_user.email
            }
            for field, value in aquix_fields.items():
                setattr(aquix_balance, field, value)
            session.add(aquix_balance)

            session.commit()

            await self._update_v2_sheet(user.row_index, 'PurchaseDone', '1')

            logger.info(
                f"V2: Granted double gift to {db_user.email}: "
                f"{jetup_qty} JETUP (${jetup_amount}) + {aquix_qty} AQUIX (${aquix_amount})"
            )
            return True

        except Exception as e:
            logger.error(f"V2: Error granting gift to {user.email}: {e}")
            return False

    async def _update_v2_sheet(self, row_index: int, field_name: str, value: str):
        """Update V2 Google Sheet."""
        field_columns = {
            'IsFound': 'D',
            'UplinerFound': 'E',
            'PurchaseDone': 'F'
        }

        if field_name not in field_columns:
            logger.warning(f"V2: Unknown field: {field_name}")
            return

        for attempt in range(3):
            try:
                sheets_client, _ = await get_google_services()

                def _write_v2():
                    sheet = sheets_client.open_by_key(LEGACY_V2_SHEET_ID).worksheet("Users")
                    cell = f"{field_columns[field_name]}{row_index}"
                    sheet.update(cell, [[value]])

                await asyncio.to_thread(_write_v2)
                logger.debug(f"V2: Updated {field_columns[field_name]}{row_index} = {value}")
                return
            except Exception as e:
                if attempt == 2:
                    logger.error(f"V2: Failed to update after 3 attempts: {e}")
                else:
                    await asyncio.sleep(2 ** attempt)


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

legacy_processor = LegacyUserProcessor()