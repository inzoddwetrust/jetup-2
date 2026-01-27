# models/listeners/balance_listeners.py
"""
Balance Event Listeners - Auto-sync User balances on journal changes.

Architecture:
    ActiveBalance (INSERT) → User.balanceActive += amount
    PassiveBalance (INSERT) → User.balancePassive += amount

This ensures User.balanceActive/balancePassive always equals
SUM(amount) from corresponding journal tables.

NOTE: All balance operations MUST go through journal tables.
      Direct User.balanceActive = X is FORBIDDEN after this refactor.

Usage:
    Listeners are registered automatically when models are imported.
    See: models/listeners/__init__.py

REFACTORED: 2026-01-28 - Added COALESCE to handle NULL balances safely.
"""
import logging

from sqlalchemy import event, func

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
    # ACTIVE BALANCE LISTENER
    # =========================================================================

    @event.listens_for(ActiveBalance, 'after_insert')
    def sync_active_balance_on_insert(mapper, connection, target):
        """
        Auto-update User.balanceActive when ActiveBalance record is created.

        Args:
            mapper: SQLAlchemy mapper (unused)
            connection: Raw DB connection (used for UPDATE)
            target: The ActiveBalance instance being inserted
        """
        # Only sync records with status='done'
        if target.status != 'done':
            logger.debug(
                f"ActiveBalance {target.paymentID}: skipping sync, "
                f"status={target.status} (not 'done')"
            )
            return

        # Skip if amount is None or zero (edge case protection)
        if not target.amount:
            logger.debug(
                f"ActiveBalance {target.paymentID}: skipping sync, "
                f"amount={target.amount}"
            )
            return

        # Update User.balanceActive atomically
        # COALESCE handles NULL balance (treats as 0)
        connection.execute(
            User.__table__.update()
            .where(User.__table__.c.userID == target.userID)
            .values(
                balanceActive=func.coalesce(User.__table__.c.balanceActive, 0) + target.amount
            )
        )

        logger.info(
            f"ActiveBalance SYNC: user={target.userID}, "
            f"amount={target.amount}, reason={target.reason}"
        )

    # =========================================================================
    # PASSIVE BALANCE LISTENER
    # =========================================================================

    @event.listens_for(PassiveBalance, 'after_insert')
    def sync_passive_balance_on_insert(mapper, connection, target):
        """
        Auto-update User.balancePassive when PassiveBalance record is created.

        Args:
            mapper: SQLAlchemy mapper (unused)
            connection: Raw DB connection (used for UPDATE)
            target: The PassiveBalance instance being inserted
        """
        # Only sync records with status='done'
        if target.status != 'done':
            logger.debug(
                f"PassiveBalance {target.paymentID}: skipping sync, "
                f"status={target.status} (not 'done')"
            )
            return

        # Skip if amount is None or zero (edge case protection)
        if not target.amount:
            logger.debug(
                f"PassiveBalance {target.paymentID}: skipping sync, "
                f"amount={target.amount}"
            )
            return

        # Update User.balancePassive atomically
        # COALESCE handles NULL balance (treats as 0)
        connection.execute(
            User.__table__.update()
            .where(User.__table__.c.userID == target.userID)
            .values(
                balancePassive=func.coalesce(User.__table__.c.balancePassive, 0) + target.amount
            )
        )

        logger.info(
            f"PassiveBalance SYNC: user={target.userID}, "
            f"amount={target.amount}, reason={target.reason}"
        )


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