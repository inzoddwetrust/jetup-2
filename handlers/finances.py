# jetup/handlers/finances.py
"""
Finances handlers - balance management and history.
"""
import logging
from decimal import Decimal
from typing import Tuple, Dict, List, Any

from aiogram import Router, F
from aiogram.types import CallbackQuery, BufferedInputFile
from sqlalchemy import func, not_
from sqlalchemy.orm import Session

from models.user import User
from models.purchase import Purchase
from models.payment import Payment
from models.bonus import Bonus
from models.active_balance import ActiveBalance
from models.passive_balance import PassiveBalance
from core.message_manager import MessageManager
from services.document.csv_generator import CSVGenerator

logger = logging.getLogger(__name__)
finances_router = Router(name="finances_router")


# ==================== UTILITIES (DRY) ====================

def _parse_history_callback(callback_data: str) -> Tuple[str, str]:
    """
    Parse callback like 'ab_history_payments' or 'pb_history_bonuses'.

    Args:
        callback_data: String like 'ab_history_payments', 'pb_history', etc.

    Returns:
        Tuple of (balance_type, operation_type)
        Examples:
            'ab_history_payments' → ('active', 'payments')
            'pb_history' → ('passive', 'bonuses')  # default for passive
            'ab_history' → ('active', 'payments')  # default for active
    """
    balance_type = "active" if callback_data.startswith("ab_") else "passive"

    # Extract operation type from callback
    parts = callback_data.split("_")
    operation_type = parts[-1] if len(parts) > 2 else None

    # Set defaults if operation_type is 'history' or None
    if not operation_type or operation_type == "history":
        operation_type = "payments" if balance_type == "active" else "bonuses"

    return balance_type, operation_type


def _get_balance_info(balance_type: str, user: User) -> Dict[str, Any]:
    """
    Get balance model, value, and default operation type.

    Args:
        balance_type: 'active' or 'passive'
        user: User object

    Returns:
        Dict with keys: 'model', 'value', 'default_operation'
    """
    if balance_type == "active":
        return {
            'model': ActiveBalance,
            'value': user.balanceActive,
            'default_operation': 'payments'
        }
    else:
        return {
            'model': PassiveBalance,
            'value': user.balancePassive,
            'default_operation': 'bonuses'
        }


def _build_history_filters(
        balance_type: str,
        operation_type: str,
        user_id: int,
        balance_model: Any
) -> List[Any]:
    """
    Build SQLAlchemy filters for balance history.

    Args:
        balance_type: 'active' or 'passive'
        operation_type: Type of operation (payments, purchases, transfers, bonuses, others)
        user_id: User ID to filter by
        balance_model: ActiveBalance or PassiveBalance model

    Returns:
        List of SQLAlchemy filter conditions
    """
    filters = [balance_model.userID == user_id]

    if balance_type == "active":
        if operation_type == "payments":
            filters.append(balance_model.reason.like('payment=%'))
        elif operation_type == "purchases":
            filters.append(balance_model.reason.like('purchase=%'))
        elif operation_type == "transfers":
            filters.append(balance_model.reason.like('transfer=%'))
    else:  # passive
        if operation_type == "bonuses":
            filters.append(balance_model.reason.like('bonus=%'))
        elif operation_type == "transfers":
            filters.append(balance_model.reason.like('transfer=%'))
        elif operation_type == "others":
            # Everything except bonuses and transfers
            filters.append(not_(balance_model.reason.like('bonus=%')))
            filters.append(not_(balance_model.reason.like('transfer=%')))

    return filters


def _format_history_records(records: List[Any]) -> Dict[str, List[Any]]:
    """
    Format balance records to template variables.

    Args:
        records: List of ActiveBalance or PassiveBalance records

    Returns:
        Dict with keys: 'date', 'amount', 'status', 'doc_id'
        Each value is a list formatted for display
    """
    dates = []
    amounts = []
    statuses = []
    doc_ids = []

    for record in records:
        # Format date
        dates.append(record.createdAt.strftime('%Y-%m-%d %H:%M'))

        # Format amount with emoji indicators
        amount_value = float(record.amount)
        amount_str = f"{abs(amount_value):.2f}"

        if amount_value >= 0:
            amounts.append(f"+{amount_str} 💚")  # Green heart for positive
        else:
            amounts.append(f"-{amount_str} ❤️")  # Red heart for negative

        # Status with emoji
        if record.status == 'done':
            statuses.append("✅")
        elif record.status == 'pending':
            statuses.append("⏳")
        elif record.status == 'failed':
            statuses.append("❌")
        else:
            statuses.append(record.status)

        # Extract document ID from reason field
        doc_id = "—"
        if record.reason and '=' in record.reason:
            doc_id = record.reason.split('=')[1]
        doc_ids.append(doc_id)

    return {
        'date': dates,
        'amount': amounts,
        'status': statuses,
        'doc_id': doc_ids
    }


# ==================== HANDLERS ====================

@finances_router.callback_query(F.data == "/finances")
async def handle_finances(
        callback_query: CallbackQuery,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Main finances screen with balances and statistics.
    Shows active/passive balances and totals for purchases, payments, bonuses.
    """
    logger.info(f"User {user.userID} opened finances screen")

    # Calculate user totals
    user_purchases_total = session.query(func.sum(Purchase.packPrice)).filter(
        Purchase.userID == user.userID
    ).scalar() or Decimal('0')

    user_payments_total = session.query(func.sum(Payment.amount)).filter(
        Payment.userID == user.userID,
        Payment.status == 'paid'
    ).scalar() or Decimal('0')

    user_bonuses_total = session.query(func.sum(Bonus.bonusAmount)).filter(
        Bonus.userID == user.userID,
        Bonus.status == 'paid'
    ).scalar() or Decimal('0')

    await message_manager.send_template(
        user=user,
        template_key='/finances',
        update=callback_query,
        variables={
            'balanceActive': float(user.balanceActive),
            'balancePassive': float(user.balancePassive),
            'firstname': user.firstname,
            'userid': user.userID,
            'surname': user.surname or '',
            'userPurchasesTotal': float(user_purchases_total),
            'userPaymentsTotal': float(user_payments_total),
            'userBonusesTotal': float(user_bonuses_total)
        },
        delete_original=True
    )


@finances_router.callback_query(F.data.in_(["active_balance", "passive_balance"]))
async def handle_balance_detail(
        callback_query: CallbackQuery,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Detailed balance screen (active or passive).
    Shows balance value with action buttons.
    """
    balance_type = callback_query.data  # "active_balance" or "passive_balance"

    logger.info(f"User {user.userID} opened {balance_type} screen")

    # Get balance value
    balance_value = user.balanceActive if balance_type == "active_balance" else user.balancePassive

    await message_manager.send_template(
        user=user,
        template_key=balance_type,  # Template name matches callback_data
        variables={
            'userid': user.userID,
            'balance': float(balance_value)
        },
        update=callback_query,
        delete_original=True
    )


@finances_router.callback_query(F.data.startswith(("ab_history", "pb_history")))
async def handle_balance_history(
        callback_query: CallbackQuery,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Universal balance history handler with operation type filters.
    Handles both active and passive balance history.

    Examples:
        ab_history_payments, ab_history_purchases, ab_history_transfers
        pb_history_bonuses, pb_history_transfers, pb_history_others
    """
    callback_data = callback_query.data

    # Parse callback to get balance type and operation type
    balance_type, operation_type = _parse_history_callback(callback_data)

    logger.info(f"User {user.userID} viewing {balance_type} history: {operation_type}")

    # Get balance info
    balance_info = _get_balance_info(balance_type, user)
    balance_model = balance_info['model']
    balance_value = balance_info['value']

    # Build context with balance value and active tab
    context = {
        f"balance{balance_type.capitalize()}": float(balance_value),
        "active_tab": operation_type
    }

    # Build filters for query
    filters = _build_history_filters(balance_type, operation_type, user.userID, balance_model)

    # Query records with filters, limit to last 10
    records = session.query(balance_model).filter(
        *filters
    ).order_by(balance_model.createdAt.desc()).limit(10).all()

    # Build template keys
    template_prefix = f"{balance_type}_balance_history"
    template_key = f"{template_prefix}_{operation_type}"
    empty_template_key = f"{template_prefix}_empty_{operation_type}"

    if records:
        # Format records to template variables
        context["rgroup"] = _format_history_records(records)

        await message_manager.send_template(
            user=user,
            template_key=template_key,
            update=callback_query,
            variables=context,
            delete_original=True
        )
    else:
        # Show empty state
        await message_manager.send_template(
            user=user,
            template_key=empty_template_key,
            update=callback_query,
            variables=context,
            delete_original=True
        )


@finances_router.callback_query(F.data.startswith("/finances/download/csv/"))
async def handle_csv_download(
        callback_query: CallbackQuery,
        session: Session,
        user: User,
        message_manager: MessageManager
):
    """
    Generate and send CSV report for balance history.

    Callbacks:
        /finances/download/csv/active - Active balance history
        /finances/download/csv/passive - Passive balance history
    """
    # Extract balance type from callback
    balance_type = callback_query.data.split("/")[-1]  # 'active' or 'passive'

    logger.info(f"User {user.userID} downloading {balance_type} balance CSV")

    # Show generating status
    await message_manager.send_template(
        user=user,
        template_key='csv_generating',
        update=callback_query,
        variables={'report_type': f'{balance_type}_balance'}
    )

    try:
        # Generate CSV report
        csv_generator = CSVGenerator()
        report_type = f"{balance_type}_balance_history"

        csv_data = csv_generator.generate_report(
            session=session,
            user=user,
            report_type=report_type
        )

        if not csv_data:
            # Show error
            await message_manager.send_template(
                user=user,
                template_key='csv_error',
                update=callback_query.message,
                variables={'error': 'Failed to generate report'}
            )
            return

        # Show ready status
        await message_manager.send_template(
            user=user,
            template_key='csv_ready',
            update=callback_query.message,
            variables={'report_type': f'{balance_type}_balance'}
        )

        # Send CSV file
        filename = f"{balance_type}_balance_history_{user.userID}.csv"
        document = BufferedInputFile(csv_data, filename=filename)

        await callback_query.message.answer_document(
            document=document,
            caption=f"📊 {balance_type.capitalize()} Balance History Report"
        )

        logger.info(f"CSV report sent to user {user.userID}")

    except Exception as e:
        logger.error(f"Error generating CSV for user {user.userID}: {e}", exc_info=True)

        await message_manager.send_template(
            user=user,
            template_key='csv_error',
            update=callback_query.message,
            variables={'error': str(e)}
        )