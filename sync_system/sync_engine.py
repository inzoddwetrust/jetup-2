# sync_system/sync_engine.py
"""
Universal sync engine for DB <-> Google Sheets.
Supports JSON fields and Decimal for new DB structure.
"""
import logging
import json
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import Session

from config import Config
from sync_system.sync_config import (
    SYNC_CONFIG, validate_upliner, validate_foreign_key, get_default_referrer_id
)
from models import User

logger = logging.getLogger(__name__)


class UniversalSyncEngine:
    """Universal engine for syncing any table."""

    def __init__(self, table_name: str):
        if table_name not in SYNC_CONFIG:
            raise ValueError(f"Unknown table: {table_name}")

        self.table_name = table_name
        self.config = SYNC_CONFIG[table_name]
        self.model = self.config['model']
        self.primary_key = self.config['primary_key']
        self.sheet_name = self.config['sheet_name']

    def export_to_json(self, session: Session) -> Dict[str, Any]:
        """Export data from DB to JSON for Google Sheets."""
        try:
            records = session.query(self.model).all()

            # Определяем поля для экспорта из sync_config
            readonly = self.config.get('readonly_fields', [])
            editable = self.config.get('editable_fields', [])
            export_fields = readonly + editable

            data = []
            for record in records:
                row = {}
                for field_name in export_fields:  # ← ИЗМЕНЕНО: только нужные поля
                    value = getattr(record, field_name, None)  # ← ИЗМЕНЕНО: добавил default

                    # Convert special types
                    if isinstance(value, datetime):
                        value = value.strftime("%Y-%m-%d %H:%M:%S")
                    elif isinstance(value, Decimal):
                        value = float(value)
                    elif value is None:
                        value = ""
                    elif isinstance(value, bool):
                        value = int(value)
                    elif isinstance(value, dict):
                        value = json.dumps(value, ensure_ascii=False)
                    elif field_name in ['personalData', 'emailVerification', 'settings', 'mlmStatus', 'mlmVolumes']:
                        if isinstance(value, str) and value:
                            try:
                                json.loads(value)
                            except:
                                pass

                    row[field_name] = value
                data.append(row)

            return {
                'success': True,
                'table': self.table_name,
                'rows': data,
                'count': len(data),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            logger.error(f"Export error for {self.table_name}: {e}")
            return {
                'success': False,
                'error': str(e),
                'table': self.table_name
            }

    def import_from_sheets(self, session: Session, dry_run: bool = False) -> Dict[str, Any]:
        """Import data from Google Sheets to DB."""
        results = {
            'table': self.table_name,
            'total': 0,
            'updated': 0,
            'added': 0,
            'skipped': 0,
            'errors': [],
            'warnings': [],
            'changes': []
        }

        try:
            # Connect to Google Sheets (sync call - gspread is sync)
            from core.google_services import get_sheets_client
            sheets_client = get_sheets_client()
            sheet_id = Config.get(Config.GOOGLE_SHEET_ID)
            spreadsheet = sheets_client.open_by_key(sheet_id)
            sheet = spreadsheet.worksheet(self.sheet_name)

            # Get raw data
            raw_records = sheet.get_all_records()

            # Clean data from Google Sheets
            sheet_records = []
            for idx, raw_row in enumerate(raw_records):
                clean_row = {}
                for key, value in raw_row.items():
                    clean_key = key.strip().replace('\u200b', '').replace('\xa0', ' ')

                    if value == '' or value is None:
                        clean_row[clean_key] = None
                    elif isinstance(value, str):
                        clean_row[clean_key] = value.strip() if value.strip() else None
                    else:
                        clean_row[clean_key] = value

                if any(v is not None for v in clean_row.values()):
                    sheet_records.append(clean_row)

            results['total'] = len(sheet_records)

            consecutive_errors = 0
            last_error = ""

            for row_idx, row in enumerate(sheet_records, start=2):
                try:
                    # Check balances BEFORE processing (for Users)
                    balance_warning = None
                    if self.table_name == 'Users':
                        balance_fields = ['balanceActive', 'balancePassive']
                        for field in balance_fields:
                            if field in row and row[field] is not None:
                                sheet_value = self._parse_decimal(row[field])
                                primary_value = row.get('telegramID')
                                if primary_value:
                                    existing = session.query(self.model).filter_by(telegramID=primary_value).first()
                                    if existing:
                                        db_value = getattr(existing, field, Decimal("0"))
                                        if abs(sheet_value - db_value) > Decimal("0.01"):
                                            warning_msg = f"Balance mismatch in {field}: DB={db_value}, sheet={sheet_value}"
                                            logger.warning(f"Row {row_idx}: {warning_msg}")
                                            results['warnings'].append({
                                                'row': row_idx,
                                                'warning': warning_msg,
                                                'field': field,
                                                'db_value': float(db_value),
                                                'sheet_value': float(sheet_value)
                                            })
                                            results['skipped'] += 1
                                            balance_warning = True
                                            break

                    if balance_warning:
                        continue

                    result = self._process_row(session, row, row_idx, dry_run)

                    if result['action'] == 'update':
                        results['updated'] += 1
                        results['changes'].append({
                            'row': row_idx,
                            'id': row.get(self.primary_key),
                            'action': 'update',
                            'fields': result.get('changes', [])
                        })
                    elif result['action'] == 'add':
                        results['added'] += 1
                        results['changes'].append({
                            'row': row_idx,
                            'id': row.get(self.primary_key),
                            'action': 'add'
                        })
                    elif result['action'] == 'skip':
                        results['skipped'] += 1
                    elif result['action'] == 'error':
                        if 'error' in result:
                            results['errors'].append({
                                'row': row_idx,
                                'error': result['error'],
                                'id': row.get('telegramID' if self.table_name == 'Users' else self.primary_key)
                            })

                    consecutive_errors = 0

                except Exception as e:
                    error_msg = str(e)[:500]

                    if not dry_run:
                        try:
                            session.rollback()
                        except:
                            pass

                    logger.error(f"Error processing row {row_idx}: {error_msg}")
                    results['errors'].append({
                        'row': row_idx,
                        'error': error_msg,
                        'id': row.get('telegramID' if self.table_name == 'Users' else self.primary_key)
                    })

                    if error_msg[:100] == last_error:
                        consecutive_errors += 1
                    else:
                        consecutive_errors = 1
                        last_error = error_msg[:100]

                    if consecutive_errors > 50:
                        logger.error(f"Too many identical errors ({consecutive_errors}), stopping import")
                        break

            # Commit results
            if not dry_run:
                if results['errors']:
                    logger.warning(f"Import completed with {len(results['errors'])} errors")
                session.commit()
                logger.info(
                    f"Results: {results['added']} added, {results['updated']} updated, "
                    f"{results['skipped']} skipped, {len(results['errors'])} errors"
                )
            else:
                logger.info(f"Dry run completed, no changes applied")

        except Exception as e:
            session.rollback()
            logger.error(f"Import failed for {self.table_name}: {e}")
            results['errors'].append({
                'row': 0,
                'error': f"Critical error: {str(e)}"
            })

        return results

    def _process_row(self, session: Session, row: Dict, row_idx: int, dry_run: bool) -> Dict:
        """Process one row from Google Sheets."""
        try:
            if self.table_name == 'Users':
                telegram_id = row.get('telegramID')
                if not telegram_id:
                    return {'action': 'skip'}
                record = session.query(self.model).filter_by(telegramID=telegram_id).first()
            else:
                record_id = row.get(self.primary_key)
                if not record_id:
                    return {'action': 'skip'}
                record = session.query(self.model).filter(
                    getattr(self.model, self.primary_key) == record_id
                ).first()

            if record:
                changes = self._update_record(session, record, row, row_idx, dry_run)
                if changes:
                    return {'action': 'update', 'changes': changes}
                else:
                    return {'action': 'skip'}
            else:
                if self._create_record(session, row, row_idx, dry_run):
                    return {'action': 'add'}
                else:
                    return {'action': 'skip'}

        except Exception as e:
            logger.error(f"Row {row_idx} processing error: {e}")
            return {'action': 'error', 'error': str(e)[:200]}

    def _update_record(self, session: Session, record: Any, row: Dict, row_idx: int, dry_run: bool) -> List[Dict]:
        """Update existing record."""
        changes = []

        # Check readonly fields
        for field_name in self.config['readonly_fields']:
            if field_name not in row:
                continue

            if self.table_name == 'Users':
                if field_name == 'userID':
                    sheet_user_id = row.get('userID')
                    db_user_id = getattr(record, 'userID')
                    if sheet_user_id and sheet_user_id != db_user_id:
                        raise ValueError(
                            f"Attempting to change readonly userID: "
                            f"DB={db_user_id}, sheet={sheet_user_id}"
                        )
                elif field_name == 'telegramID':
                    sheet_tid = row.get('telegramID')
                    db_tid = getattr(record, 'telegramID')
                    if sheet_tid != db_tid:
                        raise ValueError(f"Attempting to change telegramID: DB={db_tid}, sheet={sheet_tid}")
                elif field_name in ['balanceActive', 'balancePassive']:
                    sheet_value = self._parse_decimal(row.get(field_name))
                    db_value = getattr(record, field_name, Decimal("0"))
                    if sheet_value is not None:
                        if abs(sheet_value - db_value) > Decimal("0.01"):
                            logger.warning(
                                f"Row {row_idx}: Balance mismatch in {field_name}: "
                                f"DB={db_value}, sheet={sheet_value}. Skipping."
                            )

        # Update only editable_fields
        for field_name in self.config['editable_fields']:
            if field_name not in row:
                continue

            try:
                new_value = self._convert_value(field_name, row[field_name])
            except Exception as e:
                logger.warning(f"Row {row_idx}: Failed to convert {field_name}={row[field_name]}: {e}")
                continue

            old_value = getattr(record, field_name)

            # Special handling for upline
            if field_name == 'upline' and self.table_name == 'Users':
                new_value = validate_upliner(new_value, getattr(record, 'telegramID'), session)

            if self._values_differ(old_value, new_value):
                if field_name in self.config.get('foreign_keys', {}):
                    if not validate_foreign_key(self.table_name, field_name, new_value, session):
                        logger.warning(f"Row {row_idx}: Invalid foreign key {field_name}={new_value}")
                        continue

                changes.append({
                    'field': field_name,
                    'old': self._format_for_display(old_value),
                    'new': self._format_for_display(new_value)
                })

                if not dry_run:
                    setattr(record, field_name, new_value)

        return changes

    def _create_record(self, session: Session, row: Dict, row_idx: int, dry_run: bool) -> bool:
        """Create new record."""
        # Check required fields
        for field in self.config['required_fields']:
            if field not in row or not row[field]:
                logger.warning(f"Row {row_idx}: Missing required field: {field}")
                return False

        # For Users check duplicate telegramID
        if self.table_name == 'Users':
            telegram_id = row.get('telegramID')
            existing = session.query(User).filter_by(telegramID=telegram_id).first()
            if existing:
                logger.error(f"Row {row_idx}: telegramID {telegram_id} already exists")
                return False

        if dry_run:
            return True

        record = self.model()

        # Fill fields
        for field_name, value in row.items():
            if not hasattr(record, field_name):
                continue

            if self.table_name == 'Users' and field_name == 'userID':
                continue
            if field_name in ['createdAt', 'updatedAt']:
                continue

            try:
                converted_value = self._convert_value(field_name, value)
            except Exception as e:
                logger.warning(f"Row {row_idx}: Failed to convert {field_name}={value}: {e}")
                converted_value = None

            # Special handling for upline
            if field_name == 'upline' and self.table_name == 'Users':
                telegram_id = row.get('telegramID')
                default_ref = get_default_referrer_id()
                if converted_value == telegram_id:
                    converted_value = default_ref
                elif not converted_value:
                    converted_value = default_ref

            setattr(record, field_name, converted_value)

        # Add AuditMixin fields if present
        if hasattr(record, 'ownerTelegramID') and self.table_name != 'Users':
            user_id = row.get('userID')
            if user_id:
                owner = session.query(User).filter_by(userID=user_id).first()
                if owner:
                    record.ownerTelegramID = owner.telegramID
                    record.ownerEmail = owner.email

        session.add(record)
        return True

    def _convert_value(self, field_name: str, value: Any) -> Any:
        """Convert value to correct type."""
        if value in [None, '', 'None', 'NULL', 'null', 'Null']:
            if field_name == 'upline' and self.table_name == 'Users':
                raise ValueError(f"Empty upline is not allowed")
            return None

        validators = self.config.get('field_validators', {})
        validator = validators.get(field_name)

        # Special handling for dates
        if field_name in ['lastActive', 'createdAt', 'updatedAt', 'confirmationTime', 'birthday']:
            return self._parse_date(value)

        if not validator:
            if isinstance(value, str):
                value = value.strip()
                return value if value else None
            return value

        # Handle by validator type
        if validator == 'json_string':
            return self._parse_json_field(value)
        elif validator == 'decimal':
            return self._parse_decimal(value)
        elif validator == 'email':
            if not value:
                return None
            return str(value).lower().strip()
        elif validator == 'phone':
            if not value:
                return None
            return str(value).strip()
        elif validator == 'boolean':
            if isinstance(value, bool):
                return 1 if value else 0
            if isinstance(value, (int, float)):
                return 1 if value else 0
            if isinstance(value, str):
                val = value.lower().strip()
                return 1 if val in ('true', '1', 'yes') else 0
            return 0
        elif validator == 'int':
            try:
                if isinstance(value, str):
                    value = value.strip().replace(',', '.').replace(' ', '')
                return int(float(value))
            except:
                raise ValueError(f"Cannot convert {field_name}={value} to int")
        elif validator == 'float':
            try:
                if isinstance(value, str):
                    value = value.strip().replace(',', '.').replace(' ', '')
                return float(value)
            except:
                raise ValueError(f"Cannot convert {field_name}={value} to float")
        elif validator == 'date' or validator == 'datetime':
            result = self._parse_date(value)
            if result is None and value:
                raise ValueError(f"Invalid date format for {field_name}={value}")
            return result
        elif validator == 'special_upliner':
            try:
                return int(float(str(value).strip()))
            except:
                raise ValueError(f"Invalid upline format: {value}")
        elif isinstance(validator, list):
            if value not in validator:
                raise ValueError(f"Value '{value}' not allowed for {field_name}. Must be one of: {validator}")
            return value
        else:
            if isinstance(value, str):
                value = value.strip()
                return value if value else None
            return value

    def _parse_json_field(self, value: Any) -> Optional[Dict]:
        """Parse JSON field."""
        if not value:
            return {}
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON value: {value[:100]}...")
                return {}
        return {}

    def _parse_decimal(self, value: Any) -> Optional[Decimal]:
        """Parse Decimal value."""
        if value in [None, '', 'None']:
            return Decimal("0")
        try:
            if isinstance(value, Decimal):
                return value
            if isinstance(value, str):
                value = value.strip().replace(',', '.').replace(' ', '')
            return Decimal(str(value))
        except:
            raise ValueError(f"Cannot convert {value} to Decimal")

    def _parse_date(self, value: Any) -> Optional[datetime]:
        """Parse date value."""
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None

            formats = [
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            ]

            for fmt in formats:
                try:
                    dt = datetime.strptime(value, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt
                except ValueError:
                    continue

            return None
        return None

    def _values_differ(self, old_value: Any, new_value: Any) -> bool:
        """Check if values differ."""
        if old_value is None and new_value in ['', None]:
            return False
        if new_value is None and old_value in ['', None]:
            return False

        if isinstance(old_value, dict) and isinstance(new_value, dict):
            return old_value != new_value

        if isinstance(old_value, Decimal) or isinstance(new_value, Decimal):
            try:
                old_dec = Decimal(str(old_value)) if old_value is not None else Decimal("0")
                new_dec = Decimal(str(new_value)) if new_value is not None else Decimal("0")
                return abs(old_dec - new_dec) > Decimal("0.01")
            except:
                return True

        if isinstance(old_value, bool):
            return bool(old_value) != bool(new_value)

        if isinstance(old_value, (int, float)) and new_value is not None:
            try:
                return abs(float(old_value) - float(new_value)) > 0.001
            except:
                return True

        if isinstance(old_value, datetime) and isinstance(new_value, datetime):
            return old_value != new_value

        old_str = str(old_value).strip() if old_value not in [None, ''] else ''
        new_str = str(new_value).strip() if new_value not in [None, ''] else ''

        return old_str != new_str

    def _format_for_display(self, value: Any) -> Any:
        """Format value for report display."""
        if isinstance(value, Decimal):
            return float(value)
        elif isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        elif isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        return value