# jetup/core/message_manager.py
"""
Message manager for Jetup bot.
Hybrid: helpbot's architecture + talentir's features (PDF, media handling).

Handles:
- Sending messages with templates
- Media messages (photo, video, document)
- Inline keyboards
- Message editing
- Callback query processing
- PDF document generation (via BookStack)
"""
import logging
from typing import Optional, Dict, Any, Union, List

from aiogram import Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InputFile,
    BufferedInputFile,
    FSInputFile
)
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from core.templates import MessageTemplates
from core.utils import safe_delete_message

logger = logging.getLogger(__name__)


class MessageManager:
    """
    Manager for sending and editing messages with template support.

    Features:
    - Template-based messages from Google Sheets
    - Media support (photo, video, document, PDF)
    - Inline keyboards with variable substitution
    - Message editing
    - Callback query processing with postAction
    - PDF generation via BookStack
    """

    def __init__(self, bot: Bot):
        """
        Initialize message manager.

        Args:
            bot: Bot instance
        """
        self.bot = bot

    # ═══════════════════════════════════════════════════════════════════════
    # MAIN SEND METHOD
    # ═══════════════════════════════════════════════════════════════════════

    async def send_template(
            self,
            user,
            template_key: Union[str, List[str]],
            update: Optional[Union[Message, CallbackQuery]] = None,
            variables: Optional[Dict[str, Any]] = None,
            edit: bool = False,
            delete_original: bool = False,
            override_media_id: Optional[str] = None,
            media_type: Optional[str] = None,
            execute_preaction: bool = True
    ) -> Optional[Message]:
        """
        Send message using template from Google Sheets.

        Args:
            user: User object
            template_key: Template state key (or list of keys for sequence)
            update: Message or CallbackQuery to reply to
            variables: Variables for template substitution
            edit: Edit existing message instead of sending new
            delete_original: Delete original message after sending
            override_media_id: Override template's mediaID
            media_type: Override template's mediaType
            execute_preaction: Execute preAction (default: True)

        Returns:
            Sent/edited Message or None if failed

        Example:
            await message_manager.send_template(
                user=user,
                template_key="welcome_screen",
                update=message,
                variables={"name": user.firstname}
            )
        """
        variables = variables or {}

        try:
            # Prepare template data
            template_data = await self._prepare_template(
                user=user,
                template_key=template_key,
                variables=variables,
                override_media_id=override_media_id,
                media_type=media_type,
                execute_preaction=execute_preaction
            )

            if not template_data:
                logger.error(f"Failed to prepare template: {template_key}")
                return None

            text, keyboard, media_id, media_type_final, parse_mode, disable_preview, _ = template_data

            # Determine chat_id
            if isinstance(update, CallbackQuery):
                chat_id = update.message.chat.id
                message_id = update.message.message_id if edit else None
            elif isinstance(update, Message):
                chat_id = update.chat.id
                message_id = update.message_id if edit else None
            else:
                chat_id = user.telegramID
                message_id = None

            # Send or edit message
            sent_message = await self._send_message(
                chat_id=chat_id,
                text=text,
                media_id=media_id,
                media_type=media_type_final,
                keyboard=keyboard,
                parse_mode=parse_mode,
                disable_preview=disable_preview,
                edit=edit,
                message_id=message_id
            )

            # Delete original message if requested
            if delete_original and update:
                await safe_delete_message(update)

            return sent_message

        except Exception as e:
            logger.error(f"Error in send_template: {e}", exc_info=True)
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # TEMPLATE PREPARATION
    # ═══════════════════════════════════════════════════════════════════════

    async def _prepare_template(
            self,
            user,
            template_key: Union[str, List[str]],
            variables: Optional[Dict[str, Any]] = None,
            override_media_id: Optional[str] = None,
            media_type: Optional[str] = None,
            execute_preaction: bool = True
    ) -> Optional[tuple]:
        """
        Prepare template: get from cache, execute preAction, format text.

        Returns:
            Tuple: (text, keyboard, media_id, media_type, parse_mode, disable_preview, postaction)
            or None if failed
        """
        variables = variables or {}

        # Handle list of templates (for sequences)
        if isinstance(template_key, list):
            if not template_key:
                return None
            template_key = template_key[0]  # Use first template

        # Get template from cache
        template = await MessageTemplates.get_template(template_key, user.lang)
        if not template:
            logger.error(f"Template not found: {template_key} (lang: {user.lang})")
            return None

        # Execute preAction if enabled
        preaction = template.get('preAction', '')
        if execute_preaction and preaction:
            try:
                variables = await MessageTemplates.execute_preaction(preaction, user, variables)
            except Exception as e:
                logger.error(f"Error executing preAction '{preaction}': {e}")

        # Format text with variables
        text = template.get('text', '')
        try:
            # Check for rgroup
            if '{{rgroup}}' in text:
                text = MessageTemplates.process_repeating_group(text, variables)
            else:
                text = MessageTemplates.format_text(text, variables)
        except Exception as e:
            logger.error(f"Error formatting text: {e}")

        # Create keyboard
        buttons_str = template.get('buttons', '')
        keyboard = None
        if buttons_str:
            try:
                keyboard = MessageTemplates.create_keyboard(buttons_str, variables)
            except Exception as e:
                logger.error(f"Error creating keyboard: {e}")

        # Media
        final_media_id = override_media_id or template.get('mediaID', '')
        final_media_type = media_type or template.get('mediaType', '')

        # Parse mode
        parse_mode_str = template.get('parseMode', 'HTML')
        parse_mode = ParseMode.HTML if parse_mode_str == 'HTML' else ParseMode.MARKDOWN

        # Disable preview
        disable_preview = template.get('disablePreview', True)

        # PostAction
        postaction = template.get('postAction', '')

        return (text, keyboard, final_media_id, final_media_type, parse_mode, disable_preview, postaction)

    # ═══════════════════════════════════════════════════════════════════════
    # MESSAGE SENDING
    # ═══════════════════════════════════════════════════════════════════════

    async def _send_message(
            self,
            chat_id: int,
            text: str,
            media_id: Optional[str] = None,
            media_type: Optional[str] = None,
            keyboard: Optional[InlineKeyboardMarkup] = None,
            parse_mode: ParseMode = ParseMode.HTML,
            disable_preview: bool = True,
            edit: bool = False,
            message_id: Optional[int] = None
    ) -> Optional[Message]:
        """
        Universal method to send or edit message with optional media.

        Args:
            chat_id: Chat ID
            text: Message text
            media_id: Media file_id or path
            media_type: 'photo', 'video', 'document', etc.
            keyboard: Inline keyboard
            parse_mode: Parse mode (HTML or Markdown)
            disable_preview: Disable link preview
            edit: Edit existing message
            message_id: Message ID to edit

        Returns:
            Sent/edited Message or None
        """
        try:
            # Edit existing message
            if edit and message_id:
                return await self._edit_message(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    keyboard=keyboard,
                    parse_mode=parse_mode,
                    disable_preview=disable_preview
                )

            # Send new message with media
            if media_id and media_type:
                return await self._send_media_message(
                    chat_id=chat_id,
                    text=text,
                    media_id=media_id,
                    media_type=media_type,
                    keyboard=keyboard,
                    parse_mode=parse_mode
                )

            # Send text-only message
            return await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview
            )

        except TelegramAPIError as e:
            logger.error(f"Telegram API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error sending message: {e}", exc_info=True)
            return None

    async def _send_media_message(
            self,
            chat_id: int,
            text: str,
            media_id: str,
            media_type: str,
            keyboard: Optional[InlineKeyboardMarkup] = None,
            parse_mode: ParseMode = ParseMode.HTML
    ) -> Optional[Message]:
        """Send message with media (photo, video, document)."""
        try:
            media_type = media_type.lower()

            if media_type == 'photo':
                return await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=media_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )

            elif media_type == 'video':
                return await self.bot.send_video(
                    chat_id=chat_id,
                    video=media_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )

            elif media_type == 'document':
                return await self.bot.send_document(
                    chat_id=chat_id,
                    document=media_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )

            else:
                logger.warning(f"Unknown media type: {media_type}, sending as text")
                return await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=parse_mode
                )

        except Exception as e:
            logger.error(f"Error sending media message: {e}")
            return None

    async def _edit_message(
            self,
            chat_id: int,
            message_id: int,
            text: str,
            keyboard: Optional[InlineKeyboardMarkup] = None,
            parse_mode: ParseMode = ParseMode.HTML,
            disable_preview: bool = True
    ) -> Optional[Message]:
        """Edit existing message."""
        try:
            return await self.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=text,
                reply_markup=keyboard,
                parse_mode=parse_mode,
                disable_web_page_preview=disable_preview
            )
        except TelegramAPIError as e:
            if "message is not modified" in str(e).lower():
                logger.debug("Message content unchanged, skipping edit")
                return None
            logger.error(f"Error editing message: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # CALLBACK QUERY PROCESSING
    # ═══════════════════════════════════════════════════════════════════════

    async def process_callback(
            self,
            callback_query: CallbackQuery,
            user,
            current_state: str,
            variables: Optional[Dict[str, Any]] = None,
            edit: bool = True,
            delete_original: bool = False,
            override_media_id: Optional[str] = None,
            media_type: Optional[str] = None,
            execute_preaction: bool = True
    ) -> None:
        """
        Process callback query: execute postAction and navigate to next state.

        Args:
            callback_query: Callback query from button press
            user: User object
            current_state: Current template state
            variables: Variables for templates
            edit: Edit message instead of sending new
            delete_original: Delete original message
            override_media_id: Override media
            media_type: Override media type
            execute_preaction: Execute preAction on next state
        """
        try:
            # Answer callback to remove loading state
            await callback_query.answer()

            # Execute postAction
            logger.debug(f"Processing callback: {callback_query.data} for state: {current_state}")

            next_state = await self._execute_postaction(
                callback_query=callback_query,
                user=user,
                template_key=current_state,
                variables=variables
            )

            if next_state:
                logger.debug(f"Navigating to next state: {next_state}")
                await self.send_template(
                    user=user,
                    template_key=next_state,
                    update=callback_query,
                    variables=variables,
                    edit=edit,
                    delete_original=delete_original,
                    override_media_id=override_media_id,
                    media_type=media_type,
                    execute_preaction=execute_preaction
                )
            else:
                logger.debug(f"No state transition from postAction")

        except Exception as e:
            logger.error(f"Error processing callback: {e}", exc_info=True)
            await callback_query.answer("Error processing your request")

    async def _execute_postaction(
            self,
            callback_query: CallbackQuery,
            user,
            template_key: str,
            variables: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """
        Execute postAction for callback query.

        Returns:
            Next state key or None
        """
        try:
            # Get template to find postAction
            template_data = await self._prepare_template(
                user=user,
                template_key=template_key,
                variables=variables,
                execute_preaction=False  # Don't execute preAction again
            )

            if not template_data:
                return None

            _, _, _, _, _, _, postaction = template_data

            if postaction:
                context_vars = variables or {}
                logger.info(f"Executing postAction: {postaction} with callback_data: {callback_query.data}")

                next_state = await MessageTemplates.execute_postaction(
                    postaction, user, context_vars, callback_query.data
                )

                logger.info(f"PostAction result: {next_state or 'None'}")
                return next_state

            return None

        except Exception as e:
            logger.error(f"Error executing postAction: {e}", exc_info=True)
            return None

    # ═══════════════════════════════════════════════════════════════════════
    # PDF GENERATION (from Talentir)
    # ═══════════════════════════════════════════════════════════════════════

    async def send_pdf_document(
            self,
            chat_id: int,
            pdf_bytes: bytes,
            filename: str,
            caption: Optional[str] = None
    ) -> Optional[Message]:
        """
        Send PDF document from bytes.

        Args:
            chat_id: Chat ID
            pdf_bytes: PDF file as bytes
            filename: Filename for document
            caption: Optional caption

        Returns:
            Sent Message or None

        Example:
            # Generate PDF via BookStack
            from integrations.bookstack import generate_pdf
            pdf_bytes = generate_pdf(html_content, context_vars)

            await message_manager.send_pdf_document(
                chat_id=user.telegramID,
                pdf_bytes=pdf_bytes,
                filename="contract_123.pdf",
                caption="Your contract is ready!"
            )
        """
        try:
            # Create InputFile from bytes
            document = BufferedInputFile(
                file=pdf_bytes,
                filename=filename
            )

            return await self.bot.send_document(
                chat_id=chat_id,
                document=document,
                caption=caption
            )

        except Exception as e:
            logger.error(f"Error sending PDF document: {e}", exc_info=True)
            return None


# ═══════════════════════════════════════════════════════════════════════════
# EXPORT
# ═══════════════════════════════════════════════════════════════════════════

__all__ = [
    'MessageManager',
]