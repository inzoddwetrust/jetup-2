# sync_system/config_importer.py
"""
Importer for configuration and Projects/Options.
Used by &upconfig and &upro commands.
"""
import json
import logging
from typing import Dict, Any
from decimal import Decimal

from config import Config
from core.db import get_session
from core.google_services import get_google_services
from models import Project, Option

logger = logging.getLogger(__name__)


class ConfigImporter:
    """Import configuration from Google Sheets."""

    @staticmethod
    async def import_config() -> Dict[str, Any]:
        """
        Import configuration from Config sheet.

        Returns:
            Dict with key-value pairs from Config sheet.
        """
        try:
            sheets_client, _ = await get_google_services()
            sheet_id = Config.get(Config.GOOGLE_SHEET_ID)
            sheet = sheets_client.open_by_key(sheet_id).worksheet("Config")

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

                # Parse JSON if needed
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
                                pass  # Keep as string
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse JSON for key {key}")

                config_dict[key] = value

            logger.info(f"Imported {len(config_dict)} config variables")
            return config_dict

        except Exception as e:
            logger.error(f"Error importing config: {e}")
            return {}

    @staticmethod
    def update_config_class(config_dict: Dict[str, Any]) -> int:
        """
        Update Config class with imported values.

        Args:
            config_dict: Dict with key-value pairs.

        Returns:
            Number of updated keys.
        """
        updated = 0
        for key, value in config_dict.items():
            Config.set(key, value)
            updated += 1
            logger.debug(f"Set Config.{key}")

        return updated


class ProjectImporter:
    """Import Projects from Google Sheets."""

    @staticmethod
    async def import_projects() -> Dict[str, Any]:
        """
        Import projects from Projects sheet.

        Returns:
            Dict with import statistics.
        """
        stats = {
            'total': 0,
            'added': 0,
            'updated': 0,
            'errors': 0,
            'error_rows': []
        }

        try:
            sheets_client, _ = await get_google_services()
            sheet_id = Config.get(Config.GOOGLE_SHEET_ID)
            sheet = sheets_client.open_by_key(sheet_id).worksheet("Projects")

            rows = sheet.get_all_records()
            stats['total'] = len(rows)

            session = get_session()
            try:
                for idx, row in enumerate(rows, start=2):
                    try:
                        required = ['projectID', 'projectName', 'lang', 'status']
                        if not all(row.get(f) for f in required):
                            stats['error_rows'].append((idx, "Missing required fields"))
                            stats['errors'] += 1
                            continue

                        # Composite key: projectID + lang
                        project = session.query(Project).filter_by(
                            projectID=row['projectID'],
                            lang=row['lang']
                        ).first()

                        is_update = bool(project)
                        if not project:
                            project = Project()

                        # Fill fields
                        project.projectID = row['projectID']
                        project.lang = row['lang']
                        project.projectName = row['projectName']
                        project.projectTitle = row.get('projectTitle', '')
                        project.projectDescription = row.get('projectDescription', '')
                        project.status = row.get('status', 'active')
                        project.bookstackPageId = row.get('bookstackPageId') or None

                        if not is_update:
                            session.add(project)
                            stats['added'] += 1
                        else:
                            stats['updated'] += 1

                    except Exception as e:
                        logger.error(f"Projects row {idx} error: {e}")
                        stats['error_rows'].append((idx, str(e)))
                        stats['errors'] += 1

                session.commit()

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Error importing projects: {e}", exc_info=True)
            stats['errors'] += 1

        return stats


class OptionImporter:
    """Import Options from Google Sheets."""

    @staticmethod
    async def import_options() -> Dict[str, Any]:
        """
        Import options from Options sheet.

        Returns:
            Dict with import statistics.
        """
        stats = {
            'total': 0,
            'added': 0,
            'updated': 0,
            'errors': 0,
            'error_rows': []
        }

        try:
            sheets_client, _ = await get_google_services()
            sheet_id = Config.get(Config.GOOGLE_SHEET_ID)
            sheet = sheets_client.open_by_key(sheet_id).worksheet("Options")

            rows = sheet.get_all_records()
            stats['total'] = len(rows)

            session = get_session()
            try:
                for idx, row in enumerate(rows, start=2):
                    try:
                        required = ['optionID', 'projectID', 'projectName']
                        if not all(row.get(f) for f in required):
                            stats['error_rows'].append((idx, "Missing required fields"))
                            stats['errors'] += 1
                            continue

                        option = session.query(Option).filter_by(
                            optionID=row['optionID']
                        ).first()

                        is_update = bool(option)
                        if not option:
                            option = Option()

                        # Fill fields with Decimal
                        option.optionID = row['optionID']
                        option.projectID = row['projectID']
                        option.projectName = row['projectName']
                        option.costPerShare = Decimal(str(row.get('costPerShare', 0)))
                        option.packQty = int(row.get('packQty', 0))
                        option.packPrice = Decimal(str(row.get('packPrice', 0)))

                        # isActive = True ONLY if value is "1"
                        # Column name in Google Sheets: "isActive?"
                        option.isActive = str(row.get('isActive?', '')).strip() == '1'

                        if not is_update:
                            session.add(option)
                            stats['added'] += 1
                        else:
                            stats['updated'] += 1

                    except Exception as e:
                        logger.error(f"Options row {idx} error: {e}")
                        stats['error_rows'].append((idx, str(e)))
                        stats['errors'] += 1

                session.commit()

            finally:
                session.close()

        except Exception as e:
            logger.error(f"Error importing options: {e}", exc_info=True)
            stats['errors'] += 1

        return stats