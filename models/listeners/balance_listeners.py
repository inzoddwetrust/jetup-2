# models/listeners/balance_listeners.py
"""
Balance Event Listeners - Auto-sync User balances on journal changes.

Architecture:
    ActiveBalance (INSERT/UPDATE/DELETE) → User.balanceActive = SUM(journal)
    PassiveBalance (INSERT/UPDATE/DELETE) → User.balancePassive = SUM(journal)

This ensures User.balanceActive/balancePassive ALWAYS equals
SUM(amount) from corresponding journal tables. Discrepancies are IMPOSSIBLE.

NOTE: All balance operations MUST go through journal tables.
      Direct User.balanceActive = X is FORBIDDEN after this refactor.

REFACTORED: 2026-01-28 - Full recalculation instead of incremental updates.
"""
import logging

from sqlalchemy import event, func, select

logger = logging.getLogger(__name__)


def register_balance_listeners():
    """
    Register event listeners for balance synchronization.

    Called once during application startup from models/listeners/__init__.py
    """
    from models.active_balance import ActiveBalance
    from models.passive_balance import PassiveBalance
    from models.user import User

    # =========================================================================
    # ACTIVE BALANCE LISTENERS
    # =========================================================================

    def recalc_active_balance(mapper, connection, target):
        """
        Full recalculation of User.balanceActive from journal.

        Formula: User.balanceActive = SUM(ActiveBalance.amount)
                                      WHERE userID=X AND status='done'
        """
        # Calculate REAL sum from journal
        result = connection.execute(
            select(func.coalesce(func.sum(ActiveBalance.__table__.c.amount), 0))
            .where(ActiveBalance.__table__.c.userID == target.userID)
            .where(ActiveBalance.__table__.c.status == 'done')
        )
        real_balance = result.scalar()

        # Overwrite (NOT increment!)
        connection.execute(
            User.__table__.update()
            .where(User.__table__.c.userID == target.userID)
            .values(balanceActive=real_balance)
        )

        logger.info(
            f"ActiveBalance RECALC: user={target.userID}, "
            f"new_balance={real_balance}, trigger={target.reason}"
        )

    event.listen(ActiveBalance, 'after_insert', recalc_active_balance)
    event.listen(ActiveBalance, 'after_update', recalc_active_balance)
    event.listen(ActiveBalance, 'after_delete', recalc_active_balance)

    # =========================================================================
    # PASSIVE BALANCE LISTENERS
    # =========================================================================

    def recalc_passive_balance(mapper, connection, target):
        """
        Full recalculation of User.balancePassive from journal.

        Formula: User.balancePassive = SUM(PassiveBalance.amount)
                                       WHERE userID=X AND status='done'
        """
        # Calculate REAL sum from journal
        result = connection.execute(
            select(func.coalesce(func.sum(PassiveBalance.__table__.c.amount), 0))
            .where(PassiveBalance.__table__.c.userID == target.userID)
            .where(PassiveBalance.__table__.c.status == 'done')
        )
        real_balance = result.scalar()

        # Overwrite (NOT increment!)
        connection.execute(
            User.__table__.update()
            .where(User.__table__.c.userID == target.userID)
            .values(balancePassive=real_balance)
        )

        logger.info(
            f"PassiveBalance RECALC: user={target.userID}, "
            f"new_balance={real_balance}, trigger={target.reason}"
        )

    event.listen(PassiveBalance, 'after_insert', recalc_passive_balance)
    event.listen(PassiveBalance, 'after_update', recalc_passive_balance)
    event.listen(PassiveBalance, 'after_delete', recalc_passive_balance)


# =========================================================================
# SAFETY: Prevent direct balance modification
# =========================================================================

def register_balance_protection():
    """
    Log warnings when User.balanceActive/Passive is modified directly.

    This helps catch violations during transition period.
    Can be disabled after refactoring is complete.
    """
    from models.user import User

    @event.listens_for(User.balanceActive, 'set')
    def warn_direct_active_balance_set(target, value, oldvalue, initiator):
        """Warn when balanceActive is set directly (not via listener)."""
        if oldvalue is not None and value != oldvalue:
            import traceback
            stack = ''.join(traceback.format_stack()[-5:-1])

            logger.warning(
                f"DIRECT balanceActive modification detected! "
                f"user={target.userID}, {oldvalue} → {value}\n"
                f"Stack:\n{stack}"
            )

    @event.listens_for(User.balancePassive, 'set')
    def warn_direct_passive_balance_set(target, value, oldvalue, initiator):
        """Warn when balancePassive is set directly (not via listener)."""
        if oldvalue is not None and value != oldvalue:
            import traceback
            stack = ''.join(traceback.format_stack()[-5:-1])

            logger.warning(
                f"DIRECT balancePassive modification detected! "
                f"user={target.userID}, {oldvalue} → {value}\n"
                f"Stack:\n{stack}"
            )