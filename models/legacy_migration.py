# models/legacy_migration.py
"""
Legacy Migration Models - TEMPORARY FEATURE

These models store migration data from old Darwin/Aquix projects.
Will be deleted when migration is complete.

Tables:
- legacy_migration_v1: Darwin legacy shares
- legacy_migration_v2: Aquix double gift migration
"""
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.sql import text
from datetime import datetime, timezone
from models.base import Base


class LegacyMigrationV1(Base):
    """
    V1 Migration: Darwin legacy shares restoration.

    Source: Google Sheets (legacy users table)
    Process: Restore purchase history from old Darwin project

    Lifecycle:
    1. pending: Waiting for user registration + email verification
    2. user_found: User registered and email verified (deprecated, not used)
    3. purchase_done: Purchase created, upliner NOT assigned yet
    4. completed: Purchase + upliner assigned (all 3 flags = 1)
    5. error: Failed after multiple retries
    """
    __tablename__ = 'legacy_migration_v1'

    # Primary key
    migrationID = Column(Integer, primary_key=True, autoincrement=True)

    # Source data (from Google Sheets - IMMUTABLE)
    email = Column(String, nullable=False, index=True, comment='User email (normalized)')
    upliner = Column(String, nullable=True, comment='Upliner email or SAME keyword')
    project = Column(String, nullable=False, comment='Project name (e.g., Darwin)')
    qty = Column(Integer, nullable=False, comment='Number of shares')

    # Processing status
    status = Column(
        String,
        default='pending',
        nullable=False,
        index=True,
        comment='pending/purchase_done/completed/error'
    )

    # Relations (populated during processing)
    userID = Column(
        Integer,
        ForeignKey('users.userID', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment='User who receives the shares'
    )
    uplinerID = Column(
        Integer,
        ForeignKey('users.userID', ondelete='SET NULL'),
        nullable=True,
        comment='Assigned upliner user ID'
    )
    purchaseID = Column(
        Integer,
        ForeignKey('purchases.purchaseID', ondelete='SET NULL'),
        nullable=True,
        comment='Created purchase record'
    )

    # Timestamps
    createdAt = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='When record was imported to DB'
    )
    userFoundAt = Column(
        DateTime,
        nullable=True,
        comment='When user registered and verified email'
    )
    completedAt = Column(
        DateTime,
        nullable=True,
        comment='When purchase was successfully created'
    )

    # Error tracking
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

    # Google Sheets sync (for exporting status back)
    gsRowIndex = Column(
        Integer,
        nullable=True,
        index=True,
        comment='Row number in Google Sheets (for export)'
    )
    gsLastSyncAt = Column(
        DateTime,
        nullable=True,
        comment='Last sync to Google Sheets'
    )

    # Constraints
    __table_args__ = (
        # Prevent duplicate migrations for same user/project/qty
        UniqueConstraint('email', 'project', 'qty', name='uq_legacy_v1_migration'),

        # Optimized index for pending migrations query
        Index(
            'ix_legacy_v1_pending',
            'status',
            postgresql_where=text("status = 'pending'")
        ),

        # Index for upliner lookups
        Index('ix_legacy_v1_upliner', 'upliner'),
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
    - If value == 0: 84 JETUP + 84 AQUIX (minimum)
    - If value > 0: (value / 0.05) JETUP + (value / 0.03) AQUIX

    Lifecycle:
    1. pending: Waiting for user registration + email verification
    2. user_found: User registered and email verified (deprecated, not used)
    3. purchase_done: Gifts created, parent NOT assigned yet
    4. completed: Gifts + parent assigned (all 3 flags = 1)
    5. error: Failed after multiple retries
    """
    __tablename__ = 'legacy_migration_v2'

    # Primary key
    migrationID = Column(Integer, primary_key=True, autoincrement=True)

    # Source data (from Google Sheets - IMMUTABLE)
    email = Column(String, nullable=False, index=True, comment='User email (normalized)')
    parent = Column(String, nullable=True, comment='Parent (upliner) email')
    value = Column(Integer, default=0, nullable=False, comment='Old balance value in USD')

    # Processing status
    status = Column(
        String,
        default='pending',
        nullable=False,
        index=True,
        comment='pending/purchase_done/completed/error'
    )

    # Relations (populated during processing)
    userID = Column(
        Integer,
        ForeignKey('users.userID', ondelete='SET NULL'),
        nullable=True,
        index=True,
        comment='User who receives the gift'
    )
    parentID = Column(
        Integer,
        ForeignKey('users.userID', ondelete='SET NULL'),
        nullable=True,
        comment='Assigned parent user ID'
    )
    jetupBalanceID = Column(
        Integer,
        ForeignKey('active_balances.paymentID', ondelete='SET NULL'),
        nullable=True,
        comment='Created JETUP balance record'
    )
    aquixBalanceID = Column(
        Integer,
        ForeignKey('active_balances.paymentID', ondelete='SET NULL'),
        nullable=True,
        comment='Created AQUIX balance record'
    )

    # Timestamps
    createdAt = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        comment='When record was imported to DB'
    )
    userFoundAt = Column(
        DateTime,
        nullable=True,
        comment='When user registered and verified email'
    )
    completedAt = Column(
        DateTime,
        nullable=True,
        comment='When both gifts were successfully created'
    )

    # Error tracking
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

    # Google Sheets sync (for exporting status back)
    gsRowIndex = Column(
        Integer,
        nullable=True,
        index=True,
        comment='Row number in Google Sheets (for export)'
    )
    gsLastSyncAt = Column(
        DateTime,
        nullable=True,
        comment='Last sync to Google Sheets'
    )

    # Constraints
    __table_args__ = (
        # Prevent duplicate migrations for same user/value
        UniqueConstraint('email', 'value', name='uq_legacy_v2_migration'),

        # Optimized index for pending migrations query
        Index(
            'ix_legacy_v2_pending',
            'status',
            postgresql_where=text("status = 'pending'")
        ),

        # Index for parent lookups
        Index('ix_legacy_v2_parent', 'parent'),
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