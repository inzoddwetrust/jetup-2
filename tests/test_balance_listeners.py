# tests/test_balance_listeners.py
"""
Tests for Balance Event Listeners.

Tests SQLAlchemy Event Listeners that auto-sync User.balanceActive/balancePassive
using FULL RECALCULATION architecture:

    User.balanceActive = SUM(ActiveBalance.amount) WHERE status='done'
    User.balancePassive = SUM(PassiveBalance.amount) WHERE status='done'

Key principle: User.balance ALWAYS equals journal SUM.
Discrepancies self-heal on any INSERT/UPDATE/DELETE.

Run:
    pytest tests/test_balance_listeners.py -v
    pytest tests/test_balance_listeners.py -v --full-reconciliation

Coverage:
    pytest tests/test_balance_listeners.py -v --cov=models/listeners --cov-report=html
"""
import logging
from decimal import Decimal

import pytest
from sqlalchemy import func, text

from models import User, ActiveBalance, PassiveBalance
from models.purchase import Purchase
from models.listeners import register_all_listeners


# =============================================================================
# TEST CLASS: ActiveBalance INSERT
# =============================================================================

class TestActiveBalanceInsert:
    """Tests for INSERT into ActiveBalance → recalculate User.balanceActive."""

    def test_insert_done_recalculates_balance(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: INSERT with status='done' triggers full recalculation.

        Verify: User.balanceActive == SUM(journal) after operation.
        """
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("insert_done")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected

    def test_insert_pending_not_in_sum(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: INSERT with status='pending' — recalculation happens, but pending not in SUM.
        """
        balance_before = calc_journal_sum['active'](primary_user.userID)

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("500.00"),
            status='pending',
            reason=unique_reason("insert_pending")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        # SUM unchanged (pending not counted)
        assert balance_before == balance_after
        assert primary_user.balanceActive == balance_after

    def test_insert_negative_amount(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: INSERT with negative amount decreases balance.
        """
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("-50.00"),
            status='done',
            reason=unique_reason("insert_negative")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected

    def test_insert_multiple_records(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Multiple INSERTs — all counted in SUM.
        """
        amounts = [Decimal("100.00"), Decimal("200.00"), Decimal("-50.00"), Decimal("75.00")]

        for i, amount in enumerate(amounts):
            record = ActiveBalance(
                userID=primary_user.userID,
                firstname=primary_user.firstname,
                surname=primary_user.surname,
                amount=amount,
                status='done',
                reason=unique_reason(f"multi_{i}")
            )
            session.add(record)

        session.commit()
        session.refresh(primary_user)

        expected = calc_journal_sum['active'](primary_user.userID)
        assert primary_user.balanceActive == expected


# =============================================================================
# TEST CLASS: ActiveBalance UPDATE
# =============================================================================

class TestActiveBalanceUpdate:
    """Tests for UPDATE in ActiveBalance → recalculate User.balanceActive."""

    def test_update_status_pending_to_done(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: UPDATE status='pending' → 'done' adds record to SUM.
        """
        # Create pending record
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("200.00"),
            status='pending',
            reason=unique_reason("update_pending")
        )
        session.add(record)
        session.commit()

        balance_before = calc_journal_sum['active'](primary_user.userID)

        # Change status to done
        record.status = 'done'
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        # SUM increased by 200
        assert balance_after == balance_before + Decimal("200.00")
        assert primary_user.balanceActive == balance_after

    def test_update_status_done_to_cancelled(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: UPDATE status='done' → 'cancelled' removes record from SUM.
        """
        # Create done record
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("150.00"),
            status='done',
            reason=unique_reason("update_done")
        )
        session.add(record)
        session.commit()

        balance_with_record = calc_journal_sum['active'](primary_user.userID)

        # Cancel it
        record.status = 'cancelled'
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        # SUM decreased by 150
        assert balance_after == balance_with_record - Decimal("150.00")
        assert primary_user.balanceActive == balance_after

    def test_update_amount(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: UPDATE amount correctly recalculates balance.
        """
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='done',
            reason=unique_reason("update_amount")
        )
        session.add(record)
        session.commit()

        # Change amount
        record.amount = Decimal("250.00")
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected


# =============================================================================
# TEST CLASS: ActiveBalance DELETE
# =============================================================================

class TestActiveBalanceDelete:
    """Tests for DELETE from ActiveBalance → recalculate User.balanceActive."""

    def test_delete_done_record(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: DELETE record with status='done' decreases balance.
        """
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("300.00"),
            status='done',
            reason=unique_reason("delete_done")
        )
        session.add(record)
        session.commit()

        balance_with_record = calc_journal_sum['active'](primary_user.userID)

        # Delete
        session.delete(record)
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        assert balance_after == balance_with_record - Decimal("300.00")
        assert primary_user.balanceActive == balance_after

    def test_delete_pending_record(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: DELETE record with status='pending' doesn't affect balance.
        """
        balance_before = calc_journal_sum['active'](primary_user.userID)

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='pending',
            reason=unique_reason("delete_pending")
        )
        session.add(record)
        session.commit()

        # Delete pending record
        session.delete(record)
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        # Balance unchanged
        assert balance_before == balance_after
        assert primary_user.balanceActive == balance_after


# =============================================================================
# TEST CLASS: PassiveBalance Operations
# =============================================================================

class TestPassiveBalanceOperations:
    """Tests for PassiveBalance — similar to ActiveBalance."""

    def test_insert_done(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: INSERT with status='done' recalculates balancePassive.
        """
        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("75.00"),
            status='done',
            reason=unique_reason("passive_insert")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['passive'](primary_user.userID)

        assert primary_user.balancePassive == expected

    def test_update_status(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: UPDATE status affects balancePassive correctly.
        """
        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("100.00"),
            status='pending',
            reason=unique_reason("passive_update")
        )
        session.add(record)
        session.commit()

        balance_before = calc_journal_sum['passive'](primary_user.userID)

        # Activate
        record.status = 'done'
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['passive'](primary_user.userID)

        assert balance_after == balance_before + Decimal("100.00")
        assert primary_user.balancePassive == balance_after

    def test_delete_done(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: DELETE done record recalculates balancePassive.
        """
        record = PassiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("50.00"),
            status='done',
            reason=unique_reason("passive_delete")
        )
        session.add(record)
        session.commit()

        balance_with_record = calc_journal_sum['passive'](primary_user.userID)

        session.delete(record)
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['passive'](primary_user.userID)

        assert balance_after == balance_with_record - Decimal("50.00")
        assert primary_user.balancePassive == balance_after


# =============================================================================
# TEST CLASS: Self-Healing
# =============================================================================

class TestSelfHealing:
    """
    Tests for self-healing: corrupted balance auto-fixes on any operation.

    Architecture guarantees: balance = SUM(journal), old value IGNORED.
    """

    def test_heal_on_insert(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Corrupted balance heals on INSERT.
        """
        # Corrupt balance via raw SQL (bypass ORM)
        session.execute(
            text('UPDATE users SET "balanceActive" = :balance WHERE "userID" = :user_id'),
            {"balance": Decimal("999999.00"), "user_id": primary_user.userID}
        )
        session.commit()

        # INSERT triggers recalculation
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("10.00"),
            status='done',
            reason=unique_reason("heal_insert")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        # Balance healed
        assert primary_user.balanceActive == expected

    def test_heal_on_update(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Corrupted balance heals on UPDATE.
        """
        # Create record first
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("50.00"),
            status='pending',
            reason=unique_reason("heal_update")
        )
        session.add(record)
        session.commit()

        # Corrupt balance
        session.execute(
            text('UPDATE users SET "balanceActive" = :balance WHERE "userID" = :user_id'),
            {"balance": Decimal("-999.00"), "user_id": primary_user.userID}
        )
        session.commit()

        # UPDATE triggers recalculation
        record.status = 'done'
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected

    def test_heal_on_delete(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Corrupted balance heals on DELETE.
        """
        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("25.00"),
            status='done',
            reason=unique_reason("heal_delete")
        )
        session.add(record)
        session.commit()

        # Corrupt balance
        session.execute(
            text('UPDATE users SET "balanceActive" = :balance WHERE "userID" = :user_id'),
            {"balance": Decimal("0.00"), "user_id": primary_user.userID}
        )
        session.commit()

        # DELETE triggers recalculation (without deleted record)
        session.delete(record)
        session.commit()

        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected


# =============================================================================
# TEST CLASS: Balance Protection
# =============================================================================

class TestBalanceProtection:
    """
    Tests for protection against direct balance modification.

    Direct assignment user.balanceActive = X should log WARNING.
    """

    def test_direct_active_modification_logs_warning(self, session, primary_user, caplog):
        """
        TEST: Direct balanceActive modification logs WARNING.

        NOTE: This tests architecture violation detection.
        Production code MUST NOT do this.
        """
        caplog.set_level(logging.WARNING)

        old_balance = primary_user.balanceActive

        # Direct modification (FORBIDDEN in production!)
        primary_user.balanceActive = old_balance + Decimal("999.00")

        assert "DIRECT balanceActive modification" in caplog.text

    def test_direct_passive_modification_logs_warning(self, session, primary_user, caplog):
        """
        TEST: Direct balancePassive modification logs WARNING.
        """
        caplog.set_level(logging.WARNING)

        old_balance = primary_user.balancePassive

        # Direct modification (FORBIDDEN in production!)
        primary_user.balancePassive = old_balance + Decimal("999.00")

        assert "DIRECT balancePassive modification" in caplog.text


# =============================================================================
# TEST CLASS: Reconciliation
# =============================================================================

class TestReconciliation:
    """
    Tests for consistency: User.balance ALWAYS == SUM(journal).
    """

    def test_active_balance_equals_journal(self, session, primary_user, calc_journal_sum):
        """
        TEST: User.balanceActive == SUM(ActiveBalance) for test user.
        """
        session.refresh(primary_user)
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected

    def test_passive_balance_equals_journal(self, session, primary_user, calc_journal_sum):
        """
        TEST: User.balancePassive == SUM(PassiveBalance) for test user.
        """
        session.refresh(primary_user)
        expected = calc_journal_sum['passive'](primary_user.userID)

        assert primary_user.balancePassive == expected

    def test_find_active_discrepancies_in_db(self, session, reconciliation_user_ids):
        """
        TEST: Find discrepancies across DB (ActiveBalance).

        After listeners implementation, discrepancies should be 0.
        """
        # Subquery: sum by journal
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

        # Filter by test users if not full reconciliation
        if reconciliation_user_ids is not None:
            query = query.filter(User.userID.in_(reconciliation_user_ids))

        discrepancies = query.limit(10).all()

        if discrepancies:
            for d in discrepancies:
                print(f"DISCREPANCY: user={d.userID}, cached={d.cached}, calculated={d.calculated}")

        assert len(discrepancies) == 0, f"Found {len(discrepancies)} active balance discrepancies"

    def test_find_passive_discrepancies_in_db(self, session, reconciliation_user_ids):
        """
        TEST: Find discrepancies across DB (PassiveBalance).
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

        if reconciliation_user_ids is not None:
            query = query.filter(User.userID.in_(reconciliation_user_ids))

        discrepancies = query.limit(10).all()

        assert len(discrepancies) == 0, f"Found {len(discrepancies)} passive balance discrepancies"


# =============================================================================
# TEST CLASS: Listeners Registration
# =============================================================================

class TestListenersRegistration:
    """Tests for listeners registration."""

    def test_listeners_idempotent(self):
        """
        TEST: Multiple register_all_listeners() calls are safe (idempotent).
        """
        # Call multiple times — should not fail
        register_all_listeners()
        register_all_listeners()
        register_all_listeners()

        assert True  # Reached without errors

    def test_listeners_registered_flag(self):
        """
        TEST: _listeners_registered flag is set.
        """
        from models.listeners import _listeners_registered

        assert _listeners_registered is True


# =============================================================================
# TEST CLASS: Transfer Integration
# =============================================================================

class TestTransferIntegration:
    """Integration tests for transfers."""

    def test_transfer_active_to_active(self, session, sender, recipient, unique_reason, calc_journal_sum):
        """
        TEST: Transfer active→active correctly updates both balances.
        """
        amount = Decimal("100.00")
        reason = unique_reason("transfer_a2a")

        # Debit sender
        debit = ActiveBalance(
            userID=sender.userID,
            firstname=sender.firstname,
            surname=sender.surname,
            amount=-amount,
            status='done',
            reason=reason
        )

        # Credit recipient
        credit = ActiveBalance(
            userID=recipient.userID,
            firstname=recipient.firstname,
            surname=recipient.surname,
            amount=amount,
            status='done',
            reason=reason
        )

        session.add_all([debit, credit])
        session.commit()

        session.refresh(sender)
        session.refresh(recipient)

        assert sender.balanceActive == calc_journal_sum['active'](sender.userID)
        assert recipient.balanceActive == calc_journal_sum['active'](recipient.userID)


# =============================================================================
# TEST CLASS: Purchase Integration
# =============================================================================

class TestPurchaseIntegration:
    """Integration tests for purchases."""

    def test_purchase_deducts_balance(self, session, buyer, test_option, unique_reason, calc_journal_sum):
        """
        TEST: Purchase correctly deducts from buyer's balanceActive.

        Process:
        1. Create Purchase record
        2. Create ActiveBalance with negative amount
        3. Listener recalculates balance
        """
        pack_price = Decimal(str(test_option.packPrice))

        # Create Purchase
        purchase = Purchase(
            userID=buyer.userID,
            projectID=test_option.projectID,
            projectName=test_option.projectName,
            optionID=test_option.optionID,
            packQty=test_option.packQty,
            packPrice=pack_price
        )
        session.add(purchase)
        session.flush()

        # Create ActiveBalance debit
        debit = ActiveBalance(
            userID=buyer.userID,
            firstname=buyer.firstname,
            surname=buyer.surname,
            amount=-pack_price,
            status='done',
            reason=f"purchase={purchase.purchaseID}"
        )
        session.add(debit)
        session.commit()

        session.refresh(buyer)
        expected = calc_journal_sum['active'](buyer.userID)

        assert buyer.balanceActive == expected


# =============================================================================
# TEST CLASS: Edge Cases
# =============================================================================

class TestEdgeCases:
    """Edge cases."""

    def test_zero_amount_record(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Record with amount=0 doesn't affect balance.
        """
        balance_before = calc_journal_sum['active'](primary_user.userID)

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("0.00"),
            status='done',
            reason=unique_reason("zero_amount")
        )
        session.add(record)
        session.commit()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        assert balance_before == balance_after

    def test_decimal_precision(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Decimal precision preserved (kopecks/cents).
        """
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

        expected = calc_journal_sum['active'](primary_user.userID)
        assert primary_user.balanceActive == expected

    def test_large_amount(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Large amounts handled correctly (no overflow).
        """
        large_amount = Decimal("999999999.99")

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
        expected = calc_journal_sum['active'](primary_user.userID)

        assert primary_user.balanceActive == expected

        # Cleanup — remove large amount
        session.delete(record)
        session.commit()

    def test_rollback_reverts_balance(self, session, primary_user, unique_reason, calc_journal_sum):
        """
        TEST: Rollback reverts balance.
        """
        balance_before = calc_journal_sum['active'](primary_user.userID)

        record = ActiveBalance(
            userID=primary_user.userID,
            firstname=primary_user.firstname,
            surname=primary_user.surname,
            amount=Decimal("500.00"),
            status='done',
            reason=unique_reason("will_rollback")
        )
        session.add(record)
        session.flush()  # Listener fires here

        session.rollback()

        session.refresh(primary_user)
        balance_after = calc_journal_sum['active'](primary_user.userID)

        # Balance returned to before-transaction value
        assert balance_after == balance_before