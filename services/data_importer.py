# jetup/services/data_importer.py
"""
Configuration importer for Jetup bot.
Loads configuration from Google Sheets Config tab.
"""
import json
import logging
from typing import Dict, Any, Optional

from config import Config
from core.google_services import get_google_services

logger = logging.getLogger(__name__)


class ConfigImporter:
    """
    Import configuration from Google Sheets.

    Expected sheet format (Config tab):
    | key | value | description |
    |-----|-------|-------------|
    | REQUIRED_CHANNELS | [{"chat_id": "-100...", "title": "Channel", "url": "https://...", "lang": "en"}] | Channels for subscription check |
    | DEFAULT_REFERRER_ID | 123456789 | Default referrer if none provided |
    | ... | ... | ... |
    """

    @staticmethod
    async def import_config(sheet_id: Optional[str] = None, sheet_name: str = "Config") -> Dict[str, Any]:
        """
        Import configuration from Google Sheets.

        Args:
            sheet_id: Google Sheet ID (defaults to Config.GOOGLE_SHEET_ID)
            sheet_name: Sheet name containing config (default: "Config")

        Returns:
            Dictionary with configuration values

        Raises:
            Exception: If unable to load configuration
        """
        import asyncio

        try:
            sheet_id = sheet_id or Config.get(Config.GOOGLE_SHEET_ID)
            if not sheet_id:
                raise ValueError("GOOGLE_SHEET_ID not configured")

            logger.info(f"Loading configuration from Google Sheets: {sheet_id}/{sheet_name}")

            # Get Google Sheets client (async call, returns SYNC client)
            sheets_client, _ = await get_google_services()

            # Wrap synchronous gspread calls in thread
            def _load_from_sheets():
                spreadsheet = sheets_client.open_by_key(sheet_id)
                sheet = spreadsheet.worksheet(sheet_name)
                return sheet.get_all_records()

            # Execute in thread to avoid blocking
            records = await asyncio.to_thread(_load_from_sheets)

            if not records:
                logger.warning(f"{sheet_name} sheet is empty or has no valid records")
                return {}

            config_dict = {}

            for record in records:
                # Validate record structure
                if 'key' not in record or 'value' not in record:
                    logger.warning(f"Invalid config record (missing 'key' or 'value'): {record}")
                    continue

                key = str(record['key']).strip()
                value = record['value']

                # Skip empty keys
                if not key:
                    continue

                try:
                    # Parse value based on type
                    parsed_value = ConfigImporter.parse_config_value(key, value)
                    config_dict[key] = parsed_value
                    logger.debug(f"Loaded config: {key} = {parsed_value}")

                except Exception as e:
                    logger.warning(f"Error parsing value for key '{key}': {e}")
                    # Store as-is if parsing fails
                    config_dict[key] = value

            logger.info(f"Successfully imported {len(config_dict)} configuration variables")
            return config_dict

        except Exception as e:
            logger.error(f"Error importing configuration from Google Sheets: {e}", exc_info=True)
            raise

    @staticmethod
    def parse_config_value(key: str, value: Any) -> Any:
        """
        Parse configuration value based on key and value type.

        Args:
            key: Configuration key name
            value: Raw value from Google Sheets

        Returns:
            Parsed value with correct type

        Examples:
            >>> ConfigImporter.parse_config_value("CHANNELS", '[{"id": 1}]')
            [{"id": 1}]

            >>> ConfigImporter.parse_config_value("ENABLED", "true")
            True

            >>> ConfigImporter.parse_config_value("COUNT", "42")
            42
        """
        # Handle empty or None values
        if value is None or value == '':
            return None

        # If already correct type (from Sheets API), return as-is
        if isinstance(value, (bool, int, float, list, dict)):
            return value

        # Parse string values
        if isinstance(value, str):
            value_lower = value.lower().strip()

            # Try to parse as JSON (for arrays and objects)
            if value.startswith('{') or value.startswith('['):
                try:
                    return json.loads(value)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse JSON for key '{key}': {e}")
                    return value

            # Parse boolean
            if value_lower in ('true', 'yes', '1'):
                return True
            if value_lower in ('false', 'no', '0'):
                return False

            # Try to parse as number
            try:
                # Check for float
                if '.' in value:
                    return float(value)
                # Otherwise int
                return int(value)
            except ValueError:
                # Keep as string if not a number
                pass

        # Return as-is if no parsing rules matched
        return value