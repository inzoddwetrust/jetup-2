# jetup/handlers/portfolio.py
"""
Portfolio handlers - user's investments and purchases.
"""
import logging
from aiogram import Router, F
from aiogram.types import CallbackQuery
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from models.user import User
from models.purchase import Purchase
from core.message_manager import MessageManager
from config import Config

logger = logging.getLogger(__name__)

portfolio_router = Router(name="portfolio_router")


# ============================================================================
# MAIN PORTFOLIO SCREEN
# ============================================================================

@portfolio_router.callback_query(F.data == "/case")
async def portfolio_main(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show main portfolio screen with investment summary."""
    logger.info(f"User {user.userID} opened portfolio")

    # Calculate total investment amount
    user_purchases_total = session.query(func.sum(Purchase.packPrice)).filter(
        Purchase.userID == user.userID
    ).scalar() or 0

    # Calculate total shares quantity
    user_purchases_qty = session.query(func.sum(Purchase.packQty)).filter(
        Purchase.userID == user.userID
    ).scalar() or 0

    # Count unique projects
    user_projects_total = session.query(func.count(func.distinct(Purchase.projectID))).filter(
        Purchase.userID == user.userID
    ).scalar() or 0

    await message_manager.send_template(
        user=user,
        template_key='/case',
        update=callback_query,
        variables={
            'userPurchasesQty': user_purchases_qty,
            'userPurchasesTotal': float(user_purchases_total),
            'userProjectsTotal': user_projects_total
        },
        edit=True
    )


# ============================================================================
# MY PURCHASES
# ============================================================================

@portfolio_router.callback_query(F.data == "/case/purchases")
async def my_purchases(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show list of user's purchases with PDF links."""
    logger.info(f"User {user.userID} viewing purchases")

    purchases = session.query(Purchase).filter_by(userID=user.userID).all()

    if purchases:
        # Get bot username for deep links
        bot_username = Config.get(Config.BOT_USERNAME)

        # Build PDF links
        doc_links = []
        for purchase in purchases:
            link = f"https://t.me/{bot_username}?start=purchase_{purchase.purchaseID}"
            doc_links.append(f"<a href='{link}'>PDF</a>")

        # Use rgroup for repeating rows
        context = {
            "rgroup": {
                'i': list(range(1, len(purchases) + 1)),
                'projectName': [p.projectName for p in purchases],
                'shares': [p.packQty for p in purchases],
                'price': [float(p.packPrice) for p in purchases],
                'date': [p.createdAt.strftime('%Y-%m-%d') for p in purchases],
                'PDF': doc_links
            }
        }

        await message_manager.send_template(
            user=user,
            template_key='/case/purchases',
            variables=context,
            update=callback_query,
            edit=True
        )
    else:
        await message_manager.send_template(
            user=user,
            template_key='/case/purchases/empty',
            update=callback_query,
            edit=True
        )


# ============================================================================
# CERTIFICATES
# ============================================================================

@portfolio_router.callback_query(F.data == "/case/certs")
async def my_certificates(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show certificates aggregated by project."""
    logger.info(f"User {user.userID} viewing certificates")

    purchases = session.query(Purchase).filter_by(userID=user.userID).all()

    if not purchases:
        await message_manager.send_template(
            user=user,
            template_key='/case/certs/empty',
            update=callback_query,
            edit=True
        )
        return

    # Aggregate by project
    project_aggregates = {}
    for purchase in purchases:
        project_id = purchase.projectID
        if project_id not in project_aggregates:
            project_aggregates[project_id] = {
                'projectName': purchase.projectName,
                'total_qty': 0,
                'total_price': 0,
                'latest_date': purchase.createdAt  # ДОБАВЛЕНО: дата последней покупки
            }
        project_aggregates[project_id]['total_qty'] += purchase.packQty
        project_aggregates[project_id]['total_price'] += purchase.packPrice

        # ДОБАВЛЕНО: обновляем дату если текущая покупка новее
        if purchase.createdAt > project_aggregates[project_id]['latest_date']:
            project_aggregates[project_id]['latest_date'] = purchase.createdAt

    # Get bot username for deep links
    bot_username = Config.get(Config.BOT_USERNAME)

    # Build certificate links and data lists
    cert_links = []
    project_names = []
    total_shares = []
    total_amounts = []
    dates = []  # ДОБАВЛЕНО: список дат

    for project_id, data in project_aggregates.items():
        link = f"https://t.me/{bot_username}?start=certificate_{project_id}"
        cert_links.append(f"<a href='{link}'>PDF</a>")

        project_names.append(data['projectName'])
        total_shares.append(data['total_qty'])
        total_amounts.append(float(data['total_price']))
        dates.append(data['latest_date'].strftime('%Y-%m-%d'))  # ДОБАВЛЕНО: форматируем дату

    # Use rgroup for repeating rows
    context = {
        "rgroup": {
            'i': list(range(1, len(project_aggregates) + 1)),
            'projectName': project_names,
            'shares': total_shares,
            'price': total_amounts,  # ИСПРАВЛЕНО: было 'amount', стало 'price'
            'date': dates,  # ДОБАВЛЕНО: массив дат
            'PDF': cert_links
        }
    }

    await message_manager.send_template(
        user=user,
        template_key='/case/certs',
        variables=context,
        update=callback_query,
        edit=True
    )


# ============================================================================
# INVESTMENT STRATEGIES
# ============================================================================

@portfolio_router.callback_query(F.data == "/case/strategies")
async def show_strategies(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show investment strategy selection."""
    logger.info(f"User {user.userID} viewing strategies")

    # Get current strategy
    current_strategy = user.settings.get('strategy', 'manual') if user.settings else 'manual'

    await message_manager.send_template(
        user=user,
        template_key=['/case/strategies', f'/case/strategies/{current_strategy}'],
        update=callback_query,
        edit=True
    )


@portfolio_router.callback_query(F.data.startswith("/case/strategies/set_"))
async def select_strategy(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Handle strategy selection."""
    # Extract strategy key from callback data: /case/strategies/set_manual -> manual
    strategy_key = callback_query.data.split("_")[1]

    logger.info(f"User {user.userID} selecting strategy: {strategy_key}")

    # Get current strategy
    current_strategy = user.settings.get('strategy', 'manual') if user.settings else 'manual'

    # Update strategy in settings JSON
    if not user.settings:
        user.settings = {}

    user.settings['strategy'] = strategy_key

    # Flag JSON field as modified
    flag_modified(user, 'settings')

    session.commit()
    session.refresh(user)

    logger.info(f"User {user.userID} strategy updated to: {strategy_key}")

    # Check if already selected - show answer popup
    if current_strategy == strategy_key:
        await callback_query.answer("This strategy is already selected")
        return

    # Show updated strategy screen
    template_keys = ['/case/strategies', f'/case/strategies/{strategy_key}']

    try:
        await message_manager.send_template(
            user=user,
            template_key=template_keys,
            update=callback_query,
            edit=True
        )
    except Exception as e:
        logger.warning(f"Error updating strategy message: {e}")


# ============================================================================
# PORTFOLIO VALUE
# ============================================================================

@portfolio_router.callback_query(F.data == "/case/value")
async def portfolio_value(
        callback_query: CallbackQuery,
        user: User,
        session: Session,
        message_manager: MessageManager
):
    """Show portfolio value with strategy projection."""
    logger.info(f"User {user.userID} viewing portfolio value")

    # Get current strategy
    strategy = user.settings.get('strategy', 'manual') if user.settings else 'manual'

    # Get strategy coefficients from Config
    strategy_coefficients = Config.get('STRATEGY_COEFFICIENTS', {
        'manual': 1.0,
        'safe': 1.5,
        'aggressive': 2.0,
        'risky': 3.0
    })

    coefficient = strategy_coefficients.get(strategy, 1.0)

    # Calculate total investment
    user_purchases_total = session.query(func.sum(Purchase.packPrice)).filter(
        Purchase.userID == user.userID
    ).scalar() or 0

    # Calculate projected value
    projected_value = float(user_purchases_total) * coefficient

    # Calculate total shares
    user_shares_total = session.query(func.sum(Purchase.packQty)).filter(
        Purchase.userID == user.userID
    ).scalar() or 0

    # Calculate growth percentage
    growth_percent = (coefficient - 1) * 100

    # Build template keys based on strategy
    template_keys = [f'portfolio_value_strategy_{strategy}']

    if strategy == "manual":
        template_keys.append('portfolio_value_manual')
    else:
        template_keys.append('portfolio_value_info')

    template_keys.append('portfolio_value_back')

    await message_manager.send_template(
        user=user,
        template_key=template_keys,
        variables={
            'current_value': float(user_purchases_total),
            'projected_value': projected_value,
            'growth_percent': growth_percent,
            'total_shares': user_shares_total
        },
        update=callback_query,
        edit=True
    )