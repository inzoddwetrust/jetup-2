# jetup/fsm_states.py
from aiogram.fsm.state import State, StatesGroup  # aiogram 3 import!

class UserDataDialog(StatesGroup):
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

class ProjectCarouselState(StatesGroup):
    wait_for_welcome = State()
    current_project_index = State()
    view_project_details = State()

class PurchaseFlow(StatesGroup):
    waiting_for_payment = State()
    waiting_for_purchase_confirmation = State()

class TxidInputState(StatesGroup):
    waiting_for_txid = State()

class TransferDialog(StatesGroup):
    select_source = State()
    select_recipient_type = State()
    enter_recipient_id = State()
    enter_amount = State()
    confirm_transfer = State()