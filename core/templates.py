# jetup/core/templates.py
"""
Message templates manager for Jetup bot.
Hybrid version: helpbot's clean architecture + talentir's advanced features.

Features:
- Load templates from Google Sheets
- Advanced SafeDict with Decimal support
- Repeating groups (rgroup) for dynamic lists
- Sequence formatting for carousel/lists
- preAction/postAction support (via stubs)
"""
import logging
import re
from typing import Optional, Dict, Tuple, List, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from core.google_services import get_google_services
from core.utils import SafeDict
from config import Config
from actions.loader import execute_preaction, execute_postaction

logger = logging.getLogger(__name__)


class MessageTemplates:
    """
    Manager for message templates stored in Google Sheets.

    Templates are loaded from Google Sheets and cached in memory.
    Each template has: text, buttons, preAction, postAction, media, etc.
    """

    # Cache: (stateKey, lang) -> template_dict
    _cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
    _sheet_client = None

    # ═══════════════════════════════════════════════════════════════════════
    # TEMPLATE LOADING
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def _get_sheet_client(cls):
        """Get and cache Google Sheets client."""
        if cls._sheet_client is None:
            sheets_client, _ = await get_google_services()
            cls._sheet_client = sheets_client
        return cls._sheet_client

    @staticmethod
    async def load_templates() -> None:
        """
        Load all templates from Google Sheets to memory cache.

        Expected sheet format:
        | stateKey | lang | preAction | text | buttons | postAction | parseMode | disablePreview | mediaType | mediaID |

        Raises:
            Exception: If loading fails
        """
        try:
            sheets_client, _ = await get_google_services()
            sheet_id = Config.get(Config.GOOGLE_SHEET_ID)
            spreadsheet = await sheets_client.open_by_key(sheet_id)
            sheet = await spreadsheet.worksheet("Templates")
            rows = await sheet.get_all_records()

            # Build cache
            new_cache = {}
            for row in rows:
                key = (row['stateKey'], row['lang'])
                new_cache[key] = {
                    'preAction': row.get('preAction', ''),
                    'text': row['text'],
                    'buttons': row.get('buttons', ''),
                    'postAction': row.get('postAction', ''),
                    'parseMode': row.get('parseMode', 'HTML'),
                    'disablePreview': MessageTemplates._parse_boolean(row.get('disablePreview', False)),
                    'mediaType': row.get('mediaType', ''),
                    'mediaID': row.get('mediaID', '')
                }

            MessageTemplates._cache = new_cache
            logger.info(f"✓ Loaded {len(rows)} templates from Google Sheets")

        except Exception as e:
            logger.error(f"Failed to load templates: {e}")
            raise

    @staticmethod
    def _parse_boolean(value: Any) -> bool:
        """
        Parse boolean from various formats.

        Args:
            value: Value to parse (bool, int, str)

        Returns:
            bool: Parsed boolean
        """
        if isinstance(value, bool):
            return value
        elif isinstance(value, int):
            return value == 1
        elif isinstance(value, str):
            return value.upper() in ("TRUE", "1", "YES")
        return False

    @staticmethod
    async def get_template(state_key: str, lang: str = 'en') -> Optional[Dict[str, Any]]:
        """
        Get template by state key and language.
        Falls back to English if requested language not available.

        Args:
            state_key: Template state key
            lang: Language code (default: 'en')

        Returns:
            Template dict or None if not found
        """
        # Try requested language
        template = MessageTemplates._cache.get((state_key, lang))

        # Fallback to English
        if not template and lang != 'en':
            template = MessageTemplates._cache.get((state_key, 'en'))
            if template:
                logger.debug(f"Template '{state_key}' not found in '{lang}', using 'en'")

        if not template:
            logger.warning(f"Template '{state_key}' not found (lang: {lang})")

        return template

    # ═══════════════════════════════════════════════════════════════════════
    # TEXT FORMATTING
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def format_text(template: str, variables: Dict[str, Any]) -> str:
        """
        Format template text with variables using SafeDict.

        Args:
            template: Text template with {placeholders}
            variables: Dictionary with variable values

        Returns:
            Formatted text

        Example:
            >>> format_text("Price: {price:.2f}", {"price": Decimal("123.456")})
            "Price: 123.46"
        """
        try:
            return template.format_map(SafeDict(variables))
        except Exception as e:
            logger.error(f"Error formatting template: {e}")
            return template

    @staticmethod
    def sequence_format(
            template: str,
            variables: Dict[str, Any],
            sequence_index: int = 0
    ) -> str:
        """
        Format template with sequence support.

        For list/tuple values, uses value at sequence_index (or last if out of range).
        Useful for carousels, paginated lists, etc.

        Args:
            template: Text template
            variables: Dictionary with variables (some can be lists)
            sequence_index: Index for sequence variables

        Returns:
            Formatted string

        Example:
            >>> variables = {
            ...     "title": ["Project 1", "Project 2", "Project 3"],
            ...     "price": [100, 200, 300]
            ... }
            >>> sequence_format("{title}: ${price}", variables, sequence_index=1)
            "Project 2: $200"
        """
        formatted_vars = {}

        for key, value in variables.items():
            if isinstance(value, (list, tuple)) and value:
                # Use value at index, or last value if out of range
                try:
                    formatted_vars[key] = value[min(sequence_index, len(value) - 1)]
                except (IndexError, ValueError):
                    formatted_vars[key] = value[-1] if value else None
            else:
                formatted_vars[key] = value

        return MessageTemplates.format_text(template, formatted_vars)

    # ═══════════════════════════════════════════════════════════════════════
    # REPEATING GROUPS (rgroup) - from Talentir
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def process_repeating_group(template_text: str, rgroup_data: Dict[str, List[Any]]) -> str:
        """
        Process repeating groups in template text.

        Syntax in template:
            {{rgroup}}
            Name: {name}
            Value: {value}
            {{/rgroup}}

        Args:
            template_text: Template with {{rgroup}}...{{/rgroup}} blocks
            rgroup_data: Dictionary with list values for each key

        Returns:
            Text with repeated sections

        Example:
            >>> template = "Team:\\n{{rgroup}}\\n- {name}: {volume}\\n{{/rgroup}}"
            >>> data = {
            ...     "name": ["Alice", "Bob", "Charlie"],
            ...     "volume": [1000, 2000, 1500]
            ... }
            >>> process_repeating_group(template, data)
            "Team:\\n- Alice: 1000\\n- Bob: 2000\\n- Charlie: 1500\\n"
        """
        # Find rgroup blocks
        rgroup_pattern = r'\{\{rgroup\}\}(.*?)\{\{/rgroup\}\}'
        matches = re.finditer(rgroup_pattern, template_text, re.DOTALL)

        result = template_text

        for match in matches:
            block_template = match.group(1)

            # Get length of lists (all should be same length)
            list_length = 0
            if rgroup_data:
                first_list = next(iter(rgroup_data.values()))
                if isinstance(first_list, list):
                    list_length = len(first_list)

            # Repeat block for each item
            repeated_blocks = []
            for i in range(list_length):
                item_vars = {}
                for key, values in rgroup_data.items():
                    if isinstance(values, list) and i < len(values):
                        item_vars[key] = values[i]
                    else:
                        item_vars[key] = values

                # Format this block
                formatted_block = MessageTemplates.format_text(block_template, item_vars)
                repeated_blocks.append(formatted_block)

            # Replace {{rgroup}}...{{/rgroup}} with repeated content
            result = result.replace(match.group(0), ''.join(repeated_blocks))

        return result

    # ═══════════════════════════════════════════════════════════════════════
    # KEYBOARD CREATION
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def create_keyboard(
            buttons_str: str,
            variables: Dict[str, Any] = None
    ) -> Optional[InlineKeyboardMarkup]:
        """
        Create inline keyboard from configuration string.

        ORIGINAL TALENTIR FORMAT (500+ templates use this - DO NOT CHANGE!):
        Format: callback_data:Button Text

        Examples:
            /buy:Buy Now ✅
            /cancel:Cancel ❌

            Multiple buttons in row (separated by ;):
            lang_en:🇬🇧; lang_de:🇩🇪; lang_ru:🇷🇺

            Multiple rows (separated by newline):
            /project_1:Project 1; /project_2:Project 2
            /back:Back

            Special buttons:
            |webapp|library.jetup.info/books:Open Library 📚
            |url|https://talentir.info:Website 🌐

        Args:
            buttons_str: Button configuration string
            variables: Variables for substitution

        Returns:
            InlineKeyboardMarkup or None
        """
        if not buttons_str or not buttons_str.strip():
            return None

        variables = variables or {}
        keyboard_buttons = []
        sequence_index = 0

        try:
            rows = buttons_str.split('\n')

            for row in rows:
                if not row.strip():
                    continue

                button_row = []
                buttons = row.split(';')  # Split by semicolon

                for button in buttons:
                    button = button.strip()
                    if not button or ':' not in button:
                        continue

                    # ═══════════════════════════════════════════════════════
                    # WEBAPP BUTTON: |webapp|url:Text
                    # ═══════════════════════════════════════════════════════
                    if '|webapp|' in button:
                        webapp_parts = button.split(':', 1)
                        webapp_url_part = webapp_parts[0].strip()
                        button_text = webapp_parts[1].strip() if len(webapp_parts) > 1 else "Open WebApp"

                        if webapp_url_part.startswith('|webapp|'):
                            url = webapp_url_part[8:]  # Remove |webapp| prefix

                            # Add https:// if not present
                            if not url.startswith(('http://', 'https://')):
                                url = 'https://' + url

                            # Apply variables
                            if variables:
                                try:
                                    button_text = MessageTemplates.sequence_format(
                                        button_text, variables, sequence_index
                                    )
                                    if '{}' in url or '{' in url:
                                        url = MessageTemplates.sequence_format(
                                            url, variables, sequence_index
                                        )
                                    sequence_index += 1
                                except Exception as e:
                                    logger.error(f"Error formatting webapp button: {e}")
                                    continue

                            try:
                                from aiogram.types import WebAppInfo
                                button_row.append(
                                    InlineKeyboardButton(
                                        text=button_text,
                                        web_app=WebAppInfo(url=url)
                                    )
                                )
                                continue  # Next button
                            except Exception as e:
                                logger.error(f"Error creating webapp button: {e}")

                    # ═══════════════════════════════════════════════════════
                    # URL BUTTON: |url|url:Text
                    # ═══════════════════════════════════════════════════════
                    elif '|url|' in button:
                        url_parts = button.split(':', 1)
                        url_part = url_parts[0].strip()
                        button_text = url_parts[1].strip() if len(url_parts) > 1 else "Open URL"

                        if url_part.startswith('|url|'):
                            url = url_part[5:]  # Remove |url| prefix

                            # Add http:// if not present
                            if not url.startswith(('http://', 'https://')):
                                url = 'http://' + url

                            # Apply variables
                            if variables:
                                try:
                                    button_text = MessageTemplates.sequence_format(
                                        button_text, variables, sequence_index
                                    )
                                    if '{}' in url or '{' in url:
                                        url = MessageTemplates.sequence_format(
                                            url, variables, sequence_index
                                        )
                                    sequence_index += 1
                                except Exception as e:
                                    logger.error(f"Error formatting url button: {e}")
                                    continue

                            try:
                                button_row.append(
                                    InlineKeyboardButton(
                                        text=button_text,
                                        url=url
                                    )
                                )
                                continue  # Next button
                            except Exception as e:
                                logger.error(f"Error creating url button: {e}")

                    # ═══════════════════════════════════════════════════════
                    # STANDARD CALLBACK BUTTON: callback_data:Text
                    # ═══════════════════════════════════════════════════════
                    callback, text = button.split(':', 1)
                    callback = callback.strip()
                    text = text.strip()

                    # Apply variables
                    if variables:
                        try:
                            text = MessageTemplates.sequence_format(
                                text, variables, sequence_index
                            )
                            callback = MessageTemplates.sequence_format(
                                callback, variables, sequence_index
                            )
                            sequence_index += 1
                        except Exception as e:
                            logger.error(f"Error formatting callback button: {e}")
                            continue

                    try:
                        button_row.append(
                            InlineKeyboardButton(
                                text=text,
                                callback_data=callback
                            )
                        )
                    except Exception as e:
                        logger.error(f"Error creating callback button: {e}")

                if button_row:
                    keyboard_buttons.append(button_row)

            return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons) if keyboard_buttons else None

        except Exception as e:
            logger.error(f"Error creating keyboard: {e}")
            return None

    @staticmethod
    def merge_buttons(buttons_list: List[str]) -> str:
        """
        Merge multiple button configurations into one.

        Args:
            buttons_list: List of button configuration strings

        Returns:
            Merged button configuration
        """
        valid_configs = [b.strip() for b in buttons_list if b and b.strip()]
        if not valid_configs:
            return ''

        # Join all rows with newlines
        all_rows = []
        for config in valid_configs:
            rows = config.split('\n')
            for row in rows:
                if row.strip():
                    all_rows.append(row.strip())

        return '\n'.join(all_rows)

    # ═══════════════════════════════════════════════════════════════════════
    # ACTIONS (via stubs)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    async def execute_preaction(preaction_name: str, user, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute preAction before sending message.

        Args:
            preaction_name: Name of preAction
            user: User object
            context: Variables context

        Returns:
            Updated context (or original if preAction not found/failed)
        """
        if not preaction_name:
            return context

        try:
            result = await execute_preaction(preaction_name, user, context)
            return result
        except Exception as e:
            logger.error(f"Error executing preAction '{preaction_name}': {e}")
            return context

    @staticmethod
    async def execute_postaction(
            postaction_name: str,
            user,
            context: Dict[str, Any],
            callback_data: Optional[str] = None
    ) -> Optional[str]:
        """
        Execute postAction after user interaction.

        Args:
            postaction_name: Name of postAction
            user: User object
            context: Variables context
            callback_data: Callback data from button

        Returns:
            Next state key or None
        """
        if not postaction_name:
            return None

        try:
            result = await execute_postaction(postaction_name, user, context, callback_data)
            return result
        except Exception as e:
            logger.error(f"Error executing postAction '{postaction_name}': {e}", exc_info=True)
            return None


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    'MessageTemplates',
]