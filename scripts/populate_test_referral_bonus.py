#!/usr/bin/env python3
"""
СЦЕНАРИЙ 3: Тест Referral Bonus (1% опционами для покупок ≥$5000)

Структура:
ROOT (director)
  → ⭐️ Зодд (start) - upline, ПОЛУЧИТ бонус
    → ⭐️ Килл (start) - downline, ДЕЛАЕТ покупку ≥$5000

Что тестируем:
1. Килл делает покупку ≥$5000 через Telegram
2. Зодд (его upline) получает 1% = $50+ в виде ОПЦИОНОВ
3. Автоматическая покупка опционов для Зодд
4. Транзакции ActiveBalance для Зодд:
   - +$50 (credit от бонуса)
   - -$50 (debit на авто-покупку опционов)
   - Net effect: 0 на balanceActive
5. Опционы добавляются в портфель Зодд

Условия:
- Referral bonus только для покупок ≥$5000
- Выдается ОПЦИОНАМИ, не деньгами
- Upline должен быть active

Как тестировать:
1. python scripts/populate_test_referral_bonus.py
2. В Telegram от имени КИЛЛ делаешь покупку ≥$5000
3. Проверяешь, что Зодд получил опционы:
   python scripts/check_referral_bonus.py --downline-id 5478046601

Usage:
    python scripts/populate_test_referral_bonus.py
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
        "telegram_id": 5971989877,  # ⭐️ ЗОДД - upline, получит бонус
        "firstname": "Зодд",
        "surname": "Зверев",
        "email": "zodd@test.com",
        "rank": "start",
        "is_active": True,  # ВАЖНО: должен быть активен!
        "balance": 5000
    },
    {
        "telegram_id": 5478046601,  # ⭐️ КИЛЛ - downline, делает покупку
        "firstname": "Килл",
        "surname": "Лайт",
        "email": "kill@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 10000  # Для покупки ≥$5000
    }
]


async def main():
    """Main population script."""
    print("\n" + "=" * 80)
    print("🧪 СЦЕНАРИЙ 3: REFERRAL BONUS (1% ОПЦИОНАМИ)")
    print("=" * 80)
    print("\nСтруктура:")
    print("  ROOT (director)")
    print("    → ⭐️ ЗОДД (upline) - ПОЛУЧИТ 1% опционами")
    print("      → ⭐️ КИЛЛ (downline) - ДЕЛАЕТ покупку ≥$5000")
    print("\nУсловия:")
    print("  • Покупка должна быть ≥ $5,000")
    print("  • Бонус выдается ОПЦИОНАМИ (не деньгами)")
    print("  • Upline должен быть active (✅)")
    print("\nПример:")
    print("  Килл покупает за $5,000")
    print("  → Зодд получает 1% = $50 опционов")
    print("  → Авто-покупка опционов для Зодд")
    print("  → Net effect на balance = 0")
    print("  → Но опционы добавлены в портфель!")
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
    print("1. Открой Telegram от имени КИЛЛ (5478046601)")
    print("2. Сделай покупку на $5,000 или больше")
    print("3. Проверь результат:")
    print("   python scripts/check_referral_bonus.py --downline-id 5478046601")
    print("\n📊 ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:")
    print("   • Bonus record: commissionType='referral', 1% от покупки")
    print("   • Авто-покупка опционов для Зодд")
    print("   • ActiveBalance транзакции: +бонус, -покупка")
    print("   • Net effect на balanceActive Зодд = 0")
    print("   • Но опционы добавлены!")
    print("\n💡 ТЕСТ С НЕАКТИВНЫМ UPLINE:")
    print("   Можешь деактивировать Зодд и проверить, что бонус НЕ выдается")
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
