#!/usr/bin/env python3
"""
СЦЕНАРИЙ 2: Тест Investment Bonus (кумулятивные бонусы)

Структура:
ROOT (director)
  → ⭐️ Зодд (start) - ТЫ делаешь серию покупок!

Тиры investment bonus (кумулятивные):
- $1,000 → 5% cumulative = $50 bonus
- $5,000 → 10% cumulative = $500 bonus
- $10,000 → 15% cumulative = $1,500 bonus
- $20,000 → 20% cumulative = $4,000 bonus

Что тестируем:
1. Серия покупок от Зодд:
   - Покупка $400 → нет бонуса
   - Покупка $700 → бонус $55 (достиг $1100, тир 5%)
   - Покупка $4000 → бонус $455 (достиг $5100, тир 10%)
   - И так далее...
2. Каждый бонус автоматически конвертируется в опционы
3. Транзакции ActiveBalance: +бонус, -покупка (net = 0)
4. Опционы добавляются в портфель

Как тестировать:
1. python scripts/populate_test_investment_bonus.py
2. В Telegram от Зодд делай покупки по порядку:
   - Первая: $400
   - Вторая: $700  (должен получить ~$55 опционов)
   - Третья: $4000 (должен получить ~$455 опционов)
3. Проверяй после каждой: python scripts/check_investment_bonus.py --user-id 5971989877

Usage:
    python scripts/populate_test_investment_bonus.py
"""

import sys
import os
import asyncio
from decimal import Decimal
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm.attributes import flag_modified
from aiogram.types import User as TelegramUser
from config import Config
from core.db import get_session, setup_database, drop_all_tables
from models.user import User
from mlm_system.utils.chain_walker import ChainWalker
from services.imports import import_projects_and_options

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


TEST_USERS = [
    {
        "telegram_id": 526738615,
        "firstname": "Артем",
        "surname": "Root",
        "email": "artem@test.com",
        "rank": "director",
        "is_active": True,
        "balance": 100000,
        "is_root": True
    },
    {
        "telegram_id": 5971989877,  # ⭐️ ЗОДД
        "firstname": "Зодд",
        "surname": "Зверев",
        "email": "zodd@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 25000  # Достаточно для всех тестов
    }
]


async def main():
    """Main population script."""
    print("\n" + "=" * 80)
    print("🧪 СЦЕНАРИЙ 2: INVESTMENT BONUS (КУМУЛЯТИВНЫЕ БОНУСЫ)")
    print("=" * 80)
    print("\nСтруктура:")
    print("  ROOT (director)")
    print("    → ⭐️ ЗОДД (start, $25,000) - ТЫ делаешь серию покупок!")
    print("\nТиры для тестирования:")
    print("  1️⃣  Покупка $400  → всего $400  → нет бонуса")
    print("  2️⃣  Покупка $700  → всего $1,100 → бонус $55 (5% tier)")
    print("  3️⃣  Покупка $4,000 → всего $5,100 → бонус $455 (10% tier)")
    print("  4️⃣  Покупка $5,000 → всего $10,100 → бонус $1,065 (15% tier)")
    print("  5️⃣  Покупка $10,000 → всего $20,100 → бонус $3,510 (20% tier)")
    print("\n⚠️  WARNING: This will DROP and recreate the entire database!\n")

    confirm = input("Type 'YES' to continue: ")
    if confirm != "YES":
        print("❌ Aborted.")
        return

    print("\n🔄 Starting database population...\n")

    Config.initialize_from_env()

    print("💣 Dropping existing database...")
    drop_all_tables()
    print("✓ Database dropped\n")

    print("🗂️  Creating tables...")
    setup_database()
    print("✓ Tables created\n")

    print("📥 Importing projects from Google Sheets...")
    await import_projects()
    print("✓ Projects imported\n")

    print("⛓️  Creating test users...")
    await create_test_users()
    print("✓ Test users created\n")

    print("🔍 Validating chain integrity...")
    await validate_chain()
    print("✓ Chain validation passed\n")

    print("🌳 Structure visualization:\n")
    print_chain()

    print("\n" + "=" * 80)
    print("✅ DATABASE READY FOR TESTING!")
    print("=" * 80)
    print("\n📝 КАК ТЕСТИРОВАТЬ:")
    print("1. Открой Telegram от имени Зодд")
    print("2. Делай покупки ПО ПОРЯДКУ:")
    print("   a) Первая покупка: $400")
    print("      → Ожидаемый бонус: $0 (не достиг тира)")
    print("   b) Вторая покупка: $700")
    print("      → Ожидаемый бонус: ~$55 опционов (тир $1000, 5%)")
    print("   c) Третья покупка: $4000")
    print("      → Ожидаемый бонус: ~$455 опционов (тир $5000, 10%)")
    print("\n3. После каждой покупки проверяй:")
    print("   python scripts/check_investment_bonus.py --user-id 5971989877")
    print("\n💡 ВАЖНО:")
    print("   • Бонус НЕ деньги, а ОПЦИОНЫ (авто-покупка)")
    print("   • Баланс не меняется (credit + debit = 0)")
    print("   • Но опционы добавляются в портфель!")
    print("\n")


async def import_projects():
    """Import projects and options from Google Sheets."""
    result = await import_projects_and_options()
    if not result.get("success"):
        raise Exception(f"Import failed: {result.get('error_messages')}")


async def create_test_users():
    """Create test users."""
    session = get_session()
    try:
        previous_user = None

        for user_config in TEST_USERS:
            if user_config.get("is_root"):
                referrer_id = None
            else:
                referrer_id = previous_user.telegramID if previous_user else None

            telegram_user = TelegramUser(
                id=user_config["telegram_id"],
                is_bot=False,
                first_name=user_config["firstname"],
                last_name=user_config.get("surname"),
                language_code="ru"
            )

            user = User.create_from_telegram_data(
                session=session,
                telegram_user=telegram_user,
                referrer_id=referrer_id
            )

            user.surname = user_config.get("surname")
            user.email = user_config["email"]
            user.rank = user_config["rank"]
            user.isActive = user_config["is_active"]
            user.balanceActive = Decimal(str(user_config["balance"]))

            if user_config.get("is_root"):
                user.upline = user.telegramID

            user.personalData = {
                "dataFilled": True,
                "eulaAccepted": True,
                "eulaVersion": "1.0",
                "eulaAcceptedAt": datetime.now(timezone.utc).isoformat()
            }
            flag_modified(user, 'personalData')

            user.emailVerification = {"confirmed": True}
            flag_modified(user, 'emailVerification')

            if user_config.get("is_root"):
                user.mlmStatus = {"isFounder": True}
                flag_modified(user, 'mlmStatus')

            logger.info(
                f"✓ Created: {user.firstname} (ID: {user.telegramID}, "
                f"balance: ${user.balanceActive})"
            )

            previous_user = user

        session.commit()

    finally:
        session.close()


async def validate_chain():
    """Validate chain integrity."""
    session = get_session()
    try:
        walker = ChainWalker(session)

        if not walker.validate_default_referrer():
            raise Exception("DEFAULT_REFERRER validation failed!")

        orphans = walker.find_orphan_branches()
        if orphans:
            raise Exception(f"Found {len(orphans)} orphan users: {orphans}")

    finally:
        session.close()


def print_chain():
    """Print chain."""
    session = get_session()
    try:
        walker = ChainWalker(session)
        root = session.query(User).filter_by(telegramID=526738615).first()

        def print_user(user, level=0):
            connector = "  " * level + ("└─ " if level > 0 else "")
            rank_display = f"[{user.rank}]"
            balance_display = f"${user.balanceActive}" if user.balanceActive > 0 else ""
            root_marker = "👑 " if walker.is_system_root(user) else ""
            real_marker = "⭐️ " if user.telegramID >= 1000000 else ""
            active_marker = "✅" if user.isActive else "❌"

            print(
                f"{connector}{root_marker}{real_marker}{user.firstname} "
                f"(ID:{user.telegramID}) {active_marker} {rank_display} {balance_display}"
            )

            children = session.query(User).filter(User.upline == user.telegramID).all()
            children = [c for c in children if not walker.is_system_root(c)]

            for child in children:
                print_user(child, level + 1)

        print("=" * 80)
        print_user(root)
        print("=" * 80)

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
