#!/usr/bin/env python3
"""
Commission Testing Population Script.

Creates a linear chain specifically for testing differential commissions
and compression mechanics.

Chain structure:
ROOT (director, 18%) → inactive → active (builder, 10%) → inactive → active (start, 7%) → Зодд (buyer)

Usage:
    python scripts/populate_commission_test.py
"""

import sys
import os
import asyncio
from decimal import Decimal
from datetime import datetime, timezone

# Add project root to path
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


# Test chain configuration
TEST_CHAIN = [
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
        "telegram_id": 100000,
        "firstname": "Inactive1",
        "surname": "Level1",
        "email": "inactive1@test.com",
        "rank": "start",
        "is_active": False,
        "balance": 0
    },
    {
        "telegram_id": 100001,
        "firstname": "Builder1",
        "surname": "Level2",
        "email": "builder1@test.com",
        "rank": "builder",
        "is_active": True,
        "balance": 0
    },
    {
        "telegram_id": 100002,
        "firstname": "Inactive2",
        "surname": "Level3",
        "email": "inactive2@test.com",
        "rank": "start",
        "is_active": False,
        "balance": 0
    },
    {
        "telegram_id": 100003,
        "firstname": "Start1",
        "surname": "Level4",
        "email": "start1@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 0
    },
    {
        "telegram_id": 5971989877,
        "firstname": "Зодд",
        "surname": "Зверев",
        "email": "zodd@test.com",
        "rank": "start",
        "is_active": True,
        "balance": 10000
    }
]


async def main():
    """Main population script."""
    print("\n" + "=" * 80)
    print("🧪 COMMISSION TESTING - DATABASE POPULATION")
    print("=" * 80)
    print("\nThis creates a linear chain for testing differential commissions.")
    print("⚠️  WARNING: This will DROP and recreate the entire database!\n")

    confirm = input("Type 'YES' to continue: ")
    if confirm != "YES":
        print("❌ Aborted.")
        return

    print("\n🔄 Starting database population...\n")

    # Step 1: Initialize config
    print("📋 Step 1: Loading configuration...")
    Config.initialize_from_env()
    print("✓ Configuration loaded\n")

    # Step 2: Drop and recreate database
    print("💣 Step 2: Dropping existing database...")
    drop_all_tables()
    print("✓ Database dropped\n")

    print("🗂️  Step 3: Creating tables...")
    setup_database()
    print("✓ Tables created\n")

    # Step 4: Import projects
    print("📥 Step 4: Importing projects from Google Sheets...")
    await import_projects()
    print("✓ Projects imported\n")

    # Step 5: Create chain
    print("⛓️  Step 5: Creating test chain...")
    await create_test_chain()
    print("✓ Test chain created\n")

    # Step 6: Validate
    print("🔍 Step 6: Validating chain integrity...")
    await validate_chain()
    print("✓ Chain validation passed\n")

    # Step 7: Print structure
    print("🌳 Step 7: Visualizing structure...\n")
    print_chain()

    print("\n" + "=" * 80)
    print("✅ COMMISSION TEST DATABASE READY!")
    print("=" * 80)
    print("\nTest chain:")
    for i, user_config in enumerate(TEST_CHAIN):
        marker = "👑 " if user_config.get("is_root") else ""
        marker += "⭐ " if user_config["telegram_id"] >= 1000000 else ""
        active = "✅" if user_config["is_active"] else "❌"
        print(f"  Level {i}: {marker}{user_config['firstname']} ({user_config['rank']}) {active}")
    print("\n")


async def import_projects():
    """Import projects and options from Google Sheets."""
    result = await import_projects_and_options()

    if not result.get("success"):
        raise Exception(f"Import failed: {result.get('error_messages')}")

    logger.info(
        f"Imported: {result['projects']['added']} projects, "
        f"{result['options']['added']} options"
    )


async def create_test_chain():
    """Create linear test chain."""
    session = get_session()
    try:
        previous_user = None

        for user_config in TEST_CHAIN:
            # Determine referrer
            if user_config.get("is_root"):
                referrer_id = None
            else:
                referrer_id = previous_user.telegramID if previous_user else None

            # Create Telegram user object
            telegram_user = TelegramUser(
                id=user_config["telegram_id"],
                is_bot=False,
                first_name=user_config["firstname"],
                last_name=user_config.get("surname"),
                language_code="ru"
            )

            # Create user
            user = User.create_from_telegram_data(
                session=session,
                telegram_user=telegram_user,
                referrer_id=referrer_id
            )

            # Set properties
            user.surname = user_config.get("surname")
            user.email = user_config["email"]
            user.rank = user_config["rank"]
            user.isActive = user_config["is_active"]
            user.balanceActive = Decimal(str(user_config["balance"]))

            # Fix upline for root
            if user_config.get("is_root"):
                user.upline = user.telegramID

            # Set personalData
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
        logger.info(f"✓ Created {len(TEST_CHAIN)} users in linear chain")

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

        logger.info("✓ All chains valid, no orphans found")

    finally:
        session.close()


def print_chain():
    """Print linear chain."""
    session = get_session()
    try:
        walker = ChainWalker(session)
        root = session.query(User).filter_by(telegramID=526738615).first()

        def print_user(user, level=0):
            connector = "  " * level + ("└─ " if level > 0 else "")
            rank_display = f"[{user.rank}]"
            balance_display = f"${user.balanceActive}" if user.balanceActive > 0 else ""
            root_marker = "👑 " if walker.is_system_root(user) else ""
            real_marker = "⭐ " if user.telegramID >= 1000000 else ""
            active_marker = "✅" if user.isActive else "❌"

            print(
                f"{connector}{root_marker}{real_marker}{user.firstname} "
                f"(ID:{user.telegramID}) {active_marker} {rank_display} {balance_display}"
            )

            # Get children
            children = session.query(User).filter(User.upline == user.telegramID).all()
            children = [c for c in children if not walker.is_system_root(c)]

            for child in children:
                print_user(child, level + 1)

        print("\n" + "=" * 80)
        print("COMMISSION TEST CHAIN")
        print("=" * 80 + "\n")
        print_user(root)
        print("\n" + "=" * 80 + "\n")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
