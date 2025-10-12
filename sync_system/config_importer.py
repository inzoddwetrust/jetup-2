"""
Импортер для конфигурации и Projects/Options
Используется командами &upconfig и &upro
"""

import json
import logging
from typing import Dict, Any
from decimal import Decimal

from google_services import get_google_services
from models import Project, Option
from init import Session
import config

logger = logging.getLogger(__name__)


class ConfigImporter:
    """Импорт конфигурации из Google Sheets"""

    @staticmethod
    async def import_config() -> Dict[str, Any]:
        """Импортирует конфигурацию из листа Config"""
        try:
            sheets_client, _ = get_google_services()
            sheet = sheets_client.open_by_key(config.GOOGLE_SHEET_ID).worksheet("Config")

            records = sheet.get_all_records()
            if not records:
                logger.warning("Config sheet is empty")
                return {}

            config_dict = {}
            for record in records:
                if 'key' not in record or 'value' not in record:
                    continue

                key = record['key'].strip()
                value = record['value']

                if not key:
                    continue

                # Парсим JSON если нужно
                try:
                    if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                        value = json.loads(value)
                    elif isinstance(value, str):
                        if value.lower() == 'true':
                            value = True
                        elif value.lower() == 'false':
                            value = False
                        else:
                            try:
                                if '.' in value:
                                    value = float(value)
                                else:
                                    value = int(value)
                            except ValueError:
                                pass  # Оставляем как строку
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON for key {key}")

                config_dict[key] = value

            logger.info(f"Imported {len(config_dict)} config variables")
            return config_dict

        except Exception as e:
            logger.error(f"Error importing config: {e}")
            return {}

    @staticmethod
    def update_config_module(config_dict: Dict[str, Any]) -> None:
        """Обновляет переменные в модуле config"""
        updateable_vars = [
            'PURCHASE_BONUSES', 'STRATEGY_COEFFICIENTS', 'TRANSFER_BONUS',
            'SOCIAL_LINKS', 'FAQ_URL', 'REQUIRED_CHANNELS', 'PROJECT_DOCUMENTS',
            'SECURE_EMAIL_DOMAINS'
        ]

        for var_name in updateable_vars:
            if var_name in config_dict:
                setattr(config, var_name, config_dict[var_name])
                logger.info(f"Updated config.{var_name}")


class ProjectImporter:
    """Импортер для Projects (используется в &upro)"""

    async def import_sheet(self, sheet) -> dict:
        """Импортирует проекты из Google Sheets"""
        rows = sheet.get_all_records()
        stats = {
            'total': len(rows),
            'updated': 0,
            'added': 0,
            'errors': 0,
            'error_rows': []
        }

        with Session() as session:
            for idx, row in enumerate(rows, start=2):
                try:
                    if not all(row.get(f) for f in ['projectID', 'projectName', 'lang', 'status']):
                        stats['error_rows'].append((idx, "Missing required fields"))
                        stats['errors'] += 1
                        continue

                    project = session.query(Project).filter_by(
                        projectID=row['projectID'],
                        lang=row['lang']
                    ).first()

                    is_update = bool(project)
                    if not project:
                        project = Project()

                    # Заполняем поля
                    project.projectID = row['projectID']
                    project.lang = row['lang']
                    project.projectName = row['projectName']
                    project.projectTitle = row.get('projectTitle')
                    project.fullText = row.get('fullText')
                    project.status = row['status']
                    project.rate = Decimal(str(row.get('rate', 0))) if row.get('rate') else None
                    project.linkImage = row.get('linkImage')
                    project.linkPres = row.get('linkPres')
                    project.linkVideo = row.get('linkVideo')
                    project.docsFolder = row.get('docsFolder')

                    if not is_update:
                        session.add(project)
                        stats['added'] += 1
                    else:
                        stats['updated'] += 1

                except Exception as e:
                    logger.error(f"Row {idx} error: {e}")
                    stats['error_rows'].append((idx, str(e)))
                    stats['errors'] += 1

            session.commit()

        return stats


class OptionImporter:
    """Импортер для Options (используется в &upro)"""

    async def import_sheet(self, sheet) -> dict:
        """Импортирует опции из Google Sheets"""
        rows = sheet.get_all_records()
        stats = {
            'total': len(rows),
            'updated': 0,
            'added': 0,
            'errors': 0,
            'error_rows': []
        }

        with Session() as session:
            for idx, row in enumerate(rows, start=2):
                try:
                    if not all(row.get(f) for f in ['optionID', 'projectID', 'projectName']):
                        stats['error_rows'].append((idx, "Missing required fields"))
                        stats['errors'] += 1
                        continue

                    option = session.query(Option).filter_by(optionID=row['optionID']).first()

                    is_update = bool(option)
                    if not option:
                        option = Option()

                    # Заполняем поля с Decimal
                    option.optionID = row['optionID']
                    option.projectID = row['projectID']
                    option.projectName = row['projectName']
                    option.costPerShare = Decimal(str(row.get('costPerShare', 0)))
                    option.packQty = int(row.get('packQty', 0))
                    option.packPrice = Decimal(str(row.get('packPrice', 0)))
                    option.isActive = row.get('isActive?', True) in [True, 1, '1', 'true', 'True']

                    if not is_update:
                        session.add(option)
                        stats['added'] += 1
                    else:
                        stats['updated'] += 1

                except Exception as e:
                    logger.error(f"Row {idx} error: {e}")
                    stats['error_rows'].append((idx, str(e)))
                    stats['errors'] += 1

            session.commit()

        return stats