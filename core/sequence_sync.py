# core/sequence_sync.py
"""
PostgreSQL sequence synchronization utility.

Automatically syncs all table sequences with existing data on bot startup.
Prevents "duplicate key" errors when data is imported with explicit IDs.
"""
import logging
from sqlalchemy import text
from core.db import get_db_session_ctx

logger = logging.getLogger(__name__)

# Map of table_name -> (sequence_name, pk_column_name)
SEQUENCES_CONFIG = {
    'active_balances': ('active_balances_paymentID_seq', 'paymentID'),
    'passive_balances': ('passive_balances_paymentID_seq', 'paymentID'),
    'payments': ('payments_paymentID_seq', 'paymentID'),
    'purchases': ('purchases_purchaseID_seq', 'purchaseID'),
    'transfers': ('transfers_transferID_seq', 'transferID'),
    'bonuses': ('bonuses_bonusID_seq', 'bonusID'),
    'users': ('users_userID_seq', 'userID'),
    'projects': ('projects_id_seq', 'id'),
    'notifications': ('notifications_notificationID_seq', 'notificationID'),
    'options': ('options_optionID_seq', 'optionID'),
    # MLM tables
    'global_pool': ('global_pool_poolID_seq', 'poolID'),
    'monthly_stats': ('monthly_stats_statsID_seq', 'statsID'),
    'rank_history': ('rank_history_historyID_seq', 'historyID'),
    'system_time': ('system_time_timeID_seq', 'timeID'),
    'notification_deliveries': ('notification_deliveries_deliveryID_seq', 'deliveryID'),
    'volume_update_queue': ('volume_update_queue_id_seq', 'id'),
}


async def sync_all_sequences() -> dict:
    """
    Sync all PostgreSQL sequences with existing table data.

    This fixes sequence conflicts when data was imported with explicit IDs.
    Safe to call multiple times - uses setval with is_called=false.

    Returns:
        Dict with sync results: {table_name: status}
    """
    logger.info("Starting PostgreSQL sequence synchronization...")

    results = {}
    synced_count = 0
    error_count = 0

    with get_db_session_ctx() as session:
        for table_name, (sequence_name, pk_column) in SEQUENCES_CONFIG.items():
            try:
                # Build SQL query
                sql = text(f"""
                    SELECT setval(
                        '"{sequence_name}"',
                        (SELECT COALESCE(MAX("{pk_column}"), 0) + 1 FROM {table_name}),
                        false
                    )
                """)

                # Execute
                result = session.execute(sql)
                new_value = result.scalar()

                results[table_name] = f"✓ synced to {new_value}"
                synced_count += 1
                logger.debug(f"Synced {table_name}: sequence → {new_value}")

            except Exception as e:
                # CRITICAL: Rollback to clear failed transaction
                session.rollback()

                error_msg = str(e)
                results[table_name] = f"✗ error: {error_msg[:50]}"
                error_count += 1
                logger.warning(f"Could not sync {table_name}: {error_msg}")

        # Commit all successful changes
        try:
            session.commit()
        except Exception as e:
            logger.warning(f"Could not commit sequence sync: {e}")

    # Log summary
    if synced_count > 0:
        logger.info(f"✓ Synced {synced_count} sequences successfully")
    if error_count > 0:
        logger.warning(f"✗ Failed to sync {error_count} sequences (non-critical)")

    return results


async def sync_sequence(table_name: str) -> bool:
    """
    Sync a single table's sequence.

    Args:
        table_name: Name of the table (must be in SEQUENCES_CONFIG)

    Returns:
        True if synced successfully, False otherwise
    """
    if table_name not in SEQUENCES_CONFIG:
        logger.error(f"Unknown table: {table_name}")
        return False

    sequence_name, pk_column = SEQUENCES_CONFIG[table_name]

    try:
        with get_db_session_ctx() as session:
            sql = text(f"""
                SELECT setval(
                    '"{sequence_name}"',
                    (SELECT COALESCE(MAX("{pk_column}"), 0) + 1 FROM {table_name}),
                    false
                )
            """)

            result = session.execute(sql)
            new_value = result.scalar()
            session.commit()

            logger.info(f"✓ Synced {table_name} sequence to {new_value}")
            return True

    except Exception as e:
        logger.warning(f"Could not sync {table_name}: {e}")
        return False