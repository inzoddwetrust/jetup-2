"""
Comprehensive MLM System Test Suite - PHASE 2 FIX.
Tests all MLM functionality against TZ specifications.

FIXES:
- No manual rank assignment
- Hybrid approach: real PV purchases + mocked TV
- RankService auto-qualification based on requirements
- Proper inactive users (L3_A has no purchase = inactive)

Usage:
    python test_mlm_system.py

Features:
- Deterministic user structure (no randomness)
- Exact value verification
- All scenarios from TZ covered
- Detailed PASSED/FAILED report
"""

import sys
import os
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy.orm.attributes import flag_modified

from config import Config
from core.db import get_session, setup_database, drop_all_tables
from models import (
    User, Purchase, Bonus, ActiveBalance, PassiveBalance,
    Option, GlobalPool
)
from mlm_system.services.commission_service import CommissionService
from mlm_system.services.volume_service import VolumeService
from mlm_system.services.rank_service import RankService
from mlm_system.services.global_pool_service import GlobalPoolService
from mlm_system.services.grace_day_service import GraceDayService
from mlm_system.services.investment_bonus_service import InvestmentBonusService
from mlm_system.utils.time_machine import timeMachine
from mlm_system.events.event_bus import eventBus, MLMEvents
from mlm_system.events.setup import setup_mlm_event_handlers
from services.imports import import_projects_and_options

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress noisy loggers during tests
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('aiogram').setLevel(logging.WARNING)


# ================================================================================
# TEST RESULTS TRACKING
# ================================================================================

@dataclass
class TestResult:
    """Single test result."""
    name: str
    passed: bool
    expected: Any
    actual: Any
    details: str = ""


@dataclass
class ScenarioResult:
    """Scenario with multiple test results."""
    name: str
    tests: List[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.tests)

    @property
    def passed_count(self) -> int:
        return sum(1 for t in self.tests if t.passed)

    @property
    def failed_count(self) -> int:
        return sum(1 for t in self.tests if not t.passed)


class TestReport:
    """Collects and displays all test results."""

    def __init__(self):
        self.scenarios: List[ScenarioResult] = []
        self.current_scenario: Optional[ScenarioResult] = None

    def start_scenario(self, name: str):
        """Start a new test scenario."""
        self.current_scenario = ScenarioResult(name=name)
        print(f"\n{'=' * 60}")
        print(f"📋 SCENARIO: {name}")
        print('=' * 60)

    def end_scenario(self):
        """End current scenario and add to results."""
        if self.current_scenario:
            self.scenarios.append(self.current_scenario)
            status = "✅ PASSED" if self.current_scenario.passed else "❌ FAILED"
            print(f"\n{status} ({self.current_scenario.passed_count}/{len(self.current_scenario.tests)} tests)")

    def check(self, name: str, expected: Any, actual: Any, details: str = ""):
        """Add a test check."""
        passed = expected == actual
        result = TestResult(
            name=name,
            passed=passed,
            expected=expected,
            actual=actual,
            details=details
        )

        if self.current_scenario:
            self.current_scenario.tests.append(result)

        status = "✅" if passed else "❌"
        print(f"  {status} {name}")

        if not passed:
            print(f"      Expected: {expected}")
            print(f"      Actual:   {actual}")
            if details:
                print(f"      Details:  {details}")

        return passed

    def check_decimal(self, name: str, expected: Decimal, actual: Decimal,
                      tolerance: Decimal = Decimal("0.01")):
        """Check decimal values with tolerance."""
        diff = abs(expected - actual)
        passed = diff <= tolerance

        result = TestResult(
            name=name,
            passed=passed,
            expected=float(expected),
            actual=float(actual),
            details=f"Difference: {float(diff)}"
        )

        if self.current_scenario:
            self.current_scenario.tests.append(result)

        status = "✅" if passed else "❌"
        print(f"  {status} {name}")

        if not passed:
            print(f"      Expected: ${expected}")
            print(f"      Actual:   ${actual}")
            print(f"      Diff:     ${diff}")

        return passed

    def print_summary(self):
        """Print final test summary."""
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)

        total_tests = sum(len(s.tests) for s in self.scenarios)
        passed_tests = sum(s.passed_count for s in self.scenarios)
        failed_tests = total_tests - passed_tests

        passed_scenarios = sum(1 for s in self.scenarios if s.passed)
        failed_scenarios = len(self.scenarios) - passed_scenarios

        print(f"\nScenarios: {passed_scenarios}/{len(self.scenarios)} passed")
        print(f"Tests:     {passed_tests}/{total_tests} passed")

        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS:")
            for scenario in self.scenarios:
                for test in scenario.tests:
                    if not test.passed:
                        print(f"  • [{scenario.name}] {test.name}")
                        print(f"    Expected: {test.expected}")
                        print(f"    Actual:   {test.actual}")

        print("\n" + "=" * 60)
        if failed_tests == 0:
            print("✅ ALL TESTS PASSED!")
        else:
            print(f"❌ {failed_tests} TESTS FAILED")
        print("=" * 60 + "\n")

        return failed_tests == 0


# Global test report
report = TestReport()

# ================================================================================
# DETERMINISTIC USER STRUCTURE
# ================================================================================

# User definitions with exact telegram IDs and target ranks
# PHASE 2 FIX: Added pv_required, tv_required for hybrid qualification
USERS = {
    "ROOT": {
        "telegram_id": 1000,
        "firstname": "Root",
        "surname": "Director",
        "email": "root@test.com",
        "target_rank": "director",
        "should_be_active": True,
        "balance": Decimal("100000"),
        "upline_key": None,  # Self-referencing
        # Hybrid qualification requirements (FROM ranks.py - DO NOT CHANGE FOR TESTS!)
        "pv_required": Decimal("10000"),      # Director PV requirement
        "tv_required": Decimal("5000000"),    # Director TV requirement (mocked)
        "active_partners_needed": 15,         # Director requirement - REAL VALUE FROM PRODUCTION!
    },
    "L1_A": {
        "telegram_id": 1001,
        "firstname": "L1_A",
        "surname": "Leadership",
        "email": "l1a@test.com",
        "target_rank": "leadership",
        "should_be_active": True,
        "balance": Decimal("10000"),
        "upline_key": "ROOT",
        # Leadership requirements (FROM ranks.py - DO NOT CHANGE FOR TESTS!)
        "pv_required": Decimal("5000"),
        "tv_required": Decimal("1000000"),
        "active_partners_needed": 10,  # REAL PRODUCTION VALUE
    },
    "L2_A": {
        "telegram_id": 1002,
        "firstname": "L2_A",
        "surname": "Growth",
        "email": "l2a@test.com",
        "target_rank": "growth",
        "should_be_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L1_A",
        # Growth requirements (FROM ranks.py - DO NOT CHANGE FOR TESTS!)
        "pv_required": Decimal("2500"),
        "tv_required": Decimal("250000"),
        "active_partners_needed": 5,  # REAL PRODUCTION VALUE
    },
    "L3_A": {
        "telegram_id": 1003,
        "firstname": "L3_A",
        "surname": "Builder_Inactive",
        "email": "l3a@test.com",
        "target_rank": "builder",
        "should_be_active": False,  # ✅ INACTIVE - for compression test
        "balance": Decimal("0"),
        "upline_key": "L2_A",
        # NO PURCHASE for this user - will remain inactive
        "pv_required": Decimal("0"),     # ✅ No purchase = inactive
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L4_A": {
        "telegram_id": 1004,
        "firstname": "L4_A",
        "surname": "Start",
        "email": "l4a@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L3_A",
        # Start requirements
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "BUYER_1": {
        "telegram_id": 1005,
        "firstname": "Buyer1",
        "surname": "Test",
        "email": "buyer1@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("10000"),
        "upline_key": "L4_A",
        # Start requirements
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L2_B": {
        "telegram_id": 1006,
        "firstname": "L2_B",
        "surname": "Builder",
        "email": "l2b@test.com",
        "target_rank": "builder",
        "should_be_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L1_A",
        # Builder requirements (FROM ranks.py - DO NOT CHANGE FOR TESTS!)
        "pv_required": Decimal("1000"),
        "tv_required": Decimal("50000"),
        "active_partners_needed": 2,  # REAL PRODUCTION VALUE
    },
    "L3_B": {
        "telegram_id": 1007,
        "firstname": "L3_B",
        "surname": "Start",
        "email": "l3b@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("10000"),
        "upline_key": "L2_B",
        # Start requirements
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L1_B": {
        "telegram_id": 1008,
        "firstname": "L1_B",
        "surname": "Director2",
        "email": "l1b@test.com",
        "target_rank": "director",
        "should_be_active": True,
        "balance": Decimal("10000"),
        "upline_key": "ROOT",
        # Director requirements (FROM ranks.py - DO NOT CHANGE FOR TESTS!)
        "pv_required": Decimal("10000"),
        "tv_required": Decimal("5000000"),
        "active_partners_needed": 15,  # REAL PRODUCTION VALUE
    },
    "L2_C": {
        "telegram_id": 1009,
        "firstname": "L2_C",
        "surname": "Start",
        "email": "l2c@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L1_B",
        # Start requirements
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L1_C": {
        "telegram_id": 1010,
        "firstname": "L1_C",
        "surname": "Start",
        "email": "l1c@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("5000"),
        "upline_key": "ROOT",
        # Start requirements
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "BUYER_2": {
        "telegram_id": 1011,
        "firstname": "Buyer2",
        "surname": "Pioneer",
        "email": "buyer2@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("10000"),
        "upline_key": "L1_C",
        # Start requirements
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    # Additional users to meet active partners requirements
    "L4_B": {
        "telegram_id": 1012,
        "firstname": "L4_B",
        "surname": "Start",
        "email": "l4b@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L3_B",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L3_C": {
        "telegram_id": 1013,
        "firstname": "L3_C",
        "surname": "Start",
        "email": "l3c@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L2_C",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L2_D": {
        "telegram_id": 1014,
        "firstname": "L2_D",
        "surname": "Start",
        "email": "l2d@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L1_C",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L3_D": {
        "telegram_id": 1015,
        "firstname": "L3_D",
        "surname": "Start",
        "email": "l3d@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L2_B",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L4_C": {
        "telegram_id": 1016,
        "firstname": "L4_C",
        "surname": "Start",
        "email": "l4c@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L2_A",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L5_A": {
        "telegram_id": 1017,
        "firstname": "L5_A",
        "surname": "Start",
        "email": "l5a@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L4_A",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L4_D": {
        "telegram_id": 1018,
        "firstname": "L4_D",
        "surname": "Start",
        "email": "l4d@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L3_B",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
    "L4_E": {
        "telegram_id": 1019,
        "firstname": "L4_E",
        "surname": "Start",
        "email": "l4e@test.com",
        "target_rank": "start",
        "should_be_active": True,
        "balance": Decimal("1000"),
        "upline_key": "L2_A",  # ✅ Direct child of L2_A for 5th active partner
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "active_partners_needed": 0,
    },
}

# Map to store created users by key
created_users: Dict[str, User] = {}

# User creation order (ROOT first, then by dependency)
order = [
    "ROOT", "L1_A", "L1_B", "L1_C",
    "L2_A", "L2_B", "L2_C", "L2_D",
    "L3_A", "L3_B", "L3_C", "L3_D",
    "L4_A", "L4_B", "L4_C", "L4_D", "L4_E",
    "L5_A",
    "BUYER_1", "BUYER_2"
]


# ================================================================================
# SETUP FUNCTIONS
# ================================================================================

async def setup_database_clean():
    """Drop and recreate database."""
    print("\n🗑️  Dropping existing database...")
    drop_all_tables()
    print("✅ Database dropped")

    print("\n🏗️  Creating tables...")
    setup_database()
    print("✅ Tables created")


async def import_projects():
    """Import projects and options from Google Sheets."""
    print("\n📥 Importing projects from Google Sheets...")
    result = await import_projects_and_options()

    if not result.get("success"):
        raise Exception(f"Import failed: {result.get('error_messages')}")

    print(f"✅ Imported: {result['projects']['added']} projects, {result['options']['added']} options")


def create_user(session, key: str, data: dict) -> User:
    """
    Create a single user WITHOUT manual rank/isActive assignment.

    PHASE 2 FIX: Removed manual rank and isActive assignment.
    These will be set automatically via hybrid qualification.
    """
    user = User()
    user.telegramID = data["telegram_id"]
    user.firstname = data["firstname"]
    user.surname = data["surname"]
    user.email = data["email"]
    # ✅ REMOVED: user.rank = data["rank"]
    # ✅ REMOVED: user.isActive = data["is_active"]
    user.balanceActive = data["balance"]
    user.lang = "en"

    # Set upline
    if data["upline_key"] is None:
        # ROOT user - self-reference
        user.upline = data["telegram_id"]
    else:
        upline_user = created_users.get(data["upline_key"])
        if upline_user:
            user.upline = upline_user.telegramID
        else:
            raise Exception(f"Upline {data['upline_key']} not found for {key}")

    # Set required fields
    user.personalData = {
        "dataFilled": True,
        "eulaAccepted": True,
        "eulaVersion": "1.0",
        "eulaAcceptedAt": datetime.now(timezone.utc).isoformat()
    }
    flag_modified(user, 'personalData')

    user.emailVerification = {"confirmed": True}
    flag_modified(user, 'emailVerification')

    user.mlmStatus = {}
    flag_modified(user, 'mlmStatus')

    user.mlmVolumes = {"monthlyPV": "0", "totalPV": "0"}
    flag_modified(user, 'mlmVolumes')

    session.add(user)
    session.flush()

    return user


async def setup_user_rank_hybrid(user_key: str):
    """
    PHASE 2: Hybrid rank qualification approach.

    Steps:
    1. Create real purchase for Personal Volume (if pv_required > 0)
    2. Process purchase through VolumeService to update personalVolumeTotal
    3. Mock teamVolumeTotal directly (hybrid approach)
    4. Mock totalVolume.qualifyingVolume for 50% rule
    5. Let RankService check qualification and assign rank automatically

    Args:
        user_key: Key in USERS dict
    """
    data = USERS[user_key]

    # Skip if user should be inactive (no purchase needed)
    if not data["should_be_active"]:
        print(f"    ⏭️  {user_key}: Skipping (should be inactive)")
        return

    session = get_session()
    try:
        user = session.query(User).filter_by(
            telegramID=data["telegram_id"]
        ).first()

        if not user:
            print(f"    ❌ {user_key}: User not found in DB!")
            return

        # Step 1: Create purchase for Personal Volume (if needed)
        pv_required = data.get("pv_required", Decimal("0"))
        if pv_required > 0:
            option = session.query(Option).first()
            if not option:
                raise Exception("No options in database for purchase creation")

            # Create purchase
            purchase = Purchase()
            purchase.userID = user.userID
            purchase.projectID = option.projectID
            purchase.projectName = option.projectName
            purchase.optionID = option.optionID
            purchase.packQty = int(pv_required / Decimal(str(option.costPerShare)))
            purchase.packPrice = pv_required
            purchase.ownerTelegramID = user.telegramID
            purchase.ownerEmail = user.email

            session.add(purchase)

            # Deduct balance
            user.balanceActive -= pv_required

            # Create ActiveBalance record
            ab = ActiveBalance()
            ab.userID = user.userID
            ab.firstname = user.firstname
            ab.surname = user.surname
            ab.amount = -pv_required
            ab.status = 'done'
            ab.reason = f'purchase={purchase.purchaseID}'
            ab.link = ''
            ab.notes = 'Test purchase for rank qualification'
            session.add(ab)

            session.commit()  # Commit purchase first

            # Step 2: Process purchase through VolumeService
            volume_service = VolumeService(session)
            await volume_service.updatePurchaseVolumes(purchase)

            print(f"    💰 {user_key}: Created purchase ${pv_required} (PV)")

            # Refresh user to get updated volumes
            session.refresh(user)

        # Step 3: Mock Team Volume (HYBRID APPROACH)
        tv_required = data.get("tv_required", Decimal("0"))
        user.teamVolumeTotal = tv_required

        # Step 4: Mock totalVolume.qualifyingVolume for 50% rule
        # This is what RankService actually checks
        user.totalVolume = {
            "qualifyingVolume": float(tv_required),
            "fullVolume": float(tv_required),
            "requiredForNextRank": 0,
            "gap": 0,
            "nextRank": data["target_rank"],
            "currentRank": user.rank or "start",
            "capLimit": float(tv_required * Decimal("0.5")),
            "branches": [],
            "calculatedAt": datetime.now(timezone.utc).isoformat()
        }
        flag_modified(user, 'totalVolume')

        if tv_required > 0:
            print(f"    📊 {user_key}: Mocked TV=${tv_required}")

        session.commit()

        # Refresh user again after mocking volumes
        session.refresh(user)

        # Debug: check current state
        print(f"    🔍 {user_key}: PV={user.personalVolumeTotal}, TV={user.teamVolumeTotal}, isActive={user.isActive}")

    finally:
        session.close()


async def apply_rank_qualification_to_all():
    """
    Apply rank qualification to ALL users AFTER structure is created.
    Must be called AFTER create_user_structure() completes.
    """
    print("\n🎖️  Applying rank qualification to all users...")

    session = get_session()
    try:
        from mlm_system.services.rank_service import RankService
        from mlm_system.config.ranks import RANK_CONFIG, Rank
        from mlm_system.utils.chain_walker import ChainWalker
        from sqlalchemy import func

        rank_service = RankService(session)
        config = RANK_CONFIG()

        # Process in reverse order (bottom-up) so downline counts are accurate
        for user_key in reversed(order):
            data = USERS[user_key]

            # Skip inactive users
            if not data["should_be_active"]:
                continue

            user = session.query(User).filter_by(
                telegramID=data["telegram_id"]
            ).first()

            if not user:
                continue

            # Debug: Show current state
            target_rank = data["target_rank"]

            # Get requirements
            try:
                rank_enum = Rank(target_rank)
                req = config.get(rank_enum, {})
            except ValueError:
                continue

            # Count active partners
            walker = ChainWalker(session)
            total_active = walker.count_active_downline(user)

            print(f"    🔍 {user_key}: PV={user.personalVolumeTotal}, TV={user.teamVolumeTotal}, "
                  f"active_partners={total_active} (need {req.get('activePartnersRequired', 0)})")

            # Check qualification
            new_rank = await rank_service.checkRankQualification(user.userID)

            if new_rank:
                success = await rank_service.updateUserRank(
                    user.userID,
                    new_rank,
                    method="natural"
                )
                if success:
                    session.commit()
                    print(f"    ✅ {user_key}: Qualified for rank '{new_rank}'")
                else:
                    print(f"    ⚠️  {user_key}: Qualification failed for '{new_rank}'")
            else:
                current_rank = user.rank or "start"
                if current_rank != target_rank:
                    print(f"    ❌ {user_key}: Not qualified (current='{current_rank}', target='{target_rank}')")

    finally:
        session.close()

    print("✅ Rank qualification complete\n")


async def create_user_structure():
    """
    Create deterministic user structure.

    PHASE 2 FIX:
    1. Create all users WITHOUT manual rank assignment
    2. Apply hybrid qualification to each user
    """
    print("\n👥 Creating user structure...")

    session = get_session()
    try:
        # Create users in order (ROOT first, then by dependency)
        for key in order:
            data = USERS[key]
            user = create_user(session, key, data)
            created_users[key] = user
            print(f"  Created: {key} (ID:{user.userID}, rank:{user.rank or 'start'})")

        session.commit()
        print(f"\n✅ Created {len(created_users)} users")

    finally:
        session.close()

    # PHASE 2: Apply hybrid qualification to each user
    print("\n🎯 Applying hybrid rank qualification...")

    for key in order:
        await setup_user_rank_hybrid(key)

    print("\n✅ Hybrid qualification complete")

    # PHASE 3: Apply rank qualification to ALL users (now that structure is complete)
    await apply_rank_qualification_to_all()


def print_structure():
    """Print user structure tree."""
    print("\n🌳 USER STRUCTURE:")
    print("=" * 50)

    # Refresh user data from DB to show actual ranks
    session = get_session()
    try:
        user_info = {}
        for key in USERS.keys():
            user = session.query(User).filter_by(
                telegramID=USERS[key]["telegram_id"]
            ).first()
            if user:
                user_info[key] = {
                    "rank": user.rank or "start",
                    "active": "✅" if user.isActive else "❌"
                }

        print(f"""
ROOT ({user_info.get('ROOT', {}).get('rank', 'start')}, {user_info.get('ROOT', {}).get('active', '❌')})
├── L1_A ({user_info.get('L1_A', {}).get('rank', 'start')}, {user_info.get('L1_A', {}).get('active', '❌')})
│   ├── L2_A ({user_info.get('L2_A', {}).get('rank', 'start')}, {user_info.get('L2_A', {}).get('active', '❌')})
│   │   ├── L3_A ({user_info.get('L3_A', {}).get('rank', 'start')}, {user_info.get('L3_A', {}).get('active', '❌')}) ← compression test
│   │   │   ├── L4_A ({user_info.get('L4_A', {}).get('rank', 'start')}, {user_info.get('L4_A', {}).get('active', '❌')})
│   │   │   │   ├── BUYER_1 ({user_info.get('BUYER_1', {}).get('rank', 'start')}, {user_info.get('BUYER_1', {}).get('active', '❌')})
│   │   │   │   └── L5_A ({user_info.get('L5_A', {}).get('rank', 'start')}, {user_info.get('L5_A', {}).get('active', '❌')})
│   │   ├── L4_C ({user_info.get('L4_C', {}).get('rank', 'start')}, {user_info.get('L4_C', {}).get('active', '❌')})
│   │   └── L4_E ({user_info.get('L4_E', {}).get('rank', 'start')}, {user_info.get('L4_E', {}).get('active', '❌')}) ← 5th partner for L2_A
│   └── L2_B ({user_info.get('L2_B', {}).get('rank', 'start')}, {user_info.get('L2_B', {}).get('active', '❌')})
│       ├── L3_B ({user_info.get('L3_B', {}).get('rank', 'start')}, {user_info.get('L3_B', {}).get('active', '❌')}) ← referral test
│       │   └── L4_B ({user_info.get('L4_B', {}).get('rank', 'start')}, {user_info.get('L4_B', {}).get('active', '❌')})
│       └── L3_D ({user_info.get('L3_D', {}).get('rank', 'start')}, {user_info.get('L3_D', {}).get('active', '❌')})
├── L1_B ({user_info.get('L1_B', {}).get('rank', 'start')}, {user_info.get('L1_B', {}).get('active', '❌')}) ← 2nd Director branch
│   └── L2_C ({user_info.get('L2_C', {}).get('rank', 'start')}, {user_info.get('L2_C', {}).get('active', '❌')})
│       └── L3_C ({user_info.get('L3_C', {}).get('rank', 'start')}, {user_info.get('L3_C', {}).get('active', '❌')})
└── L1_C ({user_info.get('L1_C', {}).get('rank', 'start')}, {user_info.get('L1_C', {}).get('active', '❌')}) ← pioneer test
    ├── BUYER_2 ({user_info.get('BUYER_2', {}).get('rank', 'start')}, {user_info.get('BUYER_2', {}).get('active', '❌')})
    │   └── L4_D ({user_info.get('L4_D', {}).get('rank', 'start')}, {user_info.get('L4_D', {}).get('active', '❌')})
    └── L2_D ({user_info.get('L2_D', {}).get('rank', 'start')}, {user_info.get('L2_D', {}).get('active', '❌')})
        """)
    finally:
        session.close()

    print("=" * 50)


# ================================================================================
# HELPER FUNCTIONS
# ================================================================================

def get_user(key: str) -> User:
    """Get user from DB by key."""
    session = get_session()
    try:
        telegram_id = USERS[key]["telegram_id"]
        return session.query(User).filter_by(telegramID=telegram_id).first()
    finally:
        session.close()


def get_user_by_id(user_id: int) -> User:
    """Get user from DB by userID."""
    session = get_session()
    try:
        return session.query(User).filter_by(userID=user_id).first()
    finally:
        session.close()


def get_option(project_id: int = 1) -> Option:
    """Get first option for project."""
    session = get_session()
    try:
        return session.query(Option).filter_by(projectID=project_id).first()
    finally:
        session.close()


async def create_purchase(buyer_key: str, amount: Decimal) -> Purchase:
    """Create a purchase and trigger MLM processing."""
    session = get_session()
    try:
        buyer = session.query(User).filter_by(
            telegramID=USERS[buyer_key]["telegram_id"]
        ).first()

        option = session.query(Option).first()
        if not option:
            raise Exception("No options in database")

        # Create purchase
        purchase = Purchase()
        purchase.userID = buyer.userID
        purchase.projectID = option.projectID
        purchase.projectName = option.projectName
        purchase.optionID = option.optionID
        purchase.packQty = int(amount / Decimal(str(option.costPerShare)))
        purchase.packPrice = amount
        purchase.ownerTelegramID = buyer.telegramID
        purchase.ownerEmail = buyer.email

        session.add(purchase)
        session.flush()

        # Deduct balance
        buyer.balanceActive -= amount

        # Create ActiveBalance record
        ab = ActiveBalance()
        ab.userID = buyer.userID
        ab.firstname = buyer.firstname
        ab.surname = buyer.surname
        ab.amount = -amount
        ab.status = 'done'
        ab.reason = f'purchase={purchase.purchaseID}'
        ab.link = ''
        ab.notes = 'Test purchase'
        session.add(ab)

        session.commit()

        purchase_id = purchase.purchaseID
        logger.info(f"Created purchase {purchase_id} for {buyer_key}: ${amount}")

    finally:
        session.close()

    # Emit event for MLM processing
    await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, {
        "purchaseId": purchase_id
    })

    # Wait for processing
    await asyncio.sleep(0.5)

    # Return fresh purchase object
    session = get_session()
    try:
        return session.query(Purchase).filter_by(purchaseID=purchase_id).first()
    finally:
        session.close()


def get_bonuses_for_purchase(purchase_id: int) -> List[Bonus]:
    """Get all bonuses for a purchase."""
    session = get_session()
    try:
        return session.query(Bonus).filter_by(purchaseID=purchase_id).all()
    finally:
        session.close()


def get_bonus_for_user(purchase_id: int, user_key: str) -> Optional[Bonus]:
    """Get bonus for specific user from purchase."""
    session = get_session()
    try:
        user = session.query(User).filter_by(
            telegramID=USERS[user_key]["telegram_id"]
        ).first()

        if not user:
            return None

        return session.query(Bonus).filter_by(
            purchaseID=purchase_id,
            userID=user.userID
        ).first()
    finally:
        session.close()


# ================================================================================
# TEST SCENARIOS
# ================================================================================

async def test_differential_commissions():
    """
    Test 1: Differential Commissions (basic case).

    BUYER_1 purchases $1000.
    Chain: BUYER_1 → L4_A → L3_A (inactive) → L2_A → L1_A → ROOT

    Expected:
    - L4_A (Start 4%):       4% - 0% = 4% = $40
    - L3_A (Builder 8%):     INACTIVE, compressed, $0
    - L2_A (Growth 12%):     12% - 4% = 8% = $80 (gets L3_A's 4% via compression)
    - L1_A (Leadership 15%): 15% - 12% = 3% = $30
    - ROOT (Director 18%):   18% - 15% = 3% = $30

    Total: $180 (18% of $1000)
    """
    report.start_scenario("Differential Commissions + Compression")

    # Create purchase
    purchase = await create_purchase("BUYER_1", Decimal("1000"))

    # Get bonuses
    bonuses = get_bonuses_for_purchase(purchase.purchaseID)

    # Check total count (should be 5: L4_A, L3_A, L2_A, L1_A, ROOT)
    # Note: L3_A gets $0 but still has a record
    differential_bonuses = [b for b in bonuses if b.commissionType in ("differential", "system_compression")]

    report.check(
        "Total differential/system bonus records",
        expected=5,
        actual=len(differential_bonuses)
    )

    # Check L4_A (Start 4%) - first upline, gets 4%
    bonus_l4a = get_bonus_for_user(purchase.purchaseID, "L4_A")
    if bonus_l4a:
        report.check_decimal(
            "L4_A (Start 4%) commission",
            expected=Decimal("40.00"),
            actual=bonus_l4a.bonusAmount
        )

    # Check L3_A (Builder 8%, INACTIVE) - should get $0
    bonus_l3a = get_bonus_for_user(purchase.purchaseID, "L3_A")
    if bonus_l3a:
        report.check_decimal(
            "L3_A (INACTIVE) commission = $0",
            expected=Decimal("0.00"),
            actual=bonus_l3a.bonusAmount
        )

    # Check L2_A (Growth 12%) - gets 12% - 4% = 8%
    bonus_l2a = get_bonus_for_user(purchase.purchaseID, "L2_A")
    if bonus_l2a:
        report.check_decimal(
            "L2_A (Growth 12%) commission",
            expected=Decimal("80.00"),
            actual=bonus_l2a.bonusAmount
        )

    # Check L1_A (Leadership 15%) - gets 15% - 12% = 3%
    bonus_l1a = get_bonus_for_user(purchase.purchaseID, "L1_A")
    if bonus_l1a:
        report.check_decimal(
            "L1_A (Leadership 15%) commission",
            expected=Decimal("30.00"),
            actual=bonus_l1a.bonusAmount
        )

    # Check ROOT (Director 18%) - gets 18% - 15% = 3%
    bonus_root = get_bonus_for_user(purchase.purchaseID, "ROOT")
    if bonus_root:
        report.check_decimal(
            "ROOT (Director 18%) commission",
            expected=Decimal("30.00"),
            actual=bonus_root.bonusAmount
        )

    # Check total commissions = 18% of $1000 = $180
    total = sum(b.bonusAmount for b in differential_bonuses)
    report.check_decimal(
        "Total differential commissions",
        expected=Decimal("180.00"),
        actual=total
    )

    report.end_scenario()


async def test_monthly_payments():
    """
    Test 2: Monthly Payments (5th of month).

    Bonuses are created with status='pending'.
    On 5th of month, processMonthlyPayments() should:
    - Create PassiveBalance records
    - Update user.balancePassive
    - Update Bonus.status = 'paid'
    """
    report.start_scenario("Monthly Payments (5th of month)")

    # Set time to 5th of month
    timeMachine.setTime(datetime(2025, 1, 5, 0, 0, 0, tzinfo=timezone.utc))

    session = get_session()
    try:
        # Get a bonus from previous test (any differential commission)
        bonus = session.query(Bonus).filter_by(
            commissionType="differential",
            status="pending"
        ).first()

        if not bonus:
            report.check(
                "Bonus exists from previous test",
                expected=True,
                actual=False,
                details="No pending differential bonus found"
            )
            return

        # Process monthly payments via MLMScheduler
        from background.mlm_scheduler import MLMScheduler
        scheduler = MLMScheduler(bot=None)
        await scheduler.processMonthlyPayments(session)

        session.commit()

        # Refresh bonus
        session.refresh(bonus)

        report.check(
            "Bonus status = paid",
            expected="paid",
            actual=bonus.status
        )

        # Check PassiveBalance created
        passive = session.query(PassiveBalance).filter_by(
            userID=bonus.userID,
            reason=f"bonus={bonus.bonusID}"
        ).first()

        report.check(
            "PassiveBalance record created",
            expected=True,
            actual=passive is not None
        )

    finally:
        session.close()

    # Reset time
    timeMachine.resetToRealTime()

    report.end_scenario()


async def test_grace_day():
    """
    Test 3: Grace Day Bonus (+5%).

    Set time to 1st of month (Grace Day).
    BUYER_2 purchases $1000.
    Grace Day bonus is processed automatically via event handler.
    Should receive +5% = $50 in OPTIONS.
    """
    report.start_scenario("Grace Day Bonus (+5%)")

    # Set time to 1st of month
    timeMachine.setTime(datetime(2025, 2, 1, 10, 0, 0, tzinfo=timezone.utc))

    report.check(
        "Time Machine set to Grace Day",
        expected=True,
        actual=timeMachine.isGraceDay
    )

    # Create purchase on Grace Day - bonus processed automatically
    purchase = await create_purchase("BUYER_2", Decimal("1000"))

    # Check for Grace Day bonus
    session = get_session()
    try:
        buyer2 = session.query(User).filter_by(
            telegramID=USERS["BUYER_2"]["telegram_id"]
        ).first()

        grace_bonus = session.query(Bonus).filter_by(
            userID=buyer2.userID,
            commissionType="grace_day"
        ).first()

        report.check(
            "Grace Day bonus record created",
            expected=True,
            actual=grace_bonus is not None
        )

        if grace_bonus:
            report.check_decimal(
                "Grace Day bonus = 5% of $1000",
                expected=Decimal("50.00"),
                actual=grace_bonus.bonusAmount
            )

            report.check(
                "Grace Day bonus status = paid (immediate)",
                expected="paid",
                actual=grace_bonus.status
            )

        # Check auto-purchase created for bonus
        auto_purchase = session.query(Purchase).filter(
            Purchase.userID == buyer2.userID,
            Purchase.purchaseID != purchase.purchaseID
        ).first()

        report.check(
            "Auto-purchase created for Grace Day bonus",
            expected=True,
            actual=auto_purchase is not None
        )

    finally:
        session.close()

    # Reset time
    timeMachine.resetToRealTime()

    report.end_scenario()

async def test_referral_bonus():
    """
    Test 4: Referral Bonus (1% for $5000+ purchase).

    L3_B purchases $5000.
    L2_B (direct upline) should receive 1% = $50 in OPTIONS.
    """
    report.start_scenario("Referral Bonus (1% for $5000+)")

    # Create $5000 purchase
    purchase = await create_purchase("L3_B", Decimal("5000"))

    session = get_session()
    try:
        l2b = session.query(User).filter_by(
            telegramID=USERS["L2_B"]["telegram_id"]
        ).first()

        # Check referral bonus
        referral_bonus = session.query(Bonus).filter_by(
            userID=l2b.userID,
            commissionType="referral"
        ).first()

        report.check(
            "Referral bonus record created",
            expected=True,
            actual=referral_bonus is not None
        )

        if referral_bonus:
            report.check_decimal(
                "Referral bonus = 1% of $5000",
                expected=Decimal("50.00"),
                actual=referral_bonus.bonusAmount
            )

            report.check(
                "Referral bonus status = paid (immediate)",
                expected="paid",
                actual=referral_bonus.status
            )

    finally:
        session.close()

    report.end_scenario()


async def test_pioneer_bonus():
    """
    Test 5: Pioneer Bonus Status.

    First 50 users with $5000+ purchase get Pioneer status.
    This grants +4% to future differential commissions.
    """
    report.start_scenario("Pioneer Bonus Status")

    session = get_session()
    try:
        # Check L3_B got pioneer status (from $5000 purchase in previous test)
        l3b = session.query(User).filter_by(
            telegramID=USERS["L3_B"]["telegram_id"]
        ).first()

        has_pioneer = (l3b.mlmStatus or {}).get("hasPioneerBonus", False)

        report.check(
            "L3_B has Pioneer status after $5000 purchase",
            expected=True,
            actual=has_pioneer
        )

        # Check pioneer count in root
        root = session.query(User).filter_by(
            telegramID=USERS["ROOT"]["telegram_id"]
        ).first()

        pioneer_count = (root.mlmStatus or {}).get("pioneerPurchasesCount", 0)

        report.check(
            "Pioneer counter incremented",
            expected=True,
            actual=pioneer_count >= 1,
            details=f"Count: {pioneer_count}"
        )

    finally:
        session.close()

    report.end_scenario()


async def test_global_pool():
    """
    Test 6: Global Pool Calculation.

    Set time to 3rd of month.
    Calculate Global Pool.
    ROOT should qualify (has 2 Director branches: self + L1_B).
    """
    report.start_scenario("Global Pool Calculation")

    # Set time to 3rd of month
    timeMachine.setTime(datetime(2025, 1, 3, 0, 0, 0, tzinfo=timezone.utc))

    session = get_session()
    try:
        pool_service = GlobalPoolService(session)
        result = await pool_service.calculateMonthlyPool()

        report.check(
            "Global Pool calculation succeeded",
            expected=True,
            actual=result.get("success", False),
            details=str(result)
        )

        # Check GlobalPool record
        pool = session.query(GlobalPool).filter_by(month="2025-01").first()

        report.check(
            "GlobalPool record created",
            expected=True,
            actual=pool is not None
        )

        if pool:
            report.check(
                "GlobalPool status = calculated",
                expected="calculated",
                actual=pool.status
            )

    finally:
        session.close()

    # Reset time
    timeMachine.resetToRealTime()

    report.end_scenario()


async def test_investment_tiers():
    """
    Test 7: Investment Package Tiers.

    Tier thresholds:
    - $1000+: 5% bonus
    - $2000+: 7% bonus
    - $5000+: 10% bonus

    Bonuses are in OPTIONS (auto-purchase).
    """
    report.start_scenario("Investment Package Tiers")

    # L2_C will make purchases to test tiers
    # First purchase: $1000 → 5% = $50
    purchase1 = await create_purchase("L2_C", Decimal("1000"))

    session = get_session()
    try:
        l2c = session.query(User).filter_by(
            telegramID=USERS["L2_C"]["telegram_id"]
        ).first()

        invest_bonus = session.query(Bonus).filter_by(
            userID=l2c.userID,
            commissionType="investment_package"
        ).first()

        report.check(
            "Investment bonus created for $1000",
            expected=True,
            actual=invest_bonus is not None
        )

        if invest_bonus:
            report.check_decimal(
                "Investment bonus = 5% of $1500 (cumulative: $500 setup + $1000 new)",
                expected=Decimal("75.00"),
                actual=invest_bonus.bonusAmount
            )

    finally:
        session.close()

    report.end_scenario()


# ================================================================================
# MAIN EXECUTION
# ================================================================================

async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("🧪 MLM SYSTEM TEST SUITE - PHASE 2")
    print("=" * 60)
    print("\nThis will test all MLM functionality against TZ specifications.")
    print("PHASE 2 FIX: Hybrid rank qualification (real PV + mocked TV)")
    print("Database will be DROPPED and recreated.\n")

    confirm = input("Type 'YES' to continue: ")
    if confirm != "YES":
        print("❌ Aborted.")
        return

    # Initialize
    print("\n📋 Initializing...")
    Config.initialize_from_env()

    # Load dynamic config from Google Sheets (RANK_CONFIG, etc.)
    print("\n📥 Loading dynamic configuration from Google Sheets...")
    await Config.initialize_dynamic_from_sheets()
    print("✅ Dynamic configuration loaded")

    # Override DEFAULT_REFERRER_ID for tests (our test ROOT has telegramID=1000)
    Config.set(Config.DEFAULT_REFERRER_ID, "1000")
    print("✅ DEFAULT_REFERRER_ID set to 1000 for tests")

    # Setup
    await setup_database_clean()
    await import_projects()
    await create_user_structure()
    print_structure()

    # Setup event handlers
    setup_mlm_event_handlers()

    # Run tests
    print("\n" + "=" * 60)
    print("🚀 RUNNING TESTS")
    print("=" * 60)

    try:
        await test_differential_commissions()
        await test_monthly_payments()
        await test_grace_day()
        await test_referral_bonus()
        await test_pioneer_bonus()
        await test_global_pool()
        await test_investment_tiers()
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()

    # Print summary
    all_passed = report.print_summary()

    # Exit code
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())