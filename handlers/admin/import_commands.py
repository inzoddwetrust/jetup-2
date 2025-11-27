# handlers/admin/import_commands.py
"""
Data import and backup management commands for admins.

Commands:
    &import  - Import data from Google Sheets
    &restore - Restore database from backup

Templates used:
    admin/import/unknown_table
    admin/import/backup_error
    admin/sync/starting
    admin/sync/processing_table
    admin/sync/report_header
    admin/sync/report_summary
    admin/sync/table_stats
    admin/sync/backup_created
    admin/sync/critical_error
    admin/restore/list
    admin/restore/not_found
    admin/restore/success
    admin/restore/error
"""
import os
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy.orm import Session

from config import Config
from core.db import get_session
from core.message_manager import MessageManager
from models.user import User
from sync_system.sync_config import SUPPORT_TABLES, IMPORT_MODES
from sync_system.sync_engine import UniversalSyncEngine

logger = logging.getLogger(__name__)

# =============================================================================
# BACKUP CONFIGURATION
# =============================================================================

BACKUP_BASE_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
BACKUP_DIRS = {
    'import': BACKUP_BASE_DIR / 'import',
    'daily': BACKUP_BASE_DIR / 'daily',
    'manual': BACKUP_BASE_DIR / 'manual',
    'restore': BACKUP_BASE_DIR / 'restore'
}

# =============================================================================
# ROUTER SETUP
# =============================================================================

import_router = Router(name="admin_import")


# =============================================================================
# BACKUP UTILITIES
# =============================================================================

async def create_backup(category: str = 'import') -> str:
    """
    Create database backup.

    Args:
        category: Backup category - 'import', 'manual', 'daily', 'restore'

    Returns:
        Path to created backup file
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    backup_dir = BACKUP_DIRS.get(category, BACKUP_DIRS['manual'])
    os.makedirs(backup_dir, exist_ok=True)

    database_url = Config.get(Config.DATABASE_URL)
    if database_url.startswith("sqlite:///"):
        db_path = database_url.replace("sqlite:///", "")
    else:
        raise ValueError(f"Unsupported DATABASE_URL format: {database_url}")

    if not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")

    backup_filename = f"jetup_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)
    shutil.copy2(db_path, backup_path)

    # Cleanup old backups (keep last 20)
    backups = sorted([f for f in os.listdir(backup_dir) if f.endswith('.db')])
    if len(backups) > 20:
        for old_backup in backups[:-20]:
            os.remove(os.path.join(backup_dir, old_backup))
            logger.info(f"Removed old backup: {old_backup}")

    logger.info(f"Backup created: {backup_path}")
    return backup_path


def get_available_backups(category: str = 'import', limit: int = 10) -> list:
    """Get list of available backup files."""
    backup_dir = BACKUP_DIRS.get(category, BACKUP_DIRS['import'])

    if not os.path.exists(backup_dir):
        return []

    backups = sorted(
        [f for f in os.listdir(backup_dir) if f.endswith('.db')],
        reverse=True
    )
    return backups[:limit]


# =============================================================================
# &import - Import data from Google Sheets
# =============================================================================

@import_router.message(F.text.regexp(r'^&import'))
async def cmd_import(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Import data from Google Sheets.

    Usage:
        &import                    - dry run, all tables
        &import Users              - dry run, Users only
        &import Payments safe      - safe mode, Payments only
        &import --all force        - force mode, all tables
    """
    logger.info(f"Admin {message.from_user.id} triggered &import")

    # Parse command arguments
    command_parts = message.text.strip().split()
    mode = 'dry'
    tables_to_import = SUPPORT_TABLES.copy()

    if len(command_parts) > 1:
        args = command_parts[1:]
        remaining_args = []

        for arg in args:
            arg_lower = arg.lower()
            if arg_lower in IMPORT_MODES:
                mode = arg_lower
            elif arg_lower == '--all':
                tables_to_import = SUPPORT_TABLES.copy()
            else:
                remaining_args.append(arg)

        # Validate table names
        if remaining_args:
            tables_str = ' '.join(remaining_args)
            requested_tables = [t.strip() for t in tables_str.replace(',', ' ').split()]

            valid_tables = []
            for table in requested_tables:
                matched = next(
                    (t for t in SUPPORT_TABLES if t.lower() == table.lower()),
                    None
                )
                if matched:
                    valid_tables.append(matched)
                else:
                    await message_manager.send_template(
                        user=user,
                        template_key='admin/import/unknown_table',
                        variables={'table': table},
                        update=message
                    )
                    return

            if valid_tables:
                tables_to_import = valid_tables

    # Create backup if not dry run
    backup_path = None
    if mode != 'dry':
        try:
            backup_path = await create_backup(category='import')
            logger.info(f"Pre-import backup created: {backup_path}")
        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            await message_manager.send_template(
                user=user,
                template_key='admin/import/backup_error',
                variables={'error': str(e)},
                update=message
            )
            return

    # Send starting message
    await message_manager.send_template(
        user=user,
        template_key='admin/sync/starting',
        variables={
            'mode': mode,
            'tables': ', '.join(tables_to_import)
        },
        update=message
    )

    # Import tables
    all_results: Dict[str, Any] = {}
    total_stats = {
        'total': 0,
        'updated': 0,
        'added': 0,
        'skipped': 0,
        'errors': 0
    }

    try:
        import_session = get_session()
        try:
            for table_name in tables_to_import:
                try:
                    # Send progress update
                    await message_manager.send_template(
                        user=user,
                        template_key='admin/sync/processing_table',
                        variables={'table': table_name, 'mode': mode},
                        update=message
                    )

                    # Use UniversalSyncEngine
                    engine = UniversalSyncEngine(table_name)
                    dry_run = (mode == 'dry')

                    results = engine.import_from_sheets(
                        session=import_session,
                        dry_run=dry_run
                    )

                    all_results[table_name] = results

                    total_stats['total'] += results.get('total', 0)
                    total_stats['added'] += results.get('added', 0)
                    total_stats['updated'] += results.get('updated', 0)
                    total_stats['skipped'] += results.get('skipped', 0)
                    total_stats['errors'] += len(results.get('errors', []))

                except Exception as e:
                    logger.error(f"Error importing {table_name}: {e}", exc_info=True)
                    all_results[table_name] = {'error': str(e)}
                    total_stats['errors'] += 1

        finally:
            import_session.close()

        # Send report
        if total_stats['errors'] == 0:
            icon = '✅'
        else:
            icon = '⚠️'

        await message_manager.send_template(
            user=user,
            template_key=['admin/sync/report_header', 'admin/sync/report_summary'],
            variables={
                'mode': mode,
                'icon': icon,
                'updated': total_stats['updated'],
                'added': total_stats['added'],
                'skipped': total_stats['skipped'],
                'errors': total_stats['errors'],
                'backup_path': os.path.basename(backup_path) if backup_path else ''
            },
            update=message
        )

        # Send detailed table stats
        for table_name, results in all_results.items():
            if isinstance(results, dict) and 'error' not in results:
                await message_manager.send_template(
                    user=user,
                    template_key='admin/sync/table_stats',
                    variables={
                        'table': table_name,
                        'total': results.get('total', 0),
                        'added': results.get('added', 0),
                        'updated': results.get('updated', 0),
                        'skipped': results.get('skipped', 0),
                        'errors': len(results.get('errors', []))
                    },
                    update=message
                )

        # Show backup info if created
        if backup_path:
            await message_manager.send_template(
                user=user,
                template_key='admin/sync/backup_created',
                variables={'path': os.path.basename(backup_path)},
                update=message
            )

    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/sync/critical_error',
            variables={'error': str(e)},
            update=message
        )


# =============================================================================
# &restore - Restore database from backup
# =============================================================================

@import_router.message(F.text.regexp(r'^&restore'))
async def cmd_restore(
        message: Message,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """
    Restore database from backup.

    Usage:
        &restore              - Show available backups
        &restore <filename>   - Restore from specific backup
    """
    logger.info(f"Admin {message.from_user.id} triggered &restore")

    args = message.text.split()[1:] if len(message.text.split()) > 1 else []

    if not args:
        # Show available backups
        all_backups = []

        for category in ['import', 'manual', 'restore']:
            backups = get_available_backups(category, limit=5)
            if backups:
                all_backups.extend(backups)

        await message_manager.send_template(
            user=user,
            template_key='admin/restore/list',
            variables={
                'backups': '\n'.join(all_backups) if all_backups else 'No backups available',
                'count': len(all_backups)
            },
            update=message
        )
        return

    # Restore from specific backup
    backup_name = args[0]

    # Search for backup in all directories
    backup_path = None
    for category in ['import', 'manual', 'restore', 'daily']:
        potential_path = BACKUP_DIRS.get(category, Path('./backups')) / backup_name
        if os.path.exists(potential_path):
            backup_path = str(potential_path)
            break

    if not backup_path:
        await message_manager.send_template(
            user=user,
            template_key='admin/restore/not_found',
            variables={'filename': backup_name},
            update=message
        )
        return

    try:
        # Create backup of current state before restore
        current_backup = await create_backup(category='restore')
        logger.info(f"Pre-restore backup created: {current_backup}")

        # Get database path
        database_url = Config.get(Config.DATABASE_URL)
        if database_url.startswith("sqlite:///"):
            db_path = database_url.replace("sqlite:///", "")
        else:
            raise ValueError(f"Unsupported DATABASE_URL format: {database_url}")

        # Restore
        shutil.copy2(backup_path, db_path)
        logger.info(f"Database restored from: {backup_path}")

        await message_manager.send_template(
            user=user,
            template_key='admin/restore/success',
            variables={
                'restored_from': backup_name,
                'previous_saved': os.path.basename(current_backup)
            },
            update=message
        )

    except Exception as e:
        logger.error(f"Restore failed: {e}", exc_info=True)
        await message_manager.send_template(
            user=user,
            template_key='admin/restore/error',
            variables={'error': str(e)},
            update=message
        )


# =============================================================================
# EXPORTS
# =============================================================================

__all__ = ['import_router', 'create_backup', 'get_available_backups']