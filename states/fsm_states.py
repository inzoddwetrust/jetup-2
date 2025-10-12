# jetup/states/fsm_states.py
"""
FSM States for Jetup bot.
"""
from aiogram.fsm.state import State, StatesGroup


class ProjectCarouselState(StatesGroup):
    """States for project carousel."""
    wait_for_welcome = State()
    current_project_index = State()
    view_project_details = State()


class PurchaseFlow(StatesGroup):
    """States for purchase process."""
    waiting_for_payment = State()
    waiting_for_purchase_confirmation = State()


class UserDataDialog(StatesGroup):
    """States for user data collection."""
    waiting_for_firstname = State()
    waiting_for_surname = State()
    waiting_for_birthday = State()
    waiting_for_passport = State()
    waiting_for_country = State()
    waiting_for_city = State()
    waiting_for_address = State()
    waiting_for_phone = State()
    waiting_for_email = State()
    waiting_for_confirmation = State()


class TransferDialog(StatesGroup):
    """States for balance transfer."""
    select_source = State()
    select_recipient_type = State()
    enter_recipient_id = State()
    enter_amount = State()
    confirm_transfer = State()


class TxidInputState(StatesGroup):
    """States for TXID input."""
    waiting_for_txid = State()