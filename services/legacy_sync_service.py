# services/legacy_sync_service.py
"""
Legacy Migration Sync Service - Google Sheets ↔ PostgreSQL

Синхронизирует данные миграции между Google Sheets и PostgreSQL.
Запускается раз в час в background.

Логика:
1. ИМПОРТ: Google Sheets → PostgreSQL (новые записи + обновления)
2. ЭКСПОРТ: PostgreSQL → Google Sheets (полная перезапись листа)
"""
import logging
import asyncio
from typing import List, Dict, Any
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.legacy_migration import LegacyMigrationV1, LegacyMigrationV2
from core.db import get_db_session_ctx
from config import Config

logger = logging.getLogger(__name__)


class LegacySyncService:
    """
    Синхронизация legacy миграций между Google Sheets и PostgreSQL.

    Два направления:
    - Импорт: новые записи из GS в БД
    - Экспорт: весь прогресс из БД обратно в GS
    """

    # =========================================================================
    # MAIN ENTRY POINT
    # =========================================================================

    @staticmethod
    async def sync_all():
        """
        Синхронизировать обе таблицы (V1 и V2).
        Вызывается раз в час из background.
        """
        logger.info("Starting legacy migrations sync...")

        try:
            # V1 (Darwin)
            v1_stats = await LegacySyncService.sync_v1_migrations()
            logger.info(f"V1 sync: {v1_stats}")

            # V2 (Jetup)
            v2_stats = await LegacySyncService.sync_v2_migrations()
            logger.info(f"V2 sync: {v2_stats}")

            return {
                'v1': v1_stats,
                'v2': v2_stats
            }

        except Exception as e:
            logger.error(f"Error in sync_all: {e}", exc_info=True)
            raise

    # =========================================================================
    # V1 SYNC (DARWIN)
    # =========================================================================

    @staticmethod
    async def sync_v1_migrations() -> Dict[str, int]:
        """
        Синхронизировать V1 (Darwin) миграции.

        Returns:
            Dict с статистикой: imported, updated, exported
        """
        stats = {
            'imported': 0,
            'updated': 0,
            'exported': 0,
            'errors': 0
        }

        try:
            sheet_id = Config.get('LEGACY_SHEET_ID')
            if not sheet_id:
                logger.warning("LEGACY_SHEET_ID not configured, skipping V1 sync")
                return stats

            # STEP 1: ИМПОРТ из Google Sheets
            imported, updated = await LegacySyncService._import_v1_from_sheets(sheet_id)
            stats['imported'] = imported
            stats['updated'] = updated

            # STEP 2: ЭКСПОРТ в Google Sheets
            exported = await LegacySyncService._export_v1_to_sheets(sheet_id)
            stats['exported'] = exported

            logger.info(
                f"V1 sync complete: imported={imported}, updated={updated}, exported={exported}"
            )
            return stats

        except Exception as e:
            logger.error(f"Error in sync_v1_migrations: {e}", exc_info=True)
            stats['errors'] = 1
            return stats

    @staticmethod
    async def _import_v1_from_sheets(sheet_id: str) -> tuple:
        """
        Импорт V1 записей из Google Sheets в PostgreSQL.

        Returns:
            (imported_count, updated_count)
        """
        from core.google_services import get_google_services

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
                for idx, row in enumerate(rows, start=2):  # Start from 2 (row 1 = header)
                    try:
                        email = row.get('email', '').strip().lower()
                        if not email:
                            continue

                        # Check if exists
                        existing = session.query(LegacyMigrationV1).filter_by(
                            email=email
                        ).first()

                        if existing:
                            # Update only if data changed
                            changed = False

                            if existing.upliner != row.get('upliner', '').strip().lower():
                                existing.upliner = row.get('upliner', '').strip().lower()
                                changed = True

                            if existing.project != row.get('project', '').strip():
                                existing.project = row.get('project', '').strip()
                                changed = True

                            try:
                                qty = int(row.get('qty', 0))
                                if existing.qty != qty:
                                    existing.qty = qty
                                    changed = True
                            except (ValueError, TypeError):
                                pass

                            if changed:
                                updated += 1
                        else:
                            # Create new record
                            migration = LegacyMigrationV1()
                            migration.email = email
                            migration.upliner = row.get('upliner', '').strip().lower()
                            migration.project = row.get('project', '').strip()

                            try:
                                migration.qty = int(row.get('qty', 0))
                            except (ValueError, TypeError):
                                migration.qty = 0

                            migration.gsRowIndex = idx

                            # Determine status from GS flags
                            is_found = str(row.get('IsFound', '')).strip()
                            upliner_found = str(row.get('UplinerFound', '')).strip()
                            purchase_done = str(row.get('PurchaseDone', '')).strip()

                            # Status logic:
                            # - completed: PurchaseDone=1 AND UplinerFound=1
                            # - purchase_done: PurchaseDone=1 but UplinerFound=0
                            # - pending: otherwise
                            if purchase_done == '1' and upliner_found == '1':
                                migration.status = 'completed'
                            elif purchase_done == '1':
                                migration.status = 'purchase_done'
                            else:
                                migration.status = 'pending'

                            session.add(migration)
                            imported += 1

                    except Exception as e:
                        logger.error(f"V1: Error importing row {idx}: {e}")
                        continue

                session.commit()

            return imported, updated

        except Exception as e:
            logger.error(f"Error in _import_v1_from_sheets: {e}", exc_info=True)
            return 0, 0

    @staticmethod
    async def _export_v1_to_sheets(sheet_id: str) -> int:
        """
        Экспорт V1 записей из PostgreSQL в Google Sheets.
        Полностью перезаписывает лист.

        Returns:
            Количество экспортированных записей
        """
        from core.google_services import get_google_services

        try:
            # Read all from DB
            with get_db_session_ctx() as session:
                migrations = session.query(LegacyMigrationV1).order_by(
                    LegacyMigrationV1.migrationID
                ).all()

                # Prepare data for export
                rows = []
                for idx, m in enumerate(migrations, start=2):  # Start from 2 (row 1 is header)
                    rows.append([
                        str(idx),  # n (row number in Google Sheets)
                        m.email or '',
                        m.upliner or '',
                        m.project or '',
                        str(m.qty) if m.qty else '0',
                        '1' if m.status in ['purchase_done', 'completed'] else '0',  # IsFound
                        '1' if m.uplinerID else '0',  # UplinerFound
                        '1' if m.purchaseID else '0'  # PurchaseDone
                    ])

            if not rows:
                logger.info("V1: No records to export")
                return 0

            # Write to Google Sheets
            sheets_client, _ = await get_google_services()

            def _write_sheet():
                sheet = sheets_client.open_by_key(sheet_id).worksheet("Users")

                # Clear sheet (except header)
                sheet.clear()

                # Write header
                header = ['n', 'email', 'upliner', 'project', 'qty',
                          'IsFound', 'UplinerFound', 'PurchaseDone']
                sheet.append_row(header)

                # Write all data in one batch
                if rows:
                    sheet.append_rows(rows)

            await asyncio.to_thread(_write_sheet)

            logger.info(f"V1: Exported {len(rows)} records to Google Sheets")
            return len(rows)

        except Exception as e:
            logger.error(f"Error in _export_v1_to_sheets: {e}", exc_info=True)
            return 0

    # =========================================================================
    # V2 SYNC (JETUP)
    # =========================================================================

    @staticmethod
    async def sync_v2_migrations() -> Dict[str, int]:
        """
        Синхронизировать V2 (Jetup) миграции.

        Returns:
            Dict с статистикой: imported, updated, exported
        """
        stats = {
            'imported': 0,
            'updated': 0,
            'exported': 0,
            'errors': 0
        }

        try:
            sheet_id = Config.get('LEGACY_V2_SHEET_ID')
            if not sheet_id:
                logger.warning("LEGACY_V2_SHEET_ID not configured, skipping V2 sync")
                return stats

            # STEP 1: ИМПОРТ из Google Sheets
            imported, updated = await LegacySyncService._import_v2_from_sheets(sheet_id)
            stats['imported'] = imported
            stats['updated'] = updated

            # STEP 2: ЭКСПОРТ в Google Sheets
            exported = await LegacySyncService._export_v2_to_sheets(sheet_id)
            stats['exported'] = exported

            logger.info(
                f"V2 sync complete: imported={imported}, updated={updated}, exported={exported}"
            )
            return stats

        except Exception as e:
            logger.error(f"Error in sync_v2_migrations: {e}", exc_info=True)
            stats['errors'] = 1
            return stats

    @staticmethod
    async def _import_v2_from_sheets(sheet_id: str) -> tuple:
        """
        Импорт V2 записей из Google Sheets в PostgreSQL.

        Returns:
            (imported_count, updated_count)
        """
        from core.google_services import get_google_services

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
                        email = row.get('email', '').strip().lower()
                        if not email:
                            continue

                        # Check if exists
                        existing = session.query(LegacyMigrationV2).filter_by(
                            email=email
                        ).first()

                        if existing:
                            # Update only if data changed
                            changed = False

                            if existing.parent != row.get('parent', '').strip().lower():
                                existing.parent = row.get('parent', '').strip().lower()
                                changed = True

                            try:
                                value = Decimal(str(row.get('value', 0)))
                                if existing.value != value:
                                    existing.value = value
                                    changed = True
                            except (ValueError, TypeError, KeyError):
                                pass

                            if changed:
                                updated += 1
                        else:
                            # Create new record
                            migration = LegacyMigrationV2()
                            migration.email = email
                            migration.parent = row.get('parent', '').strip().lower()

                            try:
                                migration.value = int(row.get('value', 0))
                            except (ValueError, TypeError, KeyError):
                                migration.value = 0

                            migration.gsRowIndex = idx

                            # Determine status from GS flags
                            is_found = str(row.get('IsFound', '')).strip()
                            upliner_found = str(row.get('UplinerFound', '')).strip()
                            purchase_done = str(row.get('PurchaseDone', '')).strip()

                            # Status logic:
                            # - completed: PurchaseDone=1 AND UplinerFound=1
                            # - purchase_done: PurchaseDone=1 but UplinerFound=0
                            # - pending: otherwise
                            if purchase_done == '1' and upliner_found == '1':
                                migration.status = 'completed'
                            elif purchase_done == '1':
                                migration.status = 'purchase_done'
                            else:
                                migration.status = 'pending'

                            session.add(migration)
                            imported += 1

                    except Exception as e:
                        logger.error(f"V2: Error importing row {idx}: {e}")
                        continue

                session.commit()

            return imported, updated

        except Exception as e:
            logger.error(f"Error in _import_v2_from_sheets: {e}", exc_info=True)
            return 0, 0

    @staticmethod
    async def _export_v2_to_sheets(sheet_id: str) -> int:
        """
        Экспорт V2 записей из PostgreSQL в Google Sheets.
        Полностью перезаписывает лист.

        Returns:
            Количество экспортированных записей
        """
        from core.google_services import get_google_services

        try:
            # Read all from DB
            with get_db_session_ctx() as session:
                migrations = session.query(LegacyMigrationV2).order_by(
                    LegacyMigrationV2.migrationID
                ).all()

                # Prepare data for export
                rows = []
                for idx, m in enumerate(migrations, start=2):  # Start from 2 (row 1 is header)
                    rows.append([
                        str(idx),  # n (row number in Google Sheets)
                        m.email or '',
                        m.parent or '',
                        '1' if m.status in ['purchase_done', 'completed'] else '0',  # IsFound
                        '1' if m.parentID else '0',  # UplinerFound
                        '1' if m.jetupBalanceID and m.aquixBalanceID else '0',  # PurchaseDone
                        str(int(m.value)) if m.value else '0'  # value
                    ])

            if not rows:
                logger.info("V2: No records to export")
                return 0

            # Write to Google Sheets
            sheets_client, _ = await get_google_services()

            def _write_sheet():
                sheet = sheets_client.open_by_key(sheet_id).worksheet("Users")

                # Clear sheet (except header)
                sheet.clear()

                # Write header
                header = ['n', 'email', 'parent', 'IsFound', 'UplinerFound',
                          'PurchaseDone', 'value']
                sheet.append_row(header)

                # Write all data in one batch
                if rows:
                    sheet.append_rows(rows)

            await asyncio.to_thread(_write_sheet)

            logger.info(f"V2: Exported {len(rows)} records to Google Sheets")
            return len(rows)

        except Exception as e:
            logger.error(f"Error in _export_v2_to_sheets: {e}", exc_info=True)
            return 0