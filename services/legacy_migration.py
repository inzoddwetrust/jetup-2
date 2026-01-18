# models/legacy_migration.py
"""
Legacy Migration Models - V2.0

Temporary feature for migrating users from old Darwin/Aquix projects.
Will be deleted when migration is complete.

Tables:
- legacy_migration_v1: Darwin legacy shares restoration
- legacy_migration_v2: Aquix double gift migration (JETUP + AQUIX)

Statuses:
- pending: Not processed yet
- done: Fully completed (IsFound + PurchaseDone + UplinerFound)
- error: Failed after multiple retries (errorCount > 5)
"""
from sqlalchemy import (
    Column, Integer, String, DateTime, Text,
    ForeignKey, Index, Numeric
)
from datetime import datetime, timezone
from models.base import Base


class LegacyMigrationV1(Base):
    """
    V1 Migration: Darwin legacy shares restoration.

    Source: Google Sheets (Darwin users table)
    Process: Create Purchase + ActiveBalance for legacy shares

    Fields from GS (immutable):
    - email: User email (normalized)
    - upliner: Upliner email, "SAME" keyword, or empty
    - project: Project name (e.g., "DARWIN")
    - qty: Number of shares (None = only change upliner, no purchase)

    Result fields (filled during processing):
    - IsFound: userID when user verified email (NULL = not found yet)
    - UplinerFound: 1 when upliner assigned, 0 otherwise
    - PurchaseDone: 1 when purchase created, 0 otherwise
    """
    __tablename__ = 'legacy_migration_v1'

    # Primary key
    migrationID = Column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # SOURCE DATA (from Google Sheets - immutable after import)
    # =========================================================================
    email = Column(
        String(255),
        nullable=False,
        index=True,
        comment='User email (normalized, lowercase)'
    )
    upliner = Column(
        String(255),
        nullable=True,
        comment='Upliner email, "SAME" to keep current, or empty'
    )
    project = Column(
        String(100),
        nullable=False,
        comment='Project name (e.g., DARWIN)'
    )
    qty = Column(
        Integer,
        nullable=True,
        comment='Number of shares. NULL = only change upliner, no purchase'
    )
    gsRowIndex = Column(
        Integer,
        nullable=True,
        index=True,
        comment='Row number in Google Sheets (for ordering: last = truth)'
    )

    # =========================================================================
    # RESULT FIELDS (filled during processing, exported back to GS)
    # =========================================================================
    IsFound = Column(
        Integer,
        nullable=True,
        comment='userID when user found and verified email'
    )
    UplinerFound = Column(
        Integer,
        default=0,
        nullable=False,
        comment='1 = upliner assigned or SAME, 0 = waiting'
    )
    PurchaseDone = Column(
        Integer,
        default=0,
        nullable=False,
        comment='1 = purchase created (or qty=None processed), 0 = pending'
    )

    # =========================================================================
    # LINKS TO OTHER TABLES
    # =========================================================================
    purchaseID = Column(
        Integer,
        ForeignKey('purchases.purchaseID', ondelete='SET NULL'),
        nullable=True,
        comment='Created purchase record'
    )

    # =========================================================================
    # STATUS AND ERROR TRACKING
    # =========================================================================
    status = Column(
        String(20),
        default='pending',
        nullable=False,
        index=True,
        comment='pending / done / error'
    )
    errorCount = Column(
        Integer,
        default=0,
        nullable=False,
        comment='Number of processing failures'
    )
    lastError = Column(
        Text,
        nullable=True,
        comment='Last error message'
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    createdAt = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='When record was imported from GS'
    )
    processedAt = Column(
        DateTime,
        nullable=True,
        comment='When processing completed (status = done)'
    )

    # =========================================================================
    # INDEXES
    # =========================================================================
    __table_args__ = (
        # For finding records by upliner email
        Index('ix_legacy_v1_upliner', 'upliner'),

        # For finding pending records efficiently
        Index('ix_legacy_v1_status_pending', 'status',
              postgresql_where="status = 'pending'"),
    )

    def __repr__(self):
        return (
            f"<LegacyMigrationV1("
            f"id={self.migrationID}, "
            f"email={self.email}, "
            f"project={self.project}, "
            f"qty={self.qty}, "
            f"status={self.status}"
            f")>"
        )


class LegacyMigrationV2(Base):
    """
    V2 Migration: Aquix double gift (JETUP + AQUIX shares).

    Source: Google Sheets (Aquix users table)
    Process: Grant double gift based on old balance value

    Gift calculation:
    - If value == 0: 84 JETUP + 84 AQUIX (minimum gift)
    - If value > 0: (value / 0.05) JETUP + (value / 0.03) AQUIX
    - If value is None: only change parent, no gift

    Fields from GS (immutable):
    - email: User email (normalized)
    - parent: Parent (upliner) email or empty
    - value: USD value for gift calculation (Decimal)

    Result fields (filled during processing):
    - IsFound: userID when user verified email
    - UplinerFound: 1 when parent assigned, 0 otherwise
    - PurchaseDone: 1 when both gifts created, 0 otherwise
    """
    __tablename__ = 'legacy_migration_v2'

    # Primary key
    migrationID = Column(Integer, primary_key=True, autoincrement=True)

    # =========================================================================
    # SOURCE DATA (from Google Sheets - immutable after import)
    # =========================================================================
    email = Column(
        String(255),
        nullable=False,
        index=True,
        comment='User email (normalized, lowercase)'
    )
    parent = Column(
        String(255),
        nullable=True,
        comment='Parent (upliner) email or empty'
    )
    value = Column(
        Numeric(precision=12, scale=2),
        nullable=True,
        comment='USD value for gift calculation. 0 = minimum gift, NULL = only change parent'
    )
    gsRowIndex = Column(
        Integer,
        nullable=True,
        index=True,
        comment='Row number in Google Sheets (for ordering: last = truth)'
    )

    # =========================================================================
    # RESULT FIELDS (filled during processing, exported back to GS)
    # =========================================================================
    IsFound = Column(
        Integer,
        nullable=True,
        comment='userID when user found and verified email'
    )
    UplinerFound = Column(
        Integer,
        default=0,
        nullable=False,
        comment='1 = parent assigned, 0 = waiting'
    )
    PurchaseDone = Column(
        Integer,
        default=0,
        nullable=False,
        comment='1 = gifts created (or value=None processed), 0 = pending'
    )

    # =========================================================================
    # LINKS TO OTHER TABLES
    # =========================================================================
    jetupPurchaseID = Column(
        Integer,
        ForeignKey('purchases.purchaseID', ondelete='SET NULL'),
        nullable=True,
        comment='Created JETUP purchase record'
    )
    aquixPurchaseID = Column(
        Integer,
        ForeignKey('purchases.purchaseID', ondelete='SET NULL'),
        nullable=True,
        comment='Created AQUIX purchase record'
    )

    # =========================================================================
    # STATUS AND ERROR TRACKING
    # =========================================================================
    status = Column(
        String(20),
        default='pending',
        nullable=False,
        index=True,
        comment='pending / done / error'
    )
    errorCount = Column(
        Integer,
        default=0,
        nullable=False,
        comment='Number of processing failures'
    )
    lastError = Column(
        Text,
        nullable=True,
        comment='Last error message'
    )

    # =========================================================================
    # TIMESTAMPS
    # =========================================================================
    createdAt = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='When record was imported from GS'
    )
    processedAt = Column(
        DateTime,
        nullable=True,
        comment='When processing completed (status = done)'
    )

    # =========================================================================
    # INDEXES
    # =========================================================================
    __table_args__ = (
        # For finding records by parent email
        Index('ix_legacy_v2_parent', 'parent'),

        # For finding pending records efficiently
        Index('ix_legacy_v2_status_pending', 'status',
              postgresql_where="status = 'pending'"),
    )

    def __repr__(self):
        return (
            f"<LegacyMigrationV2("
            f"id={self.migrationID}, "
            f"email={self.email}, "
            f"value={self.value}, "
            f"status={self.status}"
            f")>"
        )