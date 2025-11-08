# scripts/populate_test_db.py
"""
Test database population script.
Creates realistic MLM structure for testing all scenarios.

Usage:
    python scripts/populate_test_db.py

WARNING: This will DROP and recreate the database!
"""

import sys
import os
import asyncio
import random
from decimal import Decimal
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from sqlalchemy.orm.attributes import flag_modified
from aiogram.types import User as TelegramUser
from config import Config
from core.db import get_engine, get_session, setup_database, drop_all_tables
from models.user import User
from mlm_system.utils.chain_walker import ChainWalker
from services.imports import import_projects_and_options

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ================================================================================
# CONFIGURATION
# ================================================================================

TEST_CONFIG = {
    "real_users": [
        {
            "telegram_id": 526738615,  # Артем (DEFAULT_REFERRER + ROOT)
            "firstname": "Артем",
            "surname": "Root",
            "email": "artem@test.com",
            "role": "root",
            "balance_active": 100000,
            "rank": "director"
        },
        {
            "telegram_id": 5971989877,  # Зодд
            "firstname": "Зодд",
            "surname": "Зверев",
            "email": "test1@test.com",
            "scenario": "investment_bonus",
            "balance_active": 10000
        },
        {
            "telegram_id": 334692878,  # Dennis
            "firstname": "Dennis",
            "surname": "Schymanietz",
            "email": "d.schymanietz+darwin8@gmail.com",
            "scenario": "rule_50_percent",
            "balance_active": 10000
        },
        {
            "telegram_id": 5130305756,  # Килл
            "firstname": "Балкно 2",
            "surname": "Второй",
            "email": "test2@test.com",
            "scenario": "investment_bonus",
            "balance_active": 10000
        },
        {
            "telegram_id": 884933951,  # Alexander
            "firstname": "Alexander",
            "surname": "Popp",
            "email": "invest.popp@gmail.com",
            "scenario": "rule_50_percent",
            "balance_active": 10000
        }
    ],

    "dummy_count": 20,
    "tree_depth_min": 3,
    "tree_depth_max": 7,
    "branches_per_user": [1, 2, 3],
}


# ================================================================================
# MAIN SCRIPT
# ================================================================================

async def main():
    """Main population script."""

    print("\n" + "=" * 80)
    print("🚨 TEST DATABASE POPULATION SCRIPT")
    print("=" * 80)
    print("\n⚠️  WARNING: This will DROP and recreate the entire database!")
    print("⚠️  All existing data will be LOST!")
    print("\n")

    confirm = input("Type 'YES' to continue: ")
    if confirm != "YES":
        print("❌ Aborted.")
        return

    print("\n🔄 Starting database population...\n")

    # STEP 1: Initialize config
    print("📋 Step 1: Loading configuration...")
    Config.initialize_from_env()
    print("✓ Configuration loaded\n")

    # STEP 2: Drop and recreate database
    print("💣 Step 2: Dropping existing database...")
    drop_all_tables()
    print("✓ Database dropped\n")

    print("🗂️  Step 3: Creating tables...")
    setup_database()
    print("✓ Tables created\n")

    # STEP 4: Import projects from Google Sheets
    print("📥 Step 4: Importing projects from Google Sheets...")
    await import_projects()
    print("✓ Projects imported\n")

    # STEP 5: Create DEFAULT_REFERRER (root)
    print("👑 Step 5: Creating DEFAULT_REFERRER (system root)...")
    root_user = await create_root_user()
    print(f"✓ Root created: userID={root_user.userID}, telegramID={root_user.telegramID}\n")

    # STEP 6: Create dummy users structure
    print("👥 Step 6: Creating dummy users structure...")
    dummy_telegram_ids = await create_dummy_structure(root_user)
    print(f"✓ Created {len(dummy_telegram_ids)} dummy users\n")

    # STEP 7: Place real users strategically
    print("⭐ Step 7: Placing real users in structure...")
    real_users_data = await place_real_users(dummy_telegram_ids)
    print(f"✓ Placed {len(real_users_data)} real users\n")

    # STEP 8: Validate chain integrity
    print("🔍 Step 8: Validating chain integrity...")
    await validate_chains()
    print("✓ Chain validation passed\n")

    # STEP 9: Print structure tree
    print("🌳 Step 9: Visualizing structure...\n")
    print_tree(root_user)

    print("\n" + "=" * 80)
    print("✅ DATABASE POPULATION COMPLETED!")
    print("=" * 80)
    print(f"\nReal users for testing:")
    for ru in real_users_data:
        print(f"  • {ru['firstname']} (ID: {ru['telegramID']}) - Balance: ${ru['balanceActive']}")
    print("\n")


# ================================================================================
# STEP IMPLEMENTATIONS
# ================================================================================

async def import_projects():
    """Import projects and options from Google Sheets."""
    result = await import_projects_and_options()

    if not result.get("success"):
        raise Exception(f"Import failed: {result.get('error_messages')}")

    logger.info(
        f"Imported: {result['projects']['added']} projects, "
        f"{result['options']['added']} options"
    )


async def create_root_user():
    """Create DEFAULT_REFERRER as system root."""
    session = get_session()
    try:
        default_ref_id = int(Config.get(Config.DEFAULT_REFERRER_ID))
        root_config = TEST_CONFIG["real_users"][0]

        telegram_user = TelegramUser(
            id=default_ref_id,
            is_bot=False,
            first_name=root_config["firstname"],
            last_name=root_config.get("surname"),
            language_code="ru"
        )

        root = User.create_from_telegram_data(
            session=session,
            telegram_user=telegram_user,
            referrer_id=None
        )

        # CRITICAL: Fix upline to self-reference for ROOT
        root.upline = root.telegramID
        root.surname = root_config.get("surname")
        root.email = root_config["email"]
        root.rank = root_config.get("rank", "director")
        root.balanceActive = Decimal(str(root_config["balance_active"]))

        # Set personalData with flag_modified
        root.personalData = {
            "dataFilled": True,
            "eulaAccepted": True,
            "eulaVersion": "1.0",
            "eulaAcceptedAt": datetime.now(timezone.utc).isoformat()
        }
        flag_modified(root, 'personalData')

        root.emailVerification = {"confirmed": True}
        flag_modified(root, 'emailVerification')

        root.mlmStatus = {"isFounder": True}
        flag_modified(root, 'mlmStatus')

        session.commit()
        session.refresh(root)

        logger.info(f"✓ Root user created: {root.userID} (upline={root.upline})")
        return root

    finally:
        session.close()


async def create_dummy_structure(root_user: User):
    """Create dummy users in tree structure."""
    session = get_session()
    try:
        dummies = []
        telegram_id_counter = 100000

        current_level = [root_user]

        for level in range(1, TEST_CONFIG["tree_depth_max"] + 1):
            next_level = []

            for parent in current_level:
                num_children = random.choice(TEST_CONFIG["branches_per_user"])

                for _ in range(num_children):
                    if len(dummies) >= TEST_CONFIG["dummy_count"]:
                        break

                    telegram_user = TelegramUser(
                        id=telegram_id_counter,
                        is_bot=False,
                        first_name=f"Dummy{telegram_id_counter}",
                        last_name=f"Level{level}",
                        language_code="en"
                    )

                    dummy = User.create_from_telegram_data(
                        session=session,
                        telegram_user=telegram_user,
                        referrer_id=parent.telegramID
                    )

                    dummy.email = f"dummy{dummy.userID}@test.com"

                    # 80% will be active
                    dummy.isActive = random.random() > 0.2
                    # If active, set rank randomly (for differential testing)
                    if dummy.isActive:
                        dummy.rank = random.choice(["start", "start", "builder", "growth"])
                    else:
                        dummy.rank = "start"

                    dummy.personalData = {
                        "dataFilled": True,
                        "eulaAccepted": True,
                        "eulaVersion": "1.0",
                        "eulaAcceptedAt": datetime.now(timezone.utc).isoformat()
                    }
                    flag_modified(dummy, 'personalData')

                    dummy.emailVerification = {"confirmed": True}
                    flag_modified(dummy, 'emailVerification')

                    dummies.append(dummy)
                    next_level.append(dummy)
                    telegram_id_counter += 1

                if len(dummies) >= TEST_CONFIG["dummy_count"]:
                    break

            if len(dummies) >= TEST_CONFIG["dummy_count"]:
                break

            current_level = next_level

            if not current_level:
                break

        session.commit()
        dummy_telegram_ids = [d.telegramID for d in dummies]

        # Log stats
        active_count = sum(1 for d in dummies if d.isActive)
        logger.info(
            f"✓ Created {len(dummies)} dummy users ({active_count} active, {len(dummies) - active_count} inactive)")

        return dummy_telegram_ids

    finally:
        session.close()


async def place_real_users(dummy_telegram_ids):
    """Place real users strategically in the structure."""
    session = get_session()
    try:
        real_users = []
        dummy_count = len(dummy_telegram_ids)

        for i, config in enumerate(TEST_CONFIG["real_users"][1:], start=1):
            # Distribute 4 real users across middle of dummy array
            if i == 1:
                parent_telegram_id = dummy_telegram_ids[dummy_count // 3]
            elif i == 2:
                parent_telegram_id = dummy_telegram_ids[dummy_count // 2]
            elif i == 3:
                parent_telegram_id = dummy_telegram_ids[(dummy_count * 2) // 3]
            elif i == 4:
                parent_telegram_id = dummy_telegram_ids[(dummy_count * 3) // 4]
            else:
                parent_telegram_id = random.choice(dummy_telegram_ids)

            telegram_user = TelegramUser(
                id=config["telegram_id"],
                is_bot=False,
                first_name=config["firstname"],
                last_name=config.get("surname"),
                language_code="ru"
            )

            real_user = User.create_from_telegram_data(
                session=session,
                telegram_user=telegram_user,
                referrer_id=parent_telegram_id
            )

            real_user.surname = config.get("surname")
            real_user.email = config["email"]
            real_user.balanceActive = Decimal(str(config["balance_active"]))

            # Set personalData with flag_modified
            real_user.personalData = {
                "dataFilled": True,
                "eulaAccepted": True,
                "eulaVersion": "1.0",
                "eulaAcceptedAt": datetime.now(timezone.utc).isoformat()
            }
            flag_modified(real_user, 'personalData')

            real_user.emailVerification = {"confirmed": True}
            flag_modified(real_user, 'emailVerification')

            real_users.append(real_user)

        session.commit()

        result = []
        for ru in real_users:
            result.append({
                "userID": ru.userID,
                "telegramID": ru.telegramID,
                "firstname": ru.firstname,
                "balanceActive": float(ru.balanceActive)
            })

        logger.info(f"✓ Placed {len(real_users)} real users")
        return result

    finally:
        session.close()


async def validate_chains():
    """Validate that all chains reach root correctly."""
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


def print_tree(root_user):
    """Print ASCII tree of the structure."""
    session = get_session()
    try:
        walker = ChainWalker(session)

        def print_user(user, prefix="", is_last=True):
            connector = "└─ " if is_last else "├─ "
            rank_display = f"[{user.rank}]" if user.rank != "start" else ""
            balance_display = f"${user.balanceActive}" if user.balanceActive > 0 else ""
            root_marker = "👑 " if walker.is_system_root(user) else ""
            real_marker = "⭐ " if user.telegramID in [u["telegram_id"] for u in TEST_CONFIG["real_users"]] else ""
            active_marker = "✅" if user.isActive else "❌"

            print(
                f"{prefix}{connector}{root_marker}{real_marker}{user.firstname} (ID:{user.telegramID}) {active_marker} {rank_display} {balance_display}"
            )

            children = session.query(User).filter(User.upline == user.telegramID).all()
            children = [c for c in children if not walker.is_system_root(c)]

            for i, child in enumerate(children):
                is_last_child = (i == len(children) - 1)
                new_prefix = prefix + ("    " if is_last else "│   ")
                print_user(child, new_prefix, is_last_child)

        print("\n" + "=" * 80)
        print("STRUCTURE TREE")
        print("=" * 80 + "\n")
        print_user(root_user)
        print("\n" + "=" * 80 + "\n")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())