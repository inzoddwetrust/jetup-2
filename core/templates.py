# jetup-2/core/templates.py
"""
Message templates manager for Jetup bot.
Clean architecture from helpbot + Talentir advanced features.

Features:
- Load templates from Google Sheets
- Advanced SafeDict with Decimal support
- Repeating groups (rgroup) for dynamic lists
- Sequence formatting for carousel/lists
- preAction/postAction support
"""
import logging
import asyncio
from typing import Optional, Dict, Tuple, List, Any, Union
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

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
    async def load_templates():
        """Load all templates from Google Sheets to memory cache."""
        try:
            # get_google_services() returns SYNC client in jetup-2
            sheets_client, _ = await get_google_services()

            # Wrap synchronous gspread calls in thread
            def _load_from_sheets():
                spreadsheet = sheets_client.open_by_key(Config.get(Config.GOOGLE_SHEET_ID))
                sheet = spreadsheet.worksheet("Templates")
                return sheet.get_all_records()

            # Execute in thread to avoid blocking
            rows = await asyncio.to_thread(_load_from_sheets)

            new_cache = {
                (row['stateKey'], row['lang']): {
                    'preAction': row.get('preAction', ''),
                    'text': row['text'],
                    'buttons': row['buttons'],
                    'postAction': row.get('postAction', ''),
                    'parseMode': row['parseMode'],
                    'disablePreview': MessageTemplates._parse_boolean(row['disablePreview']),
                    'mediaType': row['mediaType'],
                    'mediaID': row['mediaID']
                } for row in rows
            }

            MessageTemplates._cache = new_cache
            logger.info(f"Loaded {len(rows)} templates from Google Sheets")
        except Exception as e:
            logger.error(f"Failed to load templates: {e}", exc_info=True)
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
        # Ensure cache is loaded
        if not MessageTemplates._cache:
            await MessageTemplates.load_templates()

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

    @staticmethod
    async def get_raw_template(
            state_key: str,
            variables: Dict[str, Any],
            lang: str = 'en'
    ) -> Tuple[str, Optional[str]]:
        """
        Get raw template without media formatting.
        Used primarily for notifications.

        Args:
            state_key: Template identifier
            variables: Dictionary with variables for substitution
            lang: Language code (default: 'en')

        Returns:
            Tuple[str, Optional[str]]: (formatted text, formatted buttons)
        """
        # Ensure cache is loaded
        if not MessageTemplates._cache:
            await MessageTemplates.load_templates()

        template = MessageTemplates._cache.get((state_key, lang))
        if not template:
            template = MessageTemplates._cache.get((state_key, 'en'))
            if not template:
                logger.error(
                    f"Template not found: {state_key}. "
                    f"Available keys: {list(MessageTemplates._cache.keys())[:10]}"
                )
                raise ValueError(f"Template not found: {state_key}")

        text = template['text'].replace('\\n', '\n')
        buttons = template['buttons']

        # Process rgroup if present in variables
        if 'rgroup' in variables:
            text = MessageTemplates.process_repeating_group(text, variables['rgroup'])
            if buttons:
                buttons = MessageTemplates.process_repeating_group(buttons, variables['rgroup'])

        # Format with SafeDict
        formatted_text = text.format_map(SafeDict(variables))
        formatted_buttons = buttons.format_map(SafeDict(variables)) if buttons else None

        return formatted_text, formatted_buttons

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
    # REPEATING GROUPS (rgroup)
    # ═══════════════════════════════════════════════════════════════════════

    @staticmethod
    def process_repeating_group(template_text: str, rgroup_data: Dict[str, List[Any]]) -> str:
        """
        Process repeating groups in template text.

        IMPORTANT: Arrays can have DIFFERENT lengths!
        - Iteration by MAXIMUM length
        - Short arrays reuse LAST element for remaining iterations

        Syntax: |rgroup:Item template with {placeholders}|

        Example:
            template_text = "|rgroup:{name} - {price} {emoji}|"
            rgroup_data = {
                'name': ['Apple', 'Banana', 'Orange'],  # 3 items
                'price': ['$1', '$2'],                  # 2 items -> last '$2' reused
                'emoji': ['🍎']                          # 1 item -> '🍎' reused
            }
            Result:
                Apple - $1 🍎
                Banana - $2 🍎
                Orange - $2 🍎

        Args:
            template_text: Text with |rgroup:...|
            rgroup_data: Dict with list values (can be different lengths!)

        Returns:
            Text with repeated sections
        """
        start = template_text.find('|rgroup:')
        if start == -1:
            return template_text

        end = template_text.find('|', start + 8)
        if end == -1:
            return template_text

        item_template = template_text[start + 8:end]
        full_template = template_text[start:end + 1]

        if not rgroup_data or not any(rgroup_data.values()):
            return template_text.replace(full_template, '')

        # Find MAXIMUM length among all arrays
        max_length = 0
        for value in rgroup_data.values():
            if isinstance(value, (list, tuple)) and len(value) > max_length:
                max_length = len(value)

        if max_length == 0:
            return template_text.replace(full_template, '')

        # Iterate by maximum length
        result = []
        for i in range(max_length):
            item_data = {}
            for key, values in rgroup_data.items():
                if isinstance(values, (list, tuple)):
                    # Use value at index i, or LAST value if out of range
                    item_data[key] = values[min(i, len(values) - 1)] if values else ''
                else:
                    # Scalar value - use as is
                    item_data[key] = values

            # Format item with SafeDict
            result.append(item_template.format_map(SafeDict(item_data)))

        return template_text.replace(full_template, '\n'.join(result))

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

                    # ═══════════════════════════════════════════════════════════
                    # WEBAPP BUTTON: |webapp|url:Text
                    # ═══════════════════════════════════════════════════════════
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
                                button_row.append(
                                    InlineKeyboardButton(
                                        text=button_text,
                                        web_app=WebAppInfo(url=url)
                                    )
                                )
                                continue  # Next button
                            except Exception as e:
                                logger.error(f"Error creating webapp button: {e}")

                    # ═══════════════════════════════════════════════════════════
                    # URL BUTTON: |url|url:Text
                    # ═══════════════════════════════════════════════════════════
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

                    # ═══════════════════════════════════════════════════════════
                    # STANDARD CALLBACK BUTTON: callback_data:Text
                    # ═══════════════════════════════════════════════════════════
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
    # SCREEN GENERATION (CRITICAL METHOD FROM HELPBOT!)
    # ═══════════════════════════════════════════════════════════════════════

    @classmethod
    async def generate_screen(
            cls,
            user,
            state_keys: Union[str, List[str]],
            variables: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, Optional[str], Optional[InlineKeyboardMarkup], str, bool, Optional[str], Optional[str]]:
        """
        Generate screen content from templates.

        This is the MAIN method that combines multiple templates,
        processes rgroups, formats text, creates keyboards.

        Args:
            user: User object for localization
            state_keys: Template key or list of keys
            variables: Optional dictionary with template variables

        Returns:
            Tuple[str, Optional[str], Optional[InlineKeyboardMarkup], str, bool, Optional[str], Optional[str]]:
                - Formatted text
                - Media ID (if any)
                - Keyboard (if any)
                - Parse mode
                - Disable preview flag
                - preAction name (if any)
                - postAction name (if any)
        """
        if isinstance(state_keys, str):
            state_keys = [state_keys]

        templates = []

        # Load cache if needed
        if not cls._cache:
            await cls.load_templates()

        # Collect templates
        for key in state_keys:
            template = cls._cache.get((key, user.lang)) or cls._cache.get((key, 'en'))
            if not template:
                logger.warning(f"Template not found for state {key}")
                continue
            templates.append(template)

        if not templates:
            # Try to get fallback template
            fallback = cls._cache.get(('fallback', user.lang)) or cls._cache.get(('fallback', 'en'))
            if fallback:
                templates = [fallback]
            else:
                logger.error("Fallback template not found")
                return "Template not found", None, None, "HTML", True, None, None

        try:
            texts = []
            buttons_list = []
            format_vars = (variables or {}).copy()

            # Add user to context for direct access to attributes
            format_vars['user'] = user

            # Process each template
            for template in templates:
                text = template['text'].replace('\\n', '\n')

                # Process rgroup if present in variables
                if 'rgroup' in format_vars:
                    text = cls.process_repeating_group(text, format_vars['rgroup'])

                # Format with SafeDict
                text = text.format_map(SafeDict(format_vars))
                texts.append(text)

                # Collect buttons
                if template['buttons']:
                    buttons_list.append(template['buttons'])

            # Combine texts
            final_text = '\n\n'.join(text for text in texts if text)

            # Merge and create keyboard
            merged_buttons = cls.merge_buttons(buttons_list)
            keyboard = cls.create_keyboard(merged_buttons, variables=format_vars)

            # Get metadata from first template
            first_template = templates[0]
            media_id = first_template['mediaID'] if first_template.get('mediaType') != 'None' else None
            parse_mode = first_template['parseMode']
            disable_preview = first_template['disablePreview']
            pre_action = first_template.get('preAction', '') if first_template.get('preAction') else None
            post_action = first_template.get('postAction', '') if first_template.get('postAction') else None

            return final_text, media_id, keyboard, parse_mode, disable_preview, pre_action, post_action

        except Exception as e:
            logger.error(f"Error generating screen: {e}", exc_info=True)
            return f"Error generating screen: {str(e)}", None, None, "HTML", True, None, None

    # ═══════════════════════════════════════════════════════════════════════
    # ACTIONS (via loader)
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