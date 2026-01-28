# tests/test_balance_listeners.py
"""
Tests for Balance Event Listeners.

Tests SQLAlchemy Event Listeners that auto-sync User.balanceActive/balancePassive
when records are inserted into ActiveBalance/PassiveBalance journals.

Run:
    pytest tests/test_balance_listeners.py -v
    pytest tests/test_balance_listeners.py -v --full-reconciliation  # full DB scan

Coverage:
    pytest tests/test_balance_listeners.py -v --cov=models/listeners --cov-report=html
"""
import logging
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from config import Config
from models import User, ActiveBalance, PassiveBalance
from models.listeners import register_all_listeners

# =============================================================================
# CONSTANTS
# =============================================================================

USER_IDS = {
    'primary': 33,
    'sender': 48,
    'recipient': 132,
    'buyer': 283
}


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def engine():
    """Create database engine for test session."""
    database_url = Config.get(Config.DATABASE_URL)
    engine = create_engine(database_url)
    return engine


@pytest.fixture(scope="session", autouse=True)
def setup_listeners():
    """Register listeners once at test session start."""
    register_all_listeners()


@pytest.fixture
def session(engine):
    """Create database session for each test."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# =============================================================================
# USER FIXTURES
# =============================================================================

@pytest.fixture
def primary_user(session):
    """Primary test user (userID=33)."""
    user = session.query(User).filter_by(userID=USER_IDS['primary']).first()
    assert user is not None, f"User {USER_IDS['primary']} not found in test DB"
    return user


@pytest.fixture
def sender(session):
    """Sender for transfer tests (userID=48)."""
    user = session.query(User).filter_by(userID=USER_IDS['sender']).first()
    assert user is not None, f"User {USER_IDS['sender']} not found in test DB"
    return user


@pytest.fixture
def recipient(session):
    """Recipient for transfer tests (userID=132)."""
    user = session.query(User).filter_by(userID=USER_IDS['recipient']).first()
    assert user is not None, f"User {USER_IDS['recipient']} not found in test DB"
    return user


@pytest.fixture
def buyer(session):
    """Buyer for purchase tests (userID=283)."""
    user = session.query(User).filter_by(userID=USER_IDS['buyer']).first()
    assert user is not None, f"User {USER_IDS['buyer']} not found in test DB"
    return user


# =============================================================================
# HELPER FIXTURES
# =============================================================================

@pytest.fixture
def save_balance():
    """Factory to save user balance for later comparison."""
    saved = {}

    def _save(user):
        saved[user.userID] = {
            'active': user.balanceActive,
            'passive': user.balancePassive
        }
        return saved[user.userID]

    return _save


@pytest.fixture
def unique_reason():
    """Generate unique reason string for test records."""

    def _generate(prefix="test"):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    return _generate


@pytest.fixture
def reconciliation_user_ids(request):
    """
    Returns user IDs for reconciliation scope.

    Default: test users only [33, 48, 132, 283]
    With --full-reconciliation: None (scan all users)
    """
    if request.config.getoption("--full-reconciliation"):
        return None
    return list(USER_IDS.values())


# =============================================================================
# TEST CLASS: ActiveBalance Listener
# =============================================================================

class TestActiveBalanceListener:
    """Unit tests for ActiveBalance event listener."""

    def test_insert_done_updates_balance(self, session, primary_user, unique_reason):
        """
        TEST: INSERT ActiveBalance with status='done' increases User.balanceActive.
        """
        initial = primary_user.balanceActive or Decimal("0")

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("deposit")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == initial + Decimal("100.00")

    def test_negative_amount_decreases_balance(self, session, primary_user, unique_reason):
        """
        TEST: Negative amount decreases balance.
        """
        primary_user.balanceActive = Decimal("500.00")
        session.commit()

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("-200.00"),
            status='done',
            reason=unique_reason("purchase")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == Decimal("300.00")

    def test_pending_status_no_update(self, session, primary_user, unique_reason):
        """
        TEST: status='pending' does NOT update balance.
        """
        initial = primary_user.balanceActive or Decimal("0")

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='pending',
            reason=unique_reason("pending_test")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == initial

    def test_zero_amount_no_update(self, session, primary_user, unique_reason):
        """
        TEST: amount=0 does NOT update balance.
        """
        initial = primary_user.balanceActive or Decimal("0")

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("0"),
            status='done',
            reason=unique_reason("zero_test")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == initial

    def test_cancelled_status_no_update(self, session, primary_user, unique_reason):
        """
        TEST: status='cancelled' does NOT update balance.
        """
        initial = primary_user.balanceActive or Decimal("0")

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='cancelled',
            reason=unique_reason("cancelled_test")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == initial

    def test_error_status_no_update(self, session, primary_user, unique_reason):
        """
        TEST: status='error' does NOT update balance.
        """
        initial = primary_user.balanceActive or Decimal("0")

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='error',
            reason=unique_reason("error_test")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == initial


# =============================================================================
# TEST CLASS: PassiveBalance Listener
# =============================================================================

class TestPassiveBalanceListener:
    """Unit tests for PassiveBalance event listener."""

    def test_insert_done_updates_balance(self, session, primary_user, unique_reason):
        """
        TEST: INSERT PassiveBalance with status='done' increases User.balancePassive.
        """
        initial = primary_user.balancePassive or Decimal("0")

        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("50.00"),
            status='done',
            reason=unique_reason("bonus")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balancePassive == initial + Decimal("50.00")

    def test_pending_status_no_update(self, session, primary_user, unique_reason):
        """
        TEST: status='pending' does NOT update passive balance.
        """
        initial = primary_user.balancePassive or Decimal("0")

        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("50.00"),
            status='pending',
            reason=unique_reason("pending_bonus")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balancePassive == initial

    def test_negative_amount_decreases_balance(self, session, primary_user, unique_reason):
        """
        TEST: Negative amount decreases passive balance (transfer out).
        """
        primary_user.balancePassive = Decimal("300.00")
        session.commit()

        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("-100.00"),
            status='done',
            reason=unique_reason("transfer_out")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balancePassive == Decimal("200.00")


# =============================================================================
# TEST CLASS: Balance Protection
# =============================================================================

class TestBalanceProtection:
    """Tests for balance protection listener (warnings on direct modification)."""

    def test_direct_active_modification_logs_warning(self, session, primary_user, caplog):
        """
        TEST: Direct balanceActive modification logs WARNING.
        """
        caplog.set_level(logging.WARNING)

        primary_user.balanceActive = Decimal("100.00")
        session.commit()

        # Direct modification (should trigger warning)
        primary_user.balanceActive = Decimal("200.00")

        assert "DIRECT balanceActive modification" in caplog.text

    def test_direct_passive_modification_logs_warning(self, session, primary_user, caplog):
        """
        TEST: Direct balancePassive modification logs WARNING.
        """
        caplog.set_level(logging.WARNING)

        primary_user.balancePassive = Decimal("100.00")
        session.commit()

        # Direct modification (should trigger warning)
        primary_user.balancePassive = Decimal("200.00")

        assert "DIRECT balancePassive modification" in caplog.text


# =============================================================================
# TEST CLASS: Listeners Registration
# =============================================================================

class TestListenersRegistration:
    """Tests for listeners registration."""

    def test_listeners_idempotent(self):
        """
        TEST: Multiple register_all_listeners() calls are safe (idempotent).
        """
        # First call (may already be called in fixture)
        register_all_listeners()

        # Second call - should not fail
        register_all_listeners()

        # If we got here - test passed
        assert True

    def test_listeners_registered_flag(self):
        """
        TEST: _listeners_registered flag is set correctly.
        """
        from models.listeners import _listeners_registered

        assert _listeners_registered is True


# =============================================================================
# TEST CLASS: Transfer Integration
# =============================================================================

class TestTransferIntegration:
    """Integration tests for transfers."""

    def test_transfer_active_to_active(self, session, sender, recipient, unique_reason):
        """
        TEST: Active-to-active transfer updates both users.
        """
        sender.balanceActive = Decimal("1000.00")
        recipient.balanceActive = Decimal("0")
        session.commit()

        amount = Decimal("300.00")
        reason = unique_reason("transfer")

        # Sender debit
        sender_record = ActiveBalance(
            userID=sender.userID,
            firstname=sender.firstname,
            surname=sender.surname,
            amount=-amount,
            status='done',
            reason=reason
        )

        # Recipient credit
        recipient_record = ActiveBalance(
            userID=recipient.userID,
            firstname=recipient.firstname,
            surname=recipient.surname,
            amount=amount,
            status='done',
            reason=reason
        )

        session.add_all([sender_record, recipient_record])
        session.commit()

        session.refresh(sender)
        session.refresh(recipient)

        assert sender.balanceActive == Decimal("700.00")
        assert recipient.balanceActive == Decimal("300.00")

    def test_transfer_passive_to_active(self, session, sender, recipient, unique_reason):
        """
        TEST: Passive-to-active transfer updates both balances.
        """
        sender.balancePassive = Decimal("500.00")
        recipient.balanceActive = Decimal("0")
        session.commit()

        amount = Decimal("200.00")
        reason = unique_reason("transfer_p2a")

        # Sender passive debit
        sender_record = PassiveBalance(
            userID=sender.userID,
            firstname=sender.firstname,
            surname=sender.surname,
            amount=-amount,
            status='done',
            reason=reason
        )

        # Recipient active credit
        recipient_record = ActiveBalance(
            userID=recipient.userID,
            firstname=recipient.firstname,
            surname=recipient.surname,
            amount=amount,
            status='done',
            reason=reason
        )

        session.add_all([sender_record, recipient_record])
        session.commit()

        session.refresh(sender)
        session.refresh(recipient)

        assert sender.balancePassive == Decimal("300.00")
        assert recipient.balanceActive == Decimal("200.00")


# =============================================================================
# TEST CLASS: Purchase Integration
# =============================================================================

class TestPurchaseIntegration:
    """Integration tests for purchases."""

    def test_purchase_deducts_balance(self, session, buyer, unique_reason):
        """
        TEST: Purchase deducts active balance.
        """
        buyer.balanceActive = Decimal("5000.00")
        session.commit()

        pack_price = Decimal("1000.00")

        record = ActiveBalance(
            userID=buyer.userID,
            firstname=buyer.firstname,
            surname=buyer.surname,
            amount=-pack_price,
            status='done',
            reason=unique_reason("purchase")
        )
        session.add(record)
        session.commit()

        session.refresh(buyer)
        assert buyer.balanceActive == Decimal("4000.00")

    def test_auto_purchase_net_zero(self, session, buyer, unique_reason):
        """
        TEST: Auto-purchase (bonus + debit) results in net zero balance change.
        """
        initial = buyer.balanceActive or Decimal("0")
        bonus_amount = Decimal("100.00")
        reason_base = unique_reason("autopurchase")

        # Credit (bonus)
        credit = ActiveBalance(
            userID=buyer.userID,
            firstname=buyer.firstname,
            surname=buyer.surname,
            amount=bonus_amount,
            status='done',
            reason=f"{reason_base}_credit"
        )

        # Debit (purchase)
        debit = ActiveBalance(
            userID=buyer.userID,
            firstname=buyer.firstname,
            surname=buyer.surname,
            amount=-bonus_amount,
            status='done',
            reason=f"{reason_base}_debit"
        )

        session.add_all([credit, debit])
        session.commit()

        session.refresh(buyer)
        assert buyer.balanceActive == initial  # Net zero


# =============================================================================
# TEST CLASS: Bonus Payout Integration
# =============================================================================

class TestBonusPayoutIntegration:
    """Integration tests for bonus payouts."""

    def test_monthly_bonus_payout(self, session, primary_user, unique_reason):
        """
        TEST: Monthly bonus payout increases passive balance.
        """
        initial = primary_user.balancePassive or Decimal("0")
        bonus_amount = Decimal("150.00")

        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=bonus_amount,
            status='done',
            reason=unique_reason("bonus")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balancePassive == initial + Decimal("150.00")

    def test_transfer_bonus_to_active(self, session, recipient, unique_reason):
        """
        TEST: Transfer bonus credited to active balance.
        """
        initial = recipient.balanceActive or Decimal("0")
        bonus_amount = Decimal("20.00")  # 2% of 1000

        record = ActiveBalance(
            userID=recipient.userID,
            firstname=recipient.firstname,
            surname=recipient.surname,
            amount=bonus_amount,
            status='done',
            reason=unique_reason("transfer_bonus")
        )
        session.add(record)
        session.commit()

        session.refresh(recipient)
        assert recipient.balanceActive == initial + Decimal("20.00")


# =============================================================================
# TEST CLASS: Reconciliation
# =============================================================================

class TestReconciliation:
    """Tests for journal-balance consistency."""

    def test_active_balance_equals_journal_sum(self, session, primary_user, unique_reason):
        """
        TEST: User.balanceActive == SUM(ActiveBalance.amount) where status='done'.
        """
        primary_user.balanceActive = Decimal("0")
        session.commit()

        amounts = [Decimal("100"), Decimal("200"), Decimal("-50"), Decimal("75")]

        for i, amount in enumerate(amounts):
            record = ActiveBalance(
                userID=primary_user.userID,
                firstname=primary_user.firstname,
                surname=primary_user.surname,
                amount=amount,
                status='done',
                reason=unique_reason(f"reconcile_{i}")
            )
            session.add(record)

        session.commit()
        session.refresh(primary_user)

        expected = sum(amounts)
        assert primary_user.balanceActive == expected

    def test_passive_balance_equals_journal_sum(self, session, primary_user, unique_reason):
        """
        TEST: User.balancePassive == SUM(PassiveBalance.amount) where status='done'.
        """
        primary_user.balancePassive = Decimal("0")
        session.commit()

        amounts = [Decimal("50"), Decimal("100"), Decimal("-25")]

        for i, amount in enumerate(amounts):
            record = PassiveBalance(
                userID=primary_user.userID,
                firstname=primary_user.firstname,
                surname=primary_user.surname,
                amount=amount,
                status='done',
                reason=unique_reason(f"reconcile_p_{i}")
            )
            session.add(record)

        session.commit()
        session.refresh(primary_user)

        expected = sum(amounts)
        assert primary_user.balancePassive == expected

    def test_find_active_balance_discrepancies(self, session, reconciliation_user_ids):
        """
        TEST: Find discrepancies between User.balanceActive and journal sum.

        Default: checks only test users (33, 48, 132, 283)
        With --full-reconciliation: checks ALL users (diagnostic mode)
        """
        # Subquery: journal sum per user
        journal_sum = session.query(
            ActiveBalance.userID,
            func.coalesce(func.sum(ActiveBalance.amount), Decimal("0")).label('calculated')
        ).filter(
            ActiveBalance.status == 'done'
        ).group_by(ActiveBalance.userID).subquery()

        # Find discrepancies
        query = session.query(
            User.userID,
            User.balanceActive.label('cached'),
            journal_sum.c.calculated
        ).outerjoin(
            journal_sum, User.userID == journal_sum.c.userID
        ).filter(
            User.balanceActive != func.coalesce(journal_sum.c.calculated, Decimal("0"))
        )

        # Apply scope filter if not full reconciliation
        if reconciliation_user_ids:
            query = query.filter(User.userID.in_(reconciliation_user_ids))

        discrepancies = query.limit(100).all()

        # Log discrepancies for debugging
        if discrepancies:
            print(f"\n{'=' * 60}")
            print(f"ACTIVE BALANCE DISCREPANCIES: {len(discrepancies)} found")
            print(f"{'=' * 60}")
            for d in discrepancies:
                diff = (d.cached or Decimal("0")) - (d.calculated or Decimal("0"))
                print(f"  userID={d.userID}: cached={d.cached}, "
                      f"journal_sum={d.calculated}, diff={diff}")
            print(f"{'=' * 60}\n")

        assert len(discrepancies) == 0, f"Found {len(discrepancies)} active balance discrepancies"

    def test_find_passive_balance_discrepancies(self, session, reconciliation_user_ids):
        """
        TEST: Find discrepancies between User.balancePassive and journal sum.

        Default: checks only test users
        With --full-reconciliation: checks ALL users
        """
        journal_sum = session.query(
            PassiveBalance.userID,
            func.coalesce(func.sum(PassiveBalance.amount), Decimal("0")).label('calculated')
        ).filter(
            PassiveBalance.status == 'done'
        ).group_by(PassiveBalance.userID).subquery()

        query = session.query(
            User.userID,
            User.balancePassive.label('cached'),
            journal_sum.c.calculated
        ).outerjoin(
            journal_sum, User.userID == journal_sum.c.userID
        ).filter(
            User.balancePassive != func.coalesce(journal_sum.c.calculated, Decimal("0"))
        )

        if reconciliation_user_ids:
            query = query.filter(User.userID.in_(reconciliation_user_ids))

        discrepancies = query.limit(100).all()

        # Log discrepancies for debugging
        if discrepancies:
            print(f"\n{'=' * 60}")
            print(f"PASSIVE BALANCE DISCREPANCIES: {len(discrepancies)} found")
            print(f"{'=' * 60}")
            for d in discrepancies:
                diff = (d.cached or Decimal("0")) - (d.calculated or Decimal("0"))
                print(f"  userID={d.userID}: cached={d.cached}, "
                      f"journal_sum={d.calculated}, diff={diff}")
            print(f"{'=' * 60}\n")

        assert len(discrepancies) == 0, f"Found {len(discrepancies)} passive balance discrepancies"


# =============================================================================
# TEST CLASS: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_null_initial_balance(self, session, primary_user, unique_reason):
        """
        TEST: User with NULL balance is handled correctly.

        Listener uses COALESCE to treat NULL as 0.
        """
        # Set NULL directly via SQL
        session.execute(
            User.__table__.update()
            .where(User.__table__.c.userID == primary_user.userID)
            .values(balanceActive=None)
        )
        session.commit()
        session.refresh(primary_user)

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("null_test")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        # NULL + 100 should give 100 (COALESCE handles this)
        assert primary_user.balanceActive is not None
        assert primary_user.balanceActive == Decimal("100.00")

    def test_very_large_amount(self, session, primary_user, unique_reason):
        """
        TEST: Very large amount does not cause overflow.

        DECIMAL(12,2) supports up to 9,999,999,999.99
        """
        large_amount = Decimal("999999999.99")

        primary_user.balanceActive = Decimal("0")
        session.commit()

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=large_amount,
            status='done',
            reason=unique_reason("large_amount")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        assert primary_user.balanceActive == large_amount

    def test_decimal_precision(self, session, primary_user, unique_reason):
        """
        TEST: Decimal precision (cents) is preserved.

        0.01 + 0.02 + 0.03 = 0.06 (not 0.060000000001)
        """
        primary_user.balanceActive = Decimal("0")
        session.commit()

        amounts = [Decimal("0.01"), Decimal("0.02"), Decimal("0.03")]

        for i, amount in enumerate(amounts):
            record = ActiveBalance(
                userID=primary_user.userID,
                firstname=primary_user.firstname,
                surname=primary_user.surname,
                amount=amount,
                status='done',
                reason=unique_reason(f"precision_{i}")
            )
            session.add(record)

        session.commit()
        session.refresh(primary_user)

        assert primary_user.balanceActive == Decimal("0.06")

    def test_multiple_records_single_commit(self, session, primary_user, unique_reason):
        """
        TEST: Multiple records in single commit are all applied.
        """
        primary_user.balanceActive = Decimal("1000.00")
        session.commit()

        records = [
            ActiveBalance(userID=primary_user.userID, firstname=primary_user.firstname,
                          surname=primary_user.surname, amount=Decimal("-100"),
                          status='done', reason=unique_reason("multi_1")),
            ActiveBalance(userID=primary_user.userID, firstname=primary_user.firstname,
                          surname=primary_user.surname, amount=Decimal("-200"),
                          status='done', reason=unique_reason("multi_2")),
            ActiveBalance(userID=primary_user.userID, firstname=primary_user.firstname,
                          surname=primary_user.surname, amount=Decimal("50"),
                          status='done', reason=unique_reason("multi_3")),
        ]

        session.add_all(records)
        session.commit()

        session.refresh(primary_user)
        # 1000 - 100 - 200 + 50 = 750
        assert primary_user.balanceActive == Decimal("750.00")

    def test_rollback_reverts_balance(self, session, primary_user, unique_reason):
        """
        TEST: Rollback reverts balance changes.
        """
        primary_user.balanceActive = Decimal("500.00")
        session.commit()
        initial = primary_user.balanceActive

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("will_rollback")
        )
        session.add(record)
        session.flush()  # Listener fires here

        session.rollback()  # Rollback

        session.refresh(primary_user)
        assert primary_user.balanceActive == initial


# =============================================================================
# TEST CLASS: Negative Scenarios
# =============================================================================

class TestNegativeScenarios:
    """Negative scenarios and error handling."""

    def test_nonexistent_user_id(self, session, unique_reason):
        """
        TEST: ActiveBalance with nonexistent userID.

        Expected: FK constraint prevents INSERT (IntegrityError).
        """
        nonexistent_user_id = 999999

        record = ActiveBalance(
            userID=nonexistent_user_id,
            firstname="Ghost",
            surname="User",
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("ghost_user")
        )

        with pytest.raises(IntegrityError):
            session.add(record)
            session.commit()

        session.rollback()

    def test_none_amount(self, session, primary_user, unique_reason):
        """
        TEST: ActiveBalance with amount=None.

        Expected: DB constraint rejects NULL (amount is NOT NULL).
        """
        initial = primary_user.balanceActive or Decimal("0")

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=None,  # NULL amount
            status='done',
            reason=unique_reason("null_amount")
        )

        # Expect DB error (amount is NOT NULL) or listener skips
        try:
            session.add(record)
            session.commit()
            session.refresh(primary_user)
            # If we got here - listener skipped and DB allowed NULL (unexpected)
            assert primary_user.balanceActive == initial
        except IntegrityError:
            session.rollback()
            # Expected behavior - DB doesn't allow NULL

    def test_audit_mixin_fields_populated(self, session, primary_user, unique_reason):
        """
        TEST: AuditMixin fields (ownerTelegramID, ownerEmail) are saved correctly.
        """
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("audit_test"),
            ownerTelegramID=primary_user.telegramID,
            ownerEmail=primary_user.email or ''
        )
        session.add(record)
        session.commit()

        # Verify fields are saved
        session.refresh(record)
        assert record.ownerTelegramID == primary_user.telegramID
        assert record.ownerEmail == (primary_user.email or '')