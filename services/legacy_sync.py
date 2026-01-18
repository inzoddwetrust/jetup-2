# services/legacy_sync.py
"""
Legacy Migration Sync Service - Google Sheets ↔ PostgreSQL

Only handles data synchronization:
- Import: GS → PostgreSQL (new records + updates)
- Export: PostgreSQL → GS (progress for customer reporting)

Business logic is in services/legacy_processor.py
"""
import logging
import asyncio
from typing import Dict, Tuple
from decimal import Decimal, InvalidOperation

from models.legacy_migration import LegacyMigrationV1, LegacyMigrationV2
from core.db import get_db_session_ctx
from config import Config

logger = logging.getLogger(__name__)


class LegacySyncService:
    """
    Synchronization between Google Sheets and PostgreSQL.

    Import: New records from GS, updates to existing
    Export: Progress (IsFound, UplinerFound, PurchaseDone) back to GS
    """

    # =========================================================================
    # MAIN ENTRY POINTS
    # =========================================================================

    @staticmethod
    async def sync_all() -> Dict:
        """
        Full sync for both V1 and V2.
        Called from background loop (hourly) and &legacy command.

        Returns:
            Dict with stats: {v1: {...}, v2: {...}}
        """
        logger.info("Starting legacy migrations sync...")

        result = {'v1': {}, 'v2': {}}

        try:
            # V1 (Darwin)
            result['v1'] = await LegacySyncService.sync_v1()
            logger.info(f"V1 sync: {result['v1']}")

            # V2 (Aquix)
            result['v2'] = await LegacySyncService.sync_v2()
            logger.info(f"V2 sync: {result['v2']}")

        except Exception as e:
            logger.error(f"Error in sync_all: {e}", exc_info=True)
            result['error'] = str(e)

        return result

    @staticmethod
    async def import_all() -> Dict:
        """Import only (no export). For initial data load."""
        result = {'v1': {}, 'v2': {}}

        try:
            result['v1']['imported'], result['v1']['updated'] = \
                await LegacySyncService._import_v1()
            result['v2']['imported'], result['v2']['updated'] = \
                await LegacySyncService._import_v2()
        except Exception as e:
            logger.error(f"Error in import_all: {e}", exc_info=True)
            result['error'] = str(e)

        return result

    @staticmethod
    async def export_all() -> Dict:
        """Export only (no import). For manual progress update."""
        result = {'v1': {}, 'v2': {}}

        try:
            result['v1']['exported'] = await LegacySyncService._export_v1()
            result['v2']['exported'] = await LegacySyncService._export_v2()
        except Exception as e:
            logger.error(f"Error in export_all: {e}", exc_info=True)
            result['error'] = str(e)

        return result

    # =========================================================================
    # V1 SYNC (DARWIN)
    # =========================================================================

    @staticmethod
    async def sync_v1() -> Dict:
        """Sync V1 (Darwin) migrations: import + export."""
        stats = {'imported': 0, 'updated': 0, 'exported': 0, 'errors': 0}

        try:
            sheet_id = Config.get('LEGACY_SHEET_ID')
            if not sheet_id:
                logger.warning("LEGACY_SHEET_ID not configured, skipping V1 sync")
                return stats

            # Import
            imported, updated = await LegacySyncService._import_v1()
            stats['imported'] = imported
            stats['updated'] = updated

            # Export
            exported = await LegacySyncService._export_v1()
            stats['exported'] = exported

        except Exception as e:
            logger.error(f"Error in sync_v1: {e}", exc_info=True)
            stats['errors'] = 1

        return stats

    @staticmethod
    async def _import_v1() -> Tuple[int, int]:
        """
        Import V1 records from Google Sheets.

        GS columns: n, email, upliner, project, qty, IsFound, UplinerFound, PurchaseDone

        Returns:
            (imported_count, updated_count)
        """
        from core.google_services import get_google_services

        sheet_id = Config.get('LEGACY_SHEET_ID')
        if not sheet_id:
            return 0, 0

        imported = 0
        updated = 0

        try:
            sheets_client, _ = await get_google_services()

            def _read_sheet():
                sheet = sheets_client.open_by_key(sheet_id).worksheet("Users")
                return sheet.get_all_records()

            rows = await asyncio.to_thread(_read_sheet)
            logger.info(f"V1: Read {len(rows)} rows from Google Sheets")

            with get_db_session_ctx() as session:
                for idx, row in enumerate(rows, start=2):  # Row 1 = header
                    try:
                        # Normalize email
                        email = LegacySyncService._normalize_email(
                            row.get('email', '')
                        )
                        if not email:
                            continue

                        # Check if exists
                        existing = session.query(LegacyMigrationV1).filter_by(
                            email=email,
                            gsRowIndex=idx
                        ).first()

                        if existing:
                            # Update only source fields if changed
                            changed = False

                            new_upliner = row.get('upliner', '').strip().lower()
                            if existing.upliner != new_upliner:
                                existing.upliner = new_upliner
                                changed = True

                            new_project = row.get('project', '').strip()
                            if existing.project != new_project:
                                existing.project = new_project
                                changed = True

                            new_qty = LegacySyncService._parse_qty(row.get('qty'))
                            if existing.qty != new_qty:
                                existing.qty = new_qty
                                changed = True

                            if changed:
                                updated += 1
                        else:
                            # Check if same email exists with different row
                            # (multiple records for same user)
                            migration = LegacyMigrationV1()
                            migration.email = email
                            migration.upliner = row.get('upliner', '').strip().lower()
                            migration.project = row.get('project', '').strip()
                            migration.qty = LegacySyncService._parse_qty(row.get('qty'))
                            migration.gsRowIndex = idx

                            # Import existing progress from GS (for re-imports)
                            is_found = row.get('IsFound', '')
                            if is_found and str(is_found).strip().isdigit():
                                migration.IsFound = int(is_found)

                            migration.UplinerFound = 1 if str(row.get('UplinerFound', '')).strip() == '1' else 0
                            migration.PurchaseDone = 1 if str(row.get('PurchaseDone', '')).strip() == '1' else 0

                            # Determine status
                            if migration.IsFound and migration.UplinerFound and migration.PurchaseDone:
                                migration.status = 'done'
                            else:
                                migration.status = 'pending'

                            session.add(migration)
                            imported += 1

                    except Exception as e:
                        logger.error(f"V1: Error importing row {idx}: {e}")
                        continue

                session.commit()

            logger.info(f"V1 import: {imported} new, {updated} updated")
            return imported, updated

        except Exception as e:
            logger.error(f"Error in _import_v1: {e}", exc_info=True)
            return 0, 0

    @staticmethod
    async def _export_v1() -> int:
        """
        Export V1 progress to Google Sheets.
        Overwrites entire sheet with current data.

        Returns:
            Number of exported records
        """
        from core.google_services import get_google_services

        sheet_id = Config.get('LEGACY_SHEET_ID')
        if not sheet_id:
            return 0

        try:
            with get_db_session_ctx() as session:
                migrations = session.query(LegacyMigrationV1).order_by(
                    LegacyMigrationV1.gsRowIndex.asc().nullslast(),
                    LegacyMigrationV1.migrationID.asc()
                ).all()

                if not migrations:
                    logger.info("V1: No records to export")
                    return 0

                # Prepare rows
                rows = []
                for idx, m in enumerate(migrations, start=2):
                    rows.append([
                        str(idx),  # n
                        m.email or '',  # email
                        m.upliner or '',  # upliner
                        m.project or '',  # project
                        str(m.qty) if m.qty is not None else 'None',  # qty
                        str(m.IsFound) if m.IsFound else '',  # IsFound (userID or empty)
                        '1' if m.UplinerFound else '0',  # UplinerFound
                        '1' if m.PurchaseDone else '0'  # PurchaseDone
                    ])

            # Write to GS
            sheets_client, _ = await get_google_services()

            def _write_sheet():
                sheet = sheets_client.open_by_key(sheet_id).worksheet("Users")
                sheet.clear()

                # Header
                header = ['n', 'email', 'upliner', 'project', 'qty',
                          'IsFound', 'UplinerFound', 'PurchaseDone']
                sheet.append_row(header)

                # Data
                if rows:
                    sheet.append_rows(rows)

            await asyncio.to_thread(_write_sheet)

            logger.info(f"V1: Exported {len(rows)} records to Google Sheets")
            return len(rows)

        except Exception as e:
            logger.error(f"Error in _export_v1: {e}", exc_info=True)
            return 0

    # =========================================================================
    # V2 SYNC (AQUIX)
    # =========================================================================

    @staticmethod
    async def sync_v2() -> Dict:
        """Sync V2 (Aquix) migrations: import + export."""
        stats = {'imported': 0, 'updated': 0, 'exported': 0, 'errors': 0}

        try:
            sheet_id = Config.get('LEGACY_V2_SHEET_ID')
            if not sheet_id:
                logger.warning("LEGACY_V2_SHEET_ID not configured, skipping V2 sync")
                return stats

            # Import
            imported, updated = await LegacySyncService._import_v2()
            stats['imported'] = imported
            stats['updated'] = updated

            # Export
            exported = await LegacySyncService._export_v2()
            stats['exported'] = exported

        except Exception as e:
            logger.error(f"Error in sync_v2: {e}", exc_info=True)
            stats['errors'] = 1

        return stats

    @staticmethod
    async def _import_v2() -> Tuple[int, int]:
        """
        Import V2 records from Google Sheets.

        GS columns: email, parent, value, IsFound, UplinerFound, PurchaseDone

        Returns:
            (imported_count, updated_count)
        """
        from core.google_services import get_google_services

        sheet_id = Config.get('LEGACY_V2_SHEET_ID')
        if not sheet_id:
            return 0, 0

        imported = 0
        updated = 0

        try:
            sheets_client, _ = await get_google_services()

            def _read_sheet():
                sheet = sheets_client.open_by_key(sheet_id).worksheet("Users")
                return sheet.get_all_records()

            rows = await asyncio.to_thread(_read_sheet)
            logger.info(f"V2: Read {len(rows)} rows from Google Sheets")

            with get_db_session_ctx() as session:
                for idx, row in enumerate(rows, start=2):
                    try:
                        email = LegacySyncService._normalize_email(
                            row.get('email', '')
                        )
                        if not email:
                            continue

                        # Check if exists
                        existing = session.query(LegacyMigrationV2).filter_by(
                            email=email,
                            gsRowIndex=idx
                        ).first()

                        if existing:
                            changed = False

                            new_parent = row.get('parent', '').strip().lower()
                            if existing.parent != new_parent:
                                existing.parent = new_parent
                                changed = True

                            new_value = LegacySyncService._parse_value(row.get('value'))
                            if existing.value != new_value:
                                existing.value = new_value
                                changed = True

                            if changed:
                                updated += 1
                        else:
                            migration = LegacyMigrationV2()
                            migration.email = email
                            migration.parent = row.get('parent', '').strip().lower()
                            migration.value = LegacySyncService._parse_value(row.get('value'))
                            migration.gsRowIndex = idx

                            # Import existing progress
                            is_found = row.get('IsFound', '')
                            if is_found and str(is_found).strip().isdigit():
                                migration.IsFound = int(is_found)

                            migration.UplinerFound = 1 if str(row.get('UplinerFound', '')).strip() == '1' else 0
                            migration.PurchaseDone = 1 if str(row.get('PurchaseDone', '')).strip() == '1' else 0

                            # Determine status
                            if migration.IsFound and migration.UplinerFound and migration.PurchaseDone:
                                migration.status = 'done'
                            else:
                                migration.status = 'pending'

                            session.add(migration)
                            imported += 1

                    except Exception as e:
                        logger.error(f"V2: Error importing row {idx}: {e}")
                        continue

                session.commit()

            logger.info(f"V2 import: {imported} new, {updated} updated")
            return imported, updated

        except Exception as e:
            logger.error(f"Error in _import_v2: {e}", exc_info=True)
            return 0, 0

    @staticmethod
    async def _export_v2() -> int:
        """
        Export V2 progress to Google Sheets.

        Returns:
            Number of exported records
        """
        from core.google_services import get_google_services

        sheet_id = Config.get('LEGACY_V2_SHEET_ID')
        if not sheet_id:
            return 0

        try:
            with get_db_session_ctx() as session:
                migrations = session.query(LegacyMigrationV2).order_by(
                    LegacyMigrationV2.gsRowIndex.asc().nullslast(),
                    LegacyMigrationV2.migrationID.asc()
                ).all()

                if not migrations:
                    logger.info("V2: No records to export")
                    return 0

                rows = []
                for idx, m in enumerate(migrations, start=2):
                    # Format value: None stays as "None", 0 as "0", else number
                    if m.value is None:
                        value_str = 'None'
                    else:
                        value_str = str(m.value)

                    rows.append([
                        m.email or '',  # email
                        m.parent or '',  # parent
                        value_str,  # value
                        str(m.IsFound) if m.IsFound else '',  # IsFound
                        '1' if m.UplinerFound else '0',  # UplinerFound
                        '1' if m.PurchaseDone else '0'  # PurchaseDone
                    ])

            # Write to GS
            sheets_client, _ = await get_google_services()

            def _write_sheet():
                sheet = sheets_client.open_by_key(sheet_id).worksheet("Users")
                sheet.clear()

                header = ['email', 'parent', 'value', 'IsFound', 'UplinerFound', 'PurchaseDone']
                sheet.append_row(header)

                if rows:
                    sheet.append_rows(rows)

            await asyncio.to_thread(_write_sheet)

            logger.info(f"V2: Exported {len(rows)} records to Google Sheets")
            return len(rows)

        except Exception as e:
            logger.error(f"Error in _export_v2: {e}", exc_info=True)
            return 0

    # =========================================================================
    # HELPERS
    # =========================================================================

    @staticmethod
    def _normalize_email(email: str) -> str:
        """
        Normalize email: lowercase, strip, Gmail dot handling.
        """
        if not email:
            return ""

        email = str(email).lower().strip()

        # Gmail ignores dots in local part
        if '@gmail.com' in email:
            local, domain = email.split('@', 1)
            local = local.replace('.', '')
            return f"{local}@{domain}"

        return email

    @staticmethod
    def _parse_qty(value) -> int | None:
        """
        Parse qty field from GS.

        Returns:
            Integer, or None if "None" or empty
        """
        if value is None:
            return None

        value_str = str(value).strip()

        if value_str.lower() == 'none' or value_str == '':
            return None

        try:
            return int(value_str)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_value(value) -> Decimal | None:
        """
        Parse value field from GS (V2).

        Returns:
            Decimal, or None if "None" or empty
        """
        if value is None:
            return None

        value_str = str(value).strip()

        if value_str.lower() == 'none' or value_str == '':
            return None

        try:
            return Decimal(value_str)
        except (InvalidOperation, ValueError, TypeError):
            return None