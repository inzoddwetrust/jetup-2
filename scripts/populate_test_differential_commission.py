#!/usr/bin/env python3
"""
СЦЕНАРИЙ 1: Тест дифференциальных комиссий с компрессией

Структура для живого тестирования:
ROOT (director, 18%)
  → Dummy1 (❌ inactive, start) - СЖИМАЕТСЯ
    → Dummy2 (✅ active, builder, 10%)
      → Dummy3 (❌ inactive, start) - СЖИМАЕТСЯ
        → ⭐️ Зодд (✅ active, start, 7%) - ТЫ делаешь покупку через Telegram!

Что тестируем:
1. Покупка от Зодд через Telegram
2. Зодд НЕ получает комиссию (покупатель не получает)
3. Dummy3 сжимается (неактивен)
4. Dummy2 получает 10% + сжатую часть от Dummy3
5. Dummy1 сжимается (неактивен)
6. ROOT получает оставшееся до 18%

Как тестировать:
1. python scripts/populate_test_differential_commission.py
2. В Telegram от имени Зодд делаешь покупку на $1000
3. Проверяешь комиссии: python scripts/check_commissions.py --purchase-id <ID>

Usage:
    python scripts/populate_test_differential_commission.py
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


# Структура для теста
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
        "telegram_id": 100001,
        "firstname": "Dummy1_Inactive",
        "surname": "Level1",
        "email": "dummy1@test.com",
        "rank": "start",
        "is_active": False,  # СЖИМАЕТСЯ
        "balance": 0
    },
    {
        "telegram_id": 100002,
        "firstname": "Dummy2_Builder",
        "surname": "Level2",
        "email": "dummy2@test.com",
        "rank": "builder",
        "is_active": True,  # Получит 10% + compression
        "balance": 0
    },
    {
        "telegram_id": 100003,
        "firstname": "Dummy3_Inactive",
        "surname": "Level3",
        "email": "dummy3@test.com",
        "rank": "start",
        "is_active": False,  # СЖИМАЕТСЯ
        "balance": 0
    },
    {
        "telegram_id": 5971989877,  # ⭐️ ЗОДД
        "firstname": "Зодд",
        "surname": "Зверев",
        "email": "zodd@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 10000  # Баланс для покупок
    }
]


async def main():
    """Main population script."""
    print("\n" + "=" * 80)
    print("🧪 СЦЕНАРИЙ 1: ДИФФЕРЕНЦИАЛЬНЫЕ КОМИССИИ С КОМПРЕССИЕЙ")
    print("=" * 80)
    print("\nСтруктура:")
    print("  ROOT (director, 18%)")
    print("    → Dummy1 ❌ (inactive) - сжимается")
    print("      → Dummy2 ✅ (builder, 10%) - получит свои 10% + compression")
    print("        → Dummy3 ❌ (inactive) - сжимается")
    print("          → ⭐️ ЗОДД ✅ (start, 7%) - ТЫ делаешь покупку!")
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

    print("⛓️  Creating test chain...")
    await create_test_chain()
    print("✓ Test chain created\n")

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
    print("2. Сделай покупку на $1000 (или любую сумму)")
    print("3. Проверь результат:")
    print("   python scripts/check_commissions.py --last")
    print("\n📊 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:")
    print("   • Dummy2 (builder): ~10% + compression от Dummy1 и Dummy3")
    print("   • ROOT: оставшееся до 18%")
    print("   • Сумма всех комиссий = 18% от покупки")
    print("\n")


async def import_projects():
    """Import projects and options from Google Sheets."""
    result = await import_projects_and_options()
    if not result.get("success"):
        raise Exception(f"Import failed: {result.get('error_messages')}")


async def create_test_chain():
    """Create test chain."""
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
                f"rank: {user.rank}, active: {user.isActive})"
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
