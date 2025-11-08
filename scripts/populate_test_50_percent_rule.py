#!/usr/bin/env python3
"""
СЦЕНАРИЙ 4: Тест правила 50% (Transfer Bonus)

Структура:
ROOT (director)
  → Dummy1 (builder, active) - ПОЛУЧИТ 50% от комиссии Зодд
    → ⭐️ Зодд (start, active) - НЕТ активных downline
      → Килл (inactive) - неактивен, НЕ считается

Условие правила 50%:
Если у пользователя НЕТ активных партнеров в первой линии,
его upline получает 50% от его комиссии как transfer bonus.

Что тестируем:
1. Килл делает покупку (от его имени dummy покупка, или деактивируй его)
2. Зодд получает комиссию (например, $100)
3. У Зодд НЕТ активных downline (Килл неактивен)
4. Dummy1 (upline Зодд) получает transfer bonus: $100 × 50% = $50

Альтернатива для живого теста:
ROOT
  → Dummy1 (builder, active)
    → ⭐️ Зодд (start, active) - НЕТ downline ВООБЩЕ

Зодд СЕЙЧАС:
  → Dummy_child (какая-то покупка)
    → Зодд получит комиссию
    → У Зодд нет активных downline
    → Dummy1 получит 50%

Как тестировать:
1. python scripts/populate_test_50_percent_rule.py
2. Вариант A: Создать dummy покупку от Килл
3. Вариант B: Использовать симуляцию
4. Проверить transfer bonus:
   python scripts/check_transfer_bonus.py --user-id 5971989877

Usage:
    python scripts/populate_test_50_percent_rule.py
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
        "telegram_id": 100001,
        "firstname": "Dummy1_Builder",
        "surname": "Upline",
        "email": "dummy1@test.com",
        "rank": "builder",
        "is_active": True,  # Получит transfer bonus 50%
        "balance": 0
    },
    {
        "telegram_id": 5971989877,  # ⭐️ ЗОДД - НЕТ активных downline
        "firstname": "Зодд",
        "surname": "Зверев",
        "email": "zodd@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 5000
    },
    {
        "telegram_id": 100002,  # Dummy child для генерации покупки
        "firstname": "Dummy_Child",
        "surname": "Buyer",
        "email": "child@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 1000
    }
]


async def main():
    """Main population script."""
    print("\n" + "=" * 80)
    print("🧪 СЦЕНАРИЙ 4: ПРАВИЛО 50% (TRANSFER BONUS)")
    print("=" * 80)
    print("\nСтруктура:")
    print("  ROOT (director)")
    print("    → Dummy1 (builder) ✅ - ПОЛУЧИТ 50% transfer bonus")
    print("      → ⭐️ ЗОДД (start) ✅ - НЕТ активных downline")
    print("        → Dummy_Child ✅ - делает покупку")
    print("\nПравило:")
    print("  Если у пользователя НЕТ активных партнеров в 1-й линии,")
    print("  его upline получает 50% от его комиссии.")
    print("\nПример:")
    print("  1. Dummy_Child покупает за $1000")
    print("  2. Зодд получает комиссию $70 (7% как start)")
    print("  3. У Зодд НЕТ активных downline")
    print("  4. Dummy1 получает transfer bonus: $70 × 50% = $35")
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
    print("\nВариант 1 (симуляция через скрипт):")
    print("  python scripts/simulate_purchase.py --user-id 100002 --amount 1000")
    print("\nВариант 2 (вручную через SQL):")
    print("  Создать покупку от Dummy_Child и запустить processPurchase()")
    print("\n3. Проверить результат:")
    print("   python scripts/check_transfer_bonus.py --user-id 5971989877")
    print("\n📊 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:")
    print("   • Зодд получает свою комиссию (7%)")
    print("   • У Зодд НЕТ активных downline")
    print("   • Dummy1 получает transfer bonus = 50% от комиссии Зодд")
    print("   • Bonus запись с commissionType='transfer'")
    print("\n💡 ПРОВЕРКА УСЛОВИЯ:")
    print("   Если добавить активный downline Зодд → transfer bonus НЕ выдается")
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
                f"✓ Created: {user.firstname} (ID: {user.telegramID})"
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
