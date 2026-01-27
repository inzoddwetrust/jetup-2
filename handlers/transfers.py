"""
Transfer handlers - internal balance transfers between users.

REFACTORED: Balance updates now handled by event listeners.
See: models/listeners/balance_listeners.py
"""
import logging
from decimal import Decimal
from typing import Tuple, Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.orm import Session

from models.user import User
from models.transfer import Transfer
from models.bonus import Bonus
from models.active_balance import ActiveBalance
from models.passive_balance import PassiveBalance
from models.notification import Notification
from core.message_manager import MessageManager
from core.templates import MessageTemplates
from states.fsm_states import TransferDialog
from config import Config

logger = logging.getLogger(__name__)
transfers_router = Router(name="transfers_router")


# ==================== UTILITIES ====================

def mask_name(name: str) -> str:
    """
    Mask name for security, leaving only first letter.

    Args:
        name: Original name

    Returns:
        Masked name (e.g., "Alice" → "A***")
    """
    if not name:
        return ""
    return name[0] + "***"


class TransferValidator:
    """Validator for transfer dialog input."""

    @staticmethod
    def validate_recipient_id(
            user_id: str,
            source_balance: str,
            sender_id: int,
            session: Session
    ) -> Tuple[bool, Any]:
        """
        Validate recipient ID.

        Args:
            user_id: Input string with user ID
            source_balance: 'active' or 'passive'
            sender_id: Sender's user ID
            session: Database session

        Returns:
            Tuple of (is_valid, result)
            If valid: (True, recipient_id)
            If invalid: (False, error_code)
        """
        try:
            recipient_id = int(user_id.strip())

            # Check if user trying to send to themselves from active balance
            if recipient_id == sender_id and source_balance == 'active':
                return False, "self_transfer_not_allowed"

            # Check if recipient exists
            recipient = session.query(User).filter_by(userID=recipient_id).first()
            if not recipient:
                return False, "recipient_not_found"

            return True, recipient_id

        except ValueError:
            return False, "invalid_id_format"

    @staticmethod
    def validate_amount(
            amount_str: str,
            source_balance: str,
            sender_id: int,
            session: Session
    ) -> Tuple[bool, Any]:
        """
        Validate transfer amount.

        Args:
            amount_str: Input string with amount
            source_balance: 'active' or 'passive'
            sender_id: Sender's user ID
            session: Database session

        Returns:
            Tuple of (is_valid, result)
            If valid: (True, amount) - just the amount, bonus calculated later
            If invalid: (False, error_code)
        """
        try:
            amount = float(amount_str.strip().replace(',', '.'))

            # Check if amount is positive
            if amount <= 0:
                return False, "non_positive_amount"

            # Check if user has enough balance
            sender = session.query(User).filter_by(userID=sender_id).first()
            if sender:
                available_balance = (
                    sender.balanceActive if source_balance == 'active'
                    else sender.balancePassive
                )
                if amount > float(available_balance):
                    return False, "insufficient_funds"

            return True, amount

        except ValueError:
            return False, "invalid_amount_format"


# ==================== HANDLERS ====================

@transfers_router.callback_query(F.data == "transfer_active")
async def start_transfer_active(
        callback_query: CallbackQuery,
        state: FSMContext,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Start transfer from ACTIVE balance.
    Goes straight to entering recipient ID.
    """
    logger.info(f"User {user.userID} starting transfer from ACTIVE balance")

    await state.clear()

    # Save transfer data
    await state.update_data(
        source_balance="active",
        sender_id=user.userID
    )

    # Ask for recipient ID
    await message_manager.send_template(
        user=user,
        template_key='transfer_active_enter_user_id',
        update=callback_query,
        variables={'balance': float(user.balanceActive)},
        edit=True
    )

    await state.set_state(TransferDialog.enter_recipient_id)


@transfers_router.callback_query(F.data == "transfer_passive")
async def start_transfer_passive(
        callback_query: CallbackQuery,
        state: FSMContext,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Start transfer from PASSIVE balance.
    First asks: to self or to another user?
    """
    logger.info(f"User {user.userID} starting transfer from PASSIVE balance")

    await state.clear()

    # Save transfer data
    await state.update_data(
        source_balance="passive",
        sender_id=user.userID
    )

    # Ask: to self or to other user?
    await message_manager.send_template(
        user=user,
        template_key='transfer_passive_select_recipient',
        update=callback_query,
        variables={'balance': float(user.balancePassive)},
        edit=True
    )

    await state.set_state(TransferDialog.select_recipient_type)


@transfers_router.callback_query(
    F.data.in_([
        "transfer_cancel",
        "transfer_passive_to_self",
        "transfer_passive_to_other"
    ])
)
async def handle_transfer_buttons(
        callback_query: CallbackQuery,
        state: FSMContext,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Handle button callbacks during transfer dialog.

    Callbacks:
        - transfer_cancel: Cancel transfer and return to balance screen
        - transfer_passive_to_self: Transfer to own active balance
        - transfer_passive_to_other: Transfer to another user
    """
    callback_data = callback_query.data

    if callback_data == "transfer_cancel":
        # Get transfer data
        data = await state.get_data()
        source_balance = data.get('source_balance', 'active')

        # Clear FSM state
        await state.clear()

        # Get balance value
        balance_value = (
            user.balanceActive if source_balance == 'active'
            else user.balancePassive
        )

        # Return to balance screen
        template_key = 'active_balance' if source_balance == 'active' else 'passive_balance'

        await message_manager.send_template(
            user=user,
            template_key=template_key,
            update=callback_query,
            variables={
                'userid': user.userID,
                'balance': float(balance_value)
            },
            edit=True
        )

        logger.info(f"User {user.userID} cancelled transfer")

    elif callback_data == "transfer_passive_to_self":
        # Transfer from passive to own active balance
        await state.update_data(
            recipient_type="self",
            recipient_id=user.userID
        )

        # Full name (no masking for self)
        recipient_name = f"{user.firstname} {user.surname or ''}".strip()

        # Go directly to amount entry
        bonus_percent = Config.get('TRANSFER_BONUS', 2)

        await message_manager.send_template(
            user=user,
            template_key='transfer_passive_self_enter_amount',
            update=callback_query,
            variables={
                'balance': float(user.balancePassive),
                'recipient_name': recipient_name,
                'recipient_id': user.userID,
                'bonus_percent': bonus_percent
            },
            edit=True
        )

        await state.set_state(TransferDialog.enter_amount)

        logger.info(f"User {user.userID} transferring to self")

    elif callback_data == "transfer_passive_to_other":
        # Transfer to another user
        await state.update_data(recipient_type="other")

        await message_manager.send_template(
            user=user,
            template_key='transfer_passive_enter_user_id',
            update=callback_query,
            variables={'balance': float(user.balancePassive)},
            edit=True
        )

        await state.set_state(TransferDialog.enter_recipient_id)

        logger.info(f"User {user.userID} transferring to other")


@transfers_router.message(TransferDialog.enter_recipient_id)
async def process_recipient_id(
        message: Message,
        state: FSMContext,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Process recipient ID input.
    Validates ID and moves to amount entry.
    """
    # Get transfer data
    data = await state.get_data()
    source_balance = data.get('source_balance')
    sender_id = data.get('sender_id')

    # Validate recipient ID
    is_valid, result = TransferValidator.validate_recipient_id(
        message.text,
        source_balance,
        sender_id,
        session
    )

    if not is_valid:
        # Show error
        error_template = f'transfer_error_{result}'

        balance_value = (
            user.balanceActive if source_balance == 'active'
            else user.balancePassive
        )

        await message_manager.send_template(
            user=user,
            template_key=error_template,
            update=message,
            variables={'balance': float(balance_value)}
        )
        return

    # Save recipient ID
    recipient_id = result
    await state.update_data(recipient_id=recipient_id)

    # Get recipient info
    recipient = session.query(User).filter_by(userID=recipient_id).first()

    # Mask recipient name
    masked_first_name = mask_name(recipient.firstname)
    masked_surname = mask_name(recipient.surname) if recipient.surname else ""
    recipient_name = f"{masked_first_name} {masked_surname}".strip()

    # Move to amount entry
    template_key = (
        'transfer_active_enter_amount' if source_balance == 'active'
        else 'transfer_passive_other_enter_amount'
    )

    bonus_percent = Config.get('TRANSFER_BONUS', 2)
    balance_value = (
        user.balanceActive if source_balance == 'active'
        else user.balancePassive
    )

    await message_manager.send_template(
        user=user,
        template_key=template_key,
        update=message,
        variables={
            'balance': float(balance_value),
            'recipient_name': recipient_name,
            'recipient_id': recipient_id,
            'bonus_percent': bonus_percent
        }
    )

    await state.set_state(TransferDialog.enter_amount)

    logger.info(f"User {user.userID} entering amount for transfer to {recipient_id}")


@transfers_router.message(TransferDialog.enter_amount)
async def process_amount(
        message: Message,
        state: FSMContext,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Process amount input.
    Validates amount and shows confirmation.
    """
    # Get transfer data
    data = await state.get_data()
    source_balance = data.get('source_balance')
    sender_id = data.get('sender_id')
    recipient_id = data.get('recipient_id')

    # Validate amount
    is_valid, result = TransferValidator.validate_amount(
        message.text,
        source_balance,
        sender_id,
        session
    )

    if not is_valid:
        # Show error
        error_template = f'transfer_error_{result}'

        balance_value = (
            user.balanceActive if source_balance == 'active'
            else user.balancePassive
        )

        await message_manager.send_template(
            user=user,
            template_key=error_template,
            update=message,
            variables={'balance': float(balance_value)}
        )
        return

    # Save amount (just the transfer amount, bonus calculated separately)
    amount = result
    await state.update_data(amount=amount)

    # Calculate what recipient will get (for display only)
    recipient_amount = amount
    bonus_amount = 0
    if source_balance == 'passive':
        bonus_percent = Config.get('TRANSFER_BONUS', 2)
        bonus_amount = amount * (bonus_percent / 100)
        recipient_amount = amount + bonus_amount

    # Get recipient info
    recipient = session.query(User).filter_by(userID=recipient_id).first()

    # Mask recipient name if not self
    if recipient_id != user.userID:
        masked_first_name = mask_name(recipient.firstname)
        masked_surname = mask_name(recipient.surname) if recipient.surname else ""
        recipient_name = f"{masked_first_name} {masked_surname}".strip()
    else:
        # Full name for self
        recipient_name = f"{recipient.firstname} {recipient.surname or ''}".strip()

    # Prepare bonus text
    bonus_text = ""
    if source_balance == 'passive':
        bonus_percent = Config.get('TRANSFER_BONUS', 2)
        bonus_text = f"+{bonus_percent}%"

    # Show confirmation
    await message_manager.send_template(
        user=user,
        template_key='transfer_confirm',
        update=message,
        variables={
            'amount': amount,
            'recipient_amount': recipient_amount,
            'recipient_name': recipient_name,
            'recipient_id': recipient_id,
            'bonus_text': bonus_text
        }
    )

    await state.set_state(TransferDialog.confirm_transfer)

    logger.info(f"User {user.userID} confirming transfer of {amount} to {recipient_id}")


@transfers_router.callback_query(F.data == "transfer_execute", TransferDialog.confirm_transfer)
async def execute_transfer(
        callback_query: CallbackQuery,
        state: FSMContext,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Execute the transfer.

    Creates Transfer record and journal entries (ActiveBalance/PassiveBalance).
    User balances are updated automatically by event listeners.
    See: models/listeners/balance_listeners.py

    If from passive, creates pending Bonus for TransferBonusProcessor.
    """
    try:
        # Get transfer data
        data = await state.get_data()
        source_balance = data.get('source_balance')
        recipient_id = data.get('recipient_id')
        amount = Decimal(str(data.get('amount')))

        # Calculate bonus if from passive
        bonus_amount = Decimal("0")
        if source_balance == 'passive':
            bonus_percent = Config.get('TRANSFER_BONUS', 2)
            bonus_amount = amount * Decimal(str(bonus_percent)) / Decimal("100")

        total_recipient_amount = amount + bonus_amount

        logger.info(
            f"Executing transfer: user {user.userID} → {recipient_id}, "
            f"amount {amount}, bonus {bonus_amount}, total {total_recipient_amount}, "
            f"source {source_balance}"
        )

        # Lock users for update
        sender_db = session.query(User).filter_by(userID=user.userID).with_for_update().first()
        recipient = session.query(User).filter_by(userID=recipient_id).with_for_update().first()

        if not sender_db or not recipient:
            raise ValueError("Sender or recipient not found")

        # Check balance again
        if source_balance == "active" and sender_db.balanceActive < amount:
            raise ValueError("Insufficient funds on active balance")

        if source_balance == "passive" and sender_db.balancePassive < amount:
            raise ValueError("Insufficient funds on passive balance")

        # Create transfer record (ONLY the actual transfer amount, not bonus)
        transfer = Transfer(
            senderUserID=user.userID,
            senderFirstname=sender_db.firstname,
            senderSurname=sender_db.surname,
            fromBalance=source_balance,
            amount=amount,
            receiverUserID=recipient_id,
            receiverFirstname=recipient.firstname,
            receiverSurname=recipient.surname,
            toBalance="active",
            status="done",
            notes=f"Transfer from {source_balance} balance"
        )
        session.add(transfer)
        session.flush()

        # ═══════════════════════════════════════════════════════════════════════
        # SENDER: Create journal entry (listener will update User balance)
        # ═══════════════════════════════════════════════════════════════════════
        if source_balance == "active":
            sender_record = ActiveBalance(
                userID=user.userID,
                firstname=sender_db.firstname,
                surname=sender_db.surname,
                amount=-amount,
                status='done',
                reason=f'transfer={transfer.transferID}',
                notes=f'Transfer to user {recipient_id}'
            )
            session.add(sender_record)
        else:  # passive
            sender_record = PassiveBalance(
                userID=user.userID,
                firstname=sender_db.firstname,
                surname=sender_db.surname,
                amount=-amount,
                status='done',
                reason=f'transfer={transfer.transferID}',
                notes=f'Transfer to user {recipient_id}'
            )
            session.add(sender_record)

        # ═══════════════════════════════════════════════════════════════════════
        # RECIPIENT: Create journal entry (listener will update User balance)
        # ═══════════════════════════════════════════════════════════════════════
        recipient_transfer_record = ActiveBalance(
            userID=recipient_id,
            firstname=recipient.firstname,
            surname=recipient.surname,
            amount=amount,
            status='done',
            reason=f'transfer={transfer.transferID}',
            notes=f'Transfer from user {user.userID}'
        )
        session.add(recipient_transfer_record)

        # If from passive, create PENDING bonus record
        # TransferBonusProcessor will process it asynchronously
        if source_balance == 'passive' and bonus_amount > 0:
            bonus = Bonus(
                userID=recipient_id,
                downlineID=user.userID,  # From whom
                purchaseID=None,  # Not related to purchase
                projectID=None,
                optionID=None,
                packQty=None,
                packPrice=None,
                commissionType='transfer_bonus',  # KEY: different from MLM bonuses
                uplineLevel=None,
                fromRank=None,
                sourceRank=None,
                bonusRate=float(Config.get('TRANSFER_BONUS', 2)) / 100,  # 0.02 for 2%
                bonusAmount=bonus_amount,
                compressionApplied=0,
                status='pending',  # Will be processed by TransferBonusProcessor
                notes=f'Transfer bonus, transfer={transfer.transferID}',
                ownerTelegramID=recipient.telegramID,
                ownerEmail=recipient.email
            )
            session.add(bonus)
            session.flush()  # Get bonus.bonusID for logging

            logger.info(
                f"Created pending transfer bonus {bonus.bonusID}: "
                f"{bonus_amount} for user {recipient_id}"
            )

        # COMMIT TRANSFER (and pending bonus if created)
        # Event listeners will update User.balanceActive/balancePassive
        session.commit()

        # Refresh to get updated balances from listener
        session.refresh(sender_db)

        logger.info(f"Transfer {transfer.transferID} completed successfully")

        # Now try to send notification (non-critical)
        if user.userID != recipient_id:
            try:
                # Mask sender name
                masked_first_name = mask_name(sender_db.firstname)
                masked_surname = mask_name(sender_db.surname) if sender_db.surname else ""
                masked_sender_name = f"{masked_first_name} {masked_surname}".strip()

                # Prepare bonus text
                extra_bonus_text = ""
                if source_balance == 'passive':
                    bonus_percent = Config.get('TRANSFER_BONUS', 2)
                    extra_bonus_text = f" (+{bonus_percent}% bonus)"

                # Get template
                text, buttons = await MessageTemplates.get_raw_template(
                    'transfer_received_notification',
                    {
                        'sender_name': masked_sender_name,
                        'sender_id': user.userID,
                        'amount': float(total_recipient_amount),
                        'extra_bonus_text': extra_bonus_text
                    },
                    lang=recipient.lang
                )

                # Create notification
                notification = Notification(
                    source="transfer",
                    text=text,
                    buttons=buttons,
                    targetType="user",
                    targetValue=str(recipient_id),
                    priority=2,
                    category="transfer",
                    importance="high",
                    parseMode="HTML"
                )
                session.add(notification)
                session.commit()

                logger.info(f"Notification created for user {recipient_id}")

            except Exception as e:
                # Notification failed, but transfer is already completed - just log
                logger.error(f"Failed to create notification for transfer {transfer.transferID}: {e}")
                session.rollback()  # Only rollback notification, not transfer

        # Show success message
        await message_manager.send_template(
            user=user,
            template_key='transfer_success',
            update=callback_query,
            variables={
                'sender_name': f"{sender_db.firstname} {sender_db.surname or ''}".strip(),
                'sender_id': user.userID,
                'recipient_name': f"{recipient.firstname} {recipient.surname or ''}".strip(),
                'recipient_id': recipient_id,
                'amount': float(amount),
                'recipient_amount': float(total_recipient_amount),
                'source_balance': source_balance,
                'balanceActive': float(sender_db.balanceActive),
                'balancePassive': float(sender_db.balancePassive)
            },
            edit=True
        )

        # Clear FSM state
        await state.clear()

    except Exception as e:
        # Rollback ONLY if transfer itself failed
        session.rollback()
        logger.error(f"Error executing transfer: {e}", exc_info=True)

        await message_manager.send_template(
            user=user,
            template_key='transfer_error',
            update=callback_query,
            variables={'error_message': str(e)},
            edit=True
        )

        await state.clear()