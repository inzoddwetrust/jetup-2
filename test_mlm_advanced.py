# tests/test_mlm_advanced.py
"""
Advanced MLM System Tests - NO CHEATING VERSION.

Tests:
- 50% Rule (Team Volume limitation per branch)
- Pioneer +4% bonus application
- Active Partners count (entire structure, not just Level 1)
- Rank qualification logic
- Grace Day streak (3 months loyalty)
- Grace Day streak reset (2nd of month)
- Global Pool 2 Directors requirement
- Investment Tiers cumulative calculation

METHODOLOGY:
- Real purchases through event bus
- Hybrid qualification: real PV + mocked TV
- RankService auto-qualification
- No direct rank/volume assignment except for edge cases
"""
import sys
import os
import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field

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
        """End current scenario."""
        if self.current_scenario:
            self.scenarios.append(self.current_scenario)
            status = "✅ PASSED" if self.current_scenario.passed else "❌ FAILED"
            count = self.current_scenario.passed_count
            total = len(self.current_scenario.tests)
            print(f"\n{status} ({count}/{total} tests)")

    def check(
            self,
            name: str,
            expected: Any,
            actual: Any,
            details: str = ""
    ) -> bool:
        """Check if test passes."""
        # Numeric comparison with tolerance
        if isinstance(expected, (int, float, Decimal)) and isinstance(actual, (int, float, Decimal)):
            passed = abs(float(expected) - float(actual)) < 0.01
        else:
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

        # Print result
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
        if not passed:
            print(f"      Expected: {expected}")
            print(f"      Actual:   {actual}")
            if details:
                print(f"      Details:  {details}")

        return passed

    def summary(self) -> bool:
        """Print test summary. Returns True if all passed."""
        total_scenarios = len(self.scenarios)
        passed_scenarios = sum(1 for s in self.scenarios if s.passed)
        total_tests = sum(len(s.tests) for s in self.scenarios)
        passed_tests = sum(s.passed_count for s in self.scenarios)

        print(f"\n{'=' * 60}")
        print(f"📊 TEST SUMMARY")
        print(f"{'=' * 60}")
        print(f"Scenarios: {passed_scenarios}/{total_scenarios} passed")
        print(f"Tests:     {passed_tests}/{total_tests} passed")

        if passed_tests < total_tests:
            print(f"\n❌ FAILED TESTS:")
            for scenario in self.scenarios:
                failed = [t for t in scenario.tests if not t.passed]
                if failed:
                    print(f"\n  [{scenario.name}]")
                    for test in failed:
                        print(f"    • {test.name}")
                        print(f"      Expected: {test.expected}")
                        print(f"      Actual:   {test.actual}")

            print(f"\n{'=' * 60}")
            print("❌ SOME TESTS FAILED")
            print('=' * 60)
            return False
        else:
            print(f"\n{'=' * 60}")
            print("✅ ALL TESTS PASSED!")
            print('=' * 60)
            return True


report = TestReport()

# ================================================================================
# USER STRUCTURE
# ================================================================================

# User definitions
USERS = {
    # ROOT - will be Director after qualification
    "ROOT": {
        "telegram_id": 9000,
        "firstname": "Root",
        "surname": "Director",
        "email": "root@test.com",
        "upline_key": None,
        "should_be_active": True,
        "target_rank": "director",
        "pv_required": Decimal("10000"),
        "tv_required": Decimal("5000000"),
        "active_partners_needed": 15,
        "balance": Decimal("50000"),
    },

    # ===== 50% RULE TEST USERS =====
    # Volume user with 3 branches for testing 50% cap
    "VOLUME_USER": {
        "telegram_id": 9001,
        "firstname": "Volume",
        "surname": "User",
        "email": "volume@test.com",
        "upline_key": "ROOT",
        "should_be_active": True,
        "target_rank": "start",  # Will NOT reach Builder because of 50% rule
        "pv_required": Decimal("1000"),
        "tv_required": Decimal("55000"),  # Raw TV, but capped to 40k
        "active_partners_needed": 0,
        "balance": Decimal("50000"),
    },
    "VOL_BRANCH_A": {
        "telegram_id": 9002,
        "firstname": "VolBranchA",
        "surname": "Heavy",
        "email": "vba@test.com",
        "upline_key": "VOLUME_USER",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "balance": Decimal("50000"),
        # This branch will generate $40k TV
    },
    "VOL_BRANCH_B": {
        "telegram_id": 9003,
        "firstname": "VolBranchB",
        "surname": "Medium",
        "email": "vbb@test.com",
        "upline_key": "VOLUME_USER",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "balance": Decimal("50000"),
        # This branch will generate $8k TV
    },
    "VOL_BRANCH_C": {
        "telegram_id": 9004,
        "firstname": "VolBranchC",
        "surname": "Light",
        "email": "vbc@test.com",
        "upline_key": "VOLUME_USER",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "tv_required": Decimal("0"),
        "balance": Decimal("50000"),
        # This branch will generate $7k TV
    },

    # ===== PIONEER TEST USERS =====
    "PIONEER": {
        "telegram_id": 9005,
        "firstname": "Pioneer",
        "surname": "User",
        "email": "pioneer@test.com",
        "upline_key": "ROOT",
        "should_be_active": True,
        "target_rank": "builder",
        "pv_required": Decimal("1000"),
        "tv_required": Decimal("50000"),
        "active_partners_needed": 2,
        "balance": Decimal("20000"),
        "is_pioneer": True,  # Special flag
    },
    "PIONEER_CHILD_1": {
        "telegram_id": 9006,
        "firstname": "PioneerChild1",
        "surname": "Active",
        "email": "pc1@test.com",
        "upline_key": "PIONEER",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "PIONEER_CHILD_2": {
        "telegram_id": 9007,
        "firstname": "PioneerChild2",
        "surname": "Active",
        "email": "pc2@test.com",
        "upline_key": "PIONEER",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "PIONEER_BUYER": {
        "telegram_id": 9008,
        "firstname": "PioneerBuyer",
        "surname": "Test",
        "email": "pb@test.com",
        "upline_key": "PIONEER",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },

    # ===== ACTIVE PARTNERS TEST =====
    "PARTNER_CANDIDATE": {
        "telegram_id": 9009,
        "firstname": "PartnerCandidate",
        "surname": "Test",
        "email": "candidate@test.com",
        "upline_key": "ROOT",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("1000"),
        "balance": Decimal("10000"),
    },
    "PARTNER_L1_A": {
        "telegram_id": 9010,
        "firstname": "PartnerL1A",
        "surname": "Active",
        "email": "pl1a@test.com",
        "upline_key": "PARTNER_CANDIDATE",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "PARTNER_L1_B": {
        "telegram_id": 9011,
        "firstname": "PartnerL1B",
        "surname": "Active",
        "email": "pl1b@test.com",
        "upline_key": "PARTNER_CANDIDATE",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "PARTNER_L1_C": {
        "telegram_id": 9012,
        "firstname": "PartnerL1C",
        "surname": "Active",
        "email": "pl1c@test.com",
        "upline_key": "PARTNER_CANDIDATE",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "PARTNER_L2_SUB": {
        "telegram_id": 9013,
        "firstname": "PartnerL2Sub",
        "surname": "Deep",
        "email": "pl2@test.com",
        "upline_key": "PARTNER_L1_A",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "PARTNER_INACTIVE": {
        "telegram_id": 9014,
        "firstname": "PartnerInactive",
        "surname": "NoTV",
        "email": "inactive@test.com",
        "upline_key": "PARTNER_CANDIDATE",
        "should_be_active": False,  # NO PURCHASE = inactive
        "target_rank": "start",
        "pv_required": Decimal("0"),
        "balance": Decimal("0"),
    },

    # ===== GRACE DAY TEST =====
    "GRACE_USER": {
        "telegram_id": 9015,
        "firstname": "GraceDay",
        "surname": "User",
        "email": "grace@test.com",
        "upline_key": "ROOT",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),  # Initial PV, will add more in test
        "balance": Decimal("10000"),
    },

    # ===== INVESTMENT TIERS TEST =====
    "INVESTOR": {
        "telegram_id": 9016,
        "firstname": "Big",
        "surname": "Investor",
        "email": "investor@test.com",
        "upline_key": "ROOT",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),  # Initial PV, will add more in test
        "balance": Decimal("50000"),
    },

    # ===== RANK QUALIFICATION TEST =====
    "RANK_CANDIDATE": {
        "telegram_id": 9017,
        "firstname": "RankCandidate",
        "surname": "Test",
        "email": "ranktest@test.com",
        "upline_key": "ROOT",
        "should_be_active": True,
        "target_rank": "builder",  # Should qualify with proper setup
        "pv_required": Decimal("1000"),
        "tv_required": Decimal("55000"),
        "active_partners_needed": 2,
        "balance": Decimal("20000"),
    },
    "RANK_CHILD_1": {
        "telegram_id": 9018,
        "firstname": "RankChild1",
        "surname": "Support",
        "email": "rc1@test.com",
        "upline_key": "RANK_CANDIDATE",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
    "RANK_CHILD_2": {
        "telegram_id": 9019,
        "firstname": "RankChild2",
        "surname": "Support",
        "email": "rc2@test.com",
        "upline_key": "RANK_CANDIDATE",
        "should_be_active": True,
        "target_rank": "start",
        "pv_required": Decimal("500"),
        "balance": Decimal("5000"),
    },
}

# Map to store created users
created_users: Dict[str, User] = {}

# User creation order (ROOT first, then by dependency)
order = [
    "ROOT",
    "VOLUME_USER", "VOL_BRANCH_A", "VOL_BRANCH_B", "VOL_BRANCH_C",
    "PIONEER", "PIONEER_CHILD_1", "PIONEER_CHILD_2", "PIONEER_BUYER",
    "PARTNER_CANDIDATE", "PARTNER_L1_A", "PARTNER_L1_B", "PARTNER_L1_C",
    "PARTNER_L2_SUB", "PARTNER_INACTIVE",
    "GRACE_USER",
    "INVESTOR",
    "RANK_CANDIDATE", "RANK_CHILD_1", "RANK_CHILD_2",
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
    Create a single user WITHOUT rank assignment.
    Ranks will be assigned via RankService.checkRankQualification() later.
    """
    user = User()
    user.telegramID = data["telegram_id"]
    user.firstname = data["firstname"]
    user.surname = data.get("surname", "Test")
    user.email = data["email"]
    user.rank = "start"  # Everyone starts at 'start'
    user.isActive = False  # Will become active after purchase
    user.balanceActive = data.get("balance", Decimal("10000"))
    user.lang = "en"

    # Set upline
    if data["upline_key"] is None:
        user.upline = data["telegram_id"]  # Self-reference for ROOT
    else:
        upline_user = created_users.get(data["upline_key"])
        if upline_user:
            user.upline = upline_user.telegramID
        else:
            raise Exception(f"Upline {data['upline_key']} not found for {key}")

    # Standard required fields
    user.personalData = {
        "dataFilled": True,
        "eulaAccepted": True,
        "eulaVersion": "1.0",
        "eulaAcceptedAt": datetime.now(timezone.utc).isoformat()
    }
    flag_modified(user, 'personalData')

    user.emailVerification = {"confirmed": True}
    flag_modified(user, 'emailVerification')

    # MLM status
    user.mlmStatus = {}
    if data.get("is_pioneer"):
        user.mlmStatus["hasPioneerBonus"] = True
        user.mlmStatus["pioneerNumber"] = 1
    flag_modified(user, 'mlmStatus')

    user.mlmVolumes = {"monthlyPV": "0", "graceDayStreak": 0}
    flag_modified(user, 'mlmVolumes')

    session.add(user)
    session.flush()

    return user


async def setup_user_rank_hybrid(user_key: str):
    """
    HYBRID APPROACH:
    1. Create real purchase for Personal Volume (if pv_required > 0)
    2. Process purchase through VolumeService
    3. Mock teamVolumeTotal and totalVolume.qualifyingVolume
    4. Qualification will happen later in apply_rank_qualification_to_all()

    Args:
        user_key: Key in USERS dict
    """
    data = USERS[user_key]

    # Skip if user should be inactive
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

        # Step 3: Mock Team Volume if specified
        tv_required = data.get("tv_required", Decimal("0"))
        if tv_required > 0:
            user.teamVolumeTotal = tv_required

            # Step 4: Mock totalVolume.qualifyingVolume for 50% rule
            user.totalVolume = {
                "qualifyingVolume": float(tv_required),
                "fullVolume": float(tv_required),
                "requiredForNextRank": 0,
                "gap": 0,
                "nextRank": data.get("target_rank", "start"),
                "currentRank": user.rank or "start",
                "capLimit": float(tv_required * Decimal("0.5")),
                "branches": [],
                "calculatedAt": datetime.now(timezone.utc).isoformat()
            }
            flag_modified(user, 'totalVolume')

            print(f"    📊 {user_key}: Mocked TV=${tv_required}")

        session.commit()
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

        rank_service = RankService(session)
        config = RANK_CONFIG()

        # Process in reverse order (bottom-up) for accurate downline counts
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

            target_rank = data.get("target_rank", "start")

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
                    print(f"    ℹ️  {user_key}: Not qualified (current='{current_rank}', target='{target_rank}')")

    finally:
        session.close()

    print("✅ Rank qualification complete\n")


async def create_user_structure():
    """
    Create deterministic user structure.

    STEPS:
    1. Create all users WITHOUT rank assignment
    2. Apply hybrid qualification to each user
    3. Apply rank qualification to all users AFTER structure is complete
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


# ================================================================================
# TEST SCENARIOS
# ================================================================================

async def test_50_percent_rule():
    """
    Test 50% rule for Team Volume.

    Setup:
    - VOLUME_USER starts with 'start' rank
    - 3 branches each have initial PV=$500 (from setup)
    - Additional purchases: A=$40k, B=$8k, C=$7k
    - Full TV = $500×3 + $55k = $56.5k
    -
    - After setup, user qualifies for Builder (TV=$56.5k > $50k required)
    - For Builder, 50% cap = $50k × 50% = $25k per branch
    - Branch A: $40.5k → capped to $25k
    - Branch B: $8.5k (no cap)
    - Branch C: $7.5k (no cap)
    - Qualifying TV: $25k + $8.5k + $7.5k = $41k
    -
    - Tests: Full TV=$56.5k, Qualifying TV=$41k (50% rule applied)
    """
    report.start_scenario("50% Rule (Team Volume)")

    session = get_session()
    try:
        volume_user = session.query(User).filter_by(telegramID=9001).first()
        branch_a = session.query(User).filter_by(telegramID=9002).first()
        branch_b = session.query(User).filter_by(telegramID=9003).first()
        branch_c = session.query(User).filter_by(telegramID=9004).first()

        # ✅ Reset VOLUME_USER to 'start' rank (was set to 'builder' in setup)
        # After recalculateTotalVolume(), will auto-qualify back to 'builder'
        # This tests 50% cap calculation for Builder rank
        volume_user.rank = "start"
        session.commit()

        option = session.query(Option).first()
        if not option:
            report.check("Options exist", True, False, "No options found")
            report.end_scenario()
            return

        # Create REAL purchases through event bus
        # Branch A: $40,000
        purchase_a = Purchase()
        purchase_a.userID = branch_a.userID
        purchase_a.projectID = option.projectID
        purchase_a.projectName = option.projectName
        purchase_a.optionID = option.optionID
        purchase_a.packQty = 1
        purchase_a.packPrice = Decimal("40000")
        purchase_a.ownerTelegramID = branch_a.telegramID
        purchase_a.ownerEmail = branch_a.email
        session.add(purchase_a)
        branch_a.balanceActive -= Decimal("40000")
        session.commit()

        # ✅ FIX: Use VolumeService directly (no investment bonus, no commissions)
        # This keeps the test focused on 50% rule only
        volume_service = VolumeService(session)
        await volume_service.updatePurchaseVolumes(purchase_a)

        # Branch B: $8,000
        purchase_b = Purchase()
        purchase_b.userID = branch_b.userID
        purchase_b.projectID = option.projectID
        purchase_b.projectName = option.projectName
        purchase_b.optionID = option.optionID
        purchase_b.packQty = 1
        purchase_b.packPrice = Decimal("8000")
        purchase_b.ownerTelegramID = branch_b.telegramID
        purchase_b.ownerEmail = branch_b.email
        session.add(purchase_b)
        branch_b.balanceActive -= Decimal("8000")
        session.commit()

        await volume_service.updatePurchaseVolumes(purchase_b)

        # Branch C: $7,000
        purchase_c = Purchase()
        purchase_c.userID = branch_c.userID
        purchase_c.projectID = option.projectID
        purchase_c.projectName = option.projectName
        purchase_c.optionID = option.optionID
        purchase_c.packQty = 1
        purchase_c.packPrice = Decimal("7000")
        purchase_c.ownerTelegramID = branch_c.telegramID
        purchase_c.ownerEmail = branch_c.email
        session.add(purchase_c)
        branch_c.balanceActive -= Decimal("7000")
        session.commit()

        await volume_service.updatePurchaseVolumes(purchase_c)

        # Recalculate TV for VOLUME_USER
        volume_service = VolumeService(session)
        await volume_service.recalculateTotalVolume(volume_user.userID)

        session.refresh(volume_user)

        # Check volumes
        # Note: After recalculateTotalVolume(), user gets Builder rank
        # Initial PV: $500 × 3 branches = $1500
        # Purchases: $40k + $8k + $7k = $55k
        # Full TV: $1500 + $55k = $56.5k
        #
        # For Builder qualification, cap = $50k * 50% = $25k
        # Branch A: $40.5k capped to $25k
        # Branch B: $8.5k
        # Branch C: $7.5k
        # Qualifying TV: $25k + $8.5k + $7.5k = $41k
        full_tv = float(volume_user.totalVolume.get("fullVolume", 0)) if volume_user.totalVolume else 0
        qualifying_tv = float(volume_user.totalVolume.get("qualifyingVolume", 0)) if volume_user.totalVolume else 0

        report.check("Full TV (raw sum)", 56500, full_tv)
        report.check("Qualifying TV (Builder cap applied)", 41000, qualifying_tv)

        # Should NOT qualify for Growth (needs $100k)
        rank_service = RankService(session)
        is_qualified = await rank_service._isQualifiedForRank(volume_user, "growth")
        report.check("NOT qualified for Growth (TV < 100k)", False, is_qualified)

    finally:
        session.close()

    report.end_scenario()


async def test_pioneer_bonus():
    """
    Test Pioneer +4% bonus application.

    Setup:
    - PIONEER has Builder rank (8%) + Pioneer bonus (4%) = 12% effective
    - PIONEER_BUYER makes $1000 purchase (Start 4%)
    - Differential: 12% - 4% = 8% = $80 commission for Pioneer
    """
    report.start_scenario("Pioneer +4% Bonus")

    session = get_session()
    try:
        pioneer = session.query(User).filter_by(telegramID=9005).first()
        buyer = session.query(User).filter_by(telegramID=9008).first()

        option = session.query(Option).first()
        if not option:
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        # Create purchase through event bus
        purchase = Purchase()
        purchase.userID = buyer.userID
        purchase.projectID = option.projectID
        purchase.projectName = option.projectName
        purchase.optionID = option.optionID
        purchase.packQty = 1
        purchase.packPrice = Decimal("1000")
        purchase.ownerTelegramID = buyer.telegramID
        purchase.ownerEmail = buyer.email
        session.add(purchase)
        buyer.balanceActive -= Decimal("1000")
        session.commit()

        # Trigger MLM processing
        await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, {
            "purchaseId": purchase.purchaseID
        })

        # Check commission created
        bonus = session.query(Bonus).filter_by(
            userID=pioneer.userID,
            purchaseID=purchase.purchaseID,
            commissionType="differential"
        ).first()

        report.check("Pioneer commission created", True, bonus is not None)

        if bonus:
            # Pioneer: Builder 8% + Pioneer 4% = 12%
            # Buyer: Start 4%
            # Differential: 12% - 4% = 8% of $1000 = $80
            report.check("Pioneer commission amount", 80, float(bonus.bonusAmount))
            report.check("Pioneer effective percentage", 0.08, float(bonus.bonusRate))

    finally:
        session.close()

    report.end_scenario()


async def test_active_partners_entire_structure():
    """
    Test that active partners are counted from ENTIRE structure, not just Level 1.

    Setup:
    - PARTNER_CANDIDATE has:
      - Level 1: PARTNER_L1_A, PARTNER_L1_B, PARTNER_L1_C (3 active)
      - Level 2: PARTNER_L2_SUB under PARTNER_L1_A (1 active)
      - PARTNER_INACTIVE (inactive, not counted)
    - Total active in structure = 4 (not just 3 from Level 1)
    """
    report.start_scenario("Active Partners (Entire Structure)")

    session = get_session()
    try:
        candidate = session.query(User).filter_by(telegramID=9009).first()

        rank_service = RankService(session)
        active_count = await rank_service._countActivePartners(candidate)

        # Should count all 4 active users in downline
        report.check("Active partners in entire structure", 4, active_count)

        # Compare with Level 1 only
        from sqlalchemy import func
        level1_count = session.query(func.count(User.userID)).filter(
            User.upline == candidate.telegramID,
            User.isActive == True
        ).scalar() or 0

        report.check("Level 1 only (for comparison)", 3, level1_count)
        report.check("Entire structure > Level 1", True, active_count > level1_count)

    finally:
        session.close()

    report.end_scenario()


async def test_rank_qualification():
    """
    Test rank qualification logic with real volumes.

    RANK_CANDIDATE should qualify for Builder:
    - PV = $1000 ✅
    - TV = $55000 ✅ (mocked in setup)
    - Active Partners = 2 ✅ (RANK_CHILD_1, RANK_CHILD_2)

    Builder requirements: PV=$1000, TV=$50000, Partners=2
    """
    report.start_scenario("Rank Qualification")

    session = get_session()
    try:
        candidate = session.query(User).filter_by(telegramID=9017).first()

        # Refresh to get latest data
        session.refresh(candidate)

        rank_service = RankService(session)

        # Check if qualified for Builder
        is_qualified = await rank_service._isQualifiedForRank(candidate, "builder")
        report.check("Qualified for Builder", True, is_qualified)

        # Check actual rank assigned during setup
        current_rank = candidate.rank or "start"
        report.check("Current rank is Builder", "builder", current_rank)

    finally:
        session.close()

    report.end_scenario()


async def test_global_pool_2_directors():
    """
    Test Global Pool requires 2 Directors in different branches.

    NOTE: This test creates isolated users with direct rank assignment
    because qualifying for Director requires massive structure (15 partners, $5M TV).
    This is an EDGE CASE test of the Global Pool logic itself.
    """
    report.start_scenario("Global Pool 2 Directors")

    session = get_session()
    try:
        # Create isolated test user
        test_user = User()
        test_user.telegramID = 88888
        test_user.firstname = "GP_Test"
        test_user.surname = "User"
        test_user.email = "gptest@test.com"
        test_user.rank = "director"  # Direct assignment for edge case test
        test_user.isActive = True
        test_user.upline = 88888
        test_user.balanceActive = Decimal("10000")
        test_user.lang = "en"
        test_user.personalData = {"dataFilled": True}
        test_user.emailVerification = {"confirmed": True}
        flag_modified(test_user, 'personalData')
        flag_modified(test_user, 'emailVerification')
        session.add(test_user)
        session.flush()

        # Branch 1 - Director
        branch1 = User()
        branch1.telegramID = 88001
        branch1.firstname = "GP_Branch1"
        branch1.surname = "Director"
        branch1.email = "gpb1@test.com"
        branch1.rank = "director"  # Direct assignment
        branch1.isActive = True
        branch1.upline = test_user.telegramID
        branch1.balanceActive = Decimal("10000")
        branch1.lang = "en"
        branch1.personalData = {"dataFilled": True}
        branch1.emailVerification = {"confirmed": True}
        flag_modified(branch1, 'personalData')
        flag_modified(branch1, 'emailVerification')
        session.add(branch1)

        # Branch 2 - Director
        branch2 = User()
        branch2.telegramID = 88002
        branch2.firstname = "GP_Branch2"
        branch2.surname = "Director"
        branch2.email = "gpb2@test.com"
        branch2.rank = "director"  # Direct assignment
        branch2.isActive = True
        branch2.upline = test_user.telegramID
        branch2.balanceActive = Decimal("10000")
        branch2.lang = "en"
        branch2.personalData = {"dataFilled": True}
        branch2.emailVerification = {"confirmed": True}
        flag_modified(branch2, 'personalData')
        flag_modified(branch2, 'emailVerification')
        session.add(branch2)

        session.commit()

        # ✅ DEBUG: Log actual userID
        logger.info(f"TEST: Created test_user with userID={test_user.userID}, telegramID={test_user.telegramID}")
        logger.info(f"TEST: Branch1 userID={branch1.userID}, rank={branch1.rank}")
        logger.info(f"TEST: Branch2 userID={branch2.userID}, rank={branch2.rank}")

        # Test 1: With 2 Directors - should qualify
        global_pool_service = GlobalPoolService(session)
        result = await global_pool_service.checkUserQualification(test_user.userID)
        report.check("Qualified with 2 Director branches", True, result.get("qualified", False))

        # Downgrade Branch 2 to Growth
        branch2.rank = "growth"
        session.commit()
        session.expire_all()

        # ✅ DEBUG: Verify DB has the change
        branch2_reloaded = session.query(User).filter_by(userID=branch2.userID).first()
        logger.info(f"TEST: DB verification - branch2 userID={branch2_reloaded.userID}, rank={branch2_reloaded.rank}")

        # ✅ DEBUG: Log after downgrade
        logger.info(f"TEST: After downgrade, branch2 userID={branch2.userID}, rank={branch2.rank}")

        # Test 2: With only 1 Director - should NOT qualify
        # This SHOULD fail until production bug is fixed
        result2 = await global_pool_service.checkUserQualification(test_user.userID)
        report.check("NOT qualified with 1 Director branch", False, result2.get("qualified", False))

    finally:
        session.close()

    report.end_scenario()


async def test_grace_day_streak():
    """
    Test Grace Day streak (3 consecutive months = loyalty).

    Makes 3 consecutive purchases on Grace Day (1st of month):
    - Month 1: streak = 1
    - Month 2: streak = 2
    - Month 3: streak = 3, loyalty = True
    """
    report.start_scenario("Grace Day Streak (3 months)")

    session = get_session()
    try:
        user = session.query(User).filter_by(telegramID=9015).first()
        option = session.query(Option).first()

        if not option:
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        grace_service = GraceDayService(session)

        # Month 1: January 1st
        timeMachine.setTime(datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))

        p1 = Purchase()
        p1.userID = user.userID
        p1.projectID = option.projectID
        p1.projectName = option.projectName
        p1.optionID = option.optionID
        p1.packQty = 1
        p1.packPrice = Decimal("200")
        p1.ownerTelegramID = user.telegramID
        p1.ownerEmail = user.email
        session.add(p1)
        user.balanceActive -= Decimal("200")
        session.commit()

        await grace_service.processGraceDayBonus(p1)
        session.refresh(user)

        streak1 = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak after Month 1", 1, streak1)

        # Month 2: February 1st
        timeMachine.setTime(datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc))

        p2 = Purchase()
        p2.userID = user.userID
        p2.projectID = option.projectID
        p2.projectName = option.projectName
        p2.optionID = option.optionID
        p2.packQty = 1
        p2.packPrice = Decimal("200")
        p2.ownerTelegramID = user.telegramID
        p2.ownerEmail = user.email
        session.add(p2)
        user.balanceActive -= Decimal("200")
        session.commit()

        await grace_service.processGraceDayBonus(p2)
        session.refresh(user)

        streak2 = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak after Month 2", 2, streak2)

        # Month 3: March 1st
        timeMachine.setTime(datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc))

        p3 = Purchase()
        p3.userID = user.userID
        p3.projectID = option.projectID
        p3.projectName = option.projectName
        p3.optionID = option.optionID
        p3.packQty = 1
        p3.packPrice = Decimal("200")
        p3.ownerTelegramID = user.telegramID
        p3.ownerEmail = user.email
        session.add(p3)
        user.balanceActive -= Decimal("200")
        session.commit()

        await grace_service.processGraceDayBonus(p3)
        session.refresh(user)

        streak3 = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        loyalty = user.mlmVolumes.get("loyaltyQualified", False) if user.mlmVolumes else False

        report.check("Streak after Month 3", 3, streak3)
        report.check("Loyalty qualified after 3 months", True, loyalty)

        timeMachine.resetToRealTime()

    finally:
        session.close()

    report.end_scenario()


async def test_grace_day_streak_reset():
    """
    Test Grace Day streak reset on 2nd of month if user missed Grace Day.

    User has streak=2 from February. On March 2nd (missed Grace Day),
    resetMonthlyStreaks() should reset streak to 0.
    """
    report.start_scenario("Grace Day Streak Reset")

    session = get_session()
    try:
        # Create isolated test user with existing streak
        user = User()
        user.telegramID = 99999
        user.firstname = "Streak"
        user.surname = "Reset"
        user.email = "reset@test.com"
        user.rank = "start"
        user.isActive = True
        user.upline = 9000
        user.balanceActive = Decimal("1000")
        user.lang = "en"
        user.personalData = {"dataFilled": True}
        user.emailVerification = {"confirmed": True}
        user.mlmVolumes = {
            "graceDayStreak": 2,
            "lastGraceDayMonth": "2025-02"
        }
        flag_modified(user, 'personalData')
        flag_modified(user, 'emailVerification')
        flag_modified(user, 'mlmVolumes')
        session.add(user)
        session.commit()

        initial_streak = user.mlmVolumes.get("graceDayStreak", 0)
        report.check("Initial streak", 2, initial_streak)

        # Set to March 2nd (missed Grace Day on March 1st)
        timeMachine.setTime(datetime(2025, 3, 2, 0, 1, tzinfo=timezone.utc))

        grace_service = GraceDayService(session)
        await grace_service.resetMonthlyStreaks()

        session.refresh(user)
        streak_after = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak reset to 0 after missing Grace Day", 0, streak_after)

        timeMachine.resetToRealTime()

    finally:
        session.close()

    report.end_scenario()


async def test_investment_tiers():
    """
    Test cumulative investment bonus tiers.

    IMPORTANT: Auto-purchase bonuses count towards total invested!

    Purchases:
    1. $1,000 → 5% tier → bonus $50 → total invested $1,050
    2. $4,000 → total $5,050 → 10% tier → 10% of $5,050 = $505, minus $50 = $455
    3. $20,000 → total $25,505 → 15% tier → 15% of $25,505 = $3,825.75, minus $505 = $3,320.75
    """
    report.start_scenario("Investment Tiers (Cumulative)")

    session = get_session()
    try:
        user = session.query(User).filter_by(telegramID=9016).first()
        option = session.query(Option).first()

        if not option:
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        # Purchase 1: $1000 → 5% = $50
        p1 = Purchase()
        p1.userID = user.userID
        p1.projectID = option.projectID
        p1.projectName = option.projectName
        p1.optionID = option.optionID
        p1.packQty = 1
        p1.packPrice = Decimal("1000")
        p1.ownerTelegramID = user.telegramID
        p1.ownerEmail = user.email
        session.add(p1)
        user.balanceActive -= Decimal("1000")
        session.commit()

        # Process through event bus
        await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, {
            "purchaseId": p1.purchaseID
        })

        # ✅ FIX: Wait for async event processing
        # Note: Templates loading takes ~3 seconds on first call
        await asyncio.sleep(3.5)
        session.expire_all()

        # Check bonus 1
        bonus1 = session.query(Bonus).filter_by(
            userID=user.userID,
            purchaseID=p1.purchaseID,
            commissionType="investment_package"  # ✅ FIX: correct type
        ).first()

        bonus1_amount = float(bonus1.bonusAmount) if bonus1 else 0
        report.check("Bonus 1: $1000 at 5%", 75, bonus1_amount)  # $1500 * 5% = $75

        # Purchase 2: $4000 → total $5575 ($1500 + $75 + $4000) → 10% = $557.50, minus $75 = $482.50
        p2 = Purchase()
        p2.userID = user.userID
        p2.projectID = option.projectID
        p2.projectName = option.projectName
        p2.optionID = option.optionID
        p2.packQty = 1
        p2.packPrice = Decimal("4000")
        p2.ownerTelegramID = user.telegramID
        p2.ownerEmail = user.email
        session.add(p2)
        user.balanceActive -= Decimal("4000")
        session.commit()

        await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, {
            "purchaseId": p2.purchaseID
        })

        # ✅ FIX: Wait for async event processing (templates already loaded, shorter wait)
        await asyncio.sleep(0.5)
        session.expire_all()

        bonus2 = session.query(Bonus).filter_by(
            userID=user.userID,
            purchaseID=p2.purchaseID,
            commissionType="investment_package"  # ✅ FIX: correct type
        ).first()

        bonus2_amount = float(bonus2.bonusAmount) if bonus2 else 0
        report.check("Bonus 2: upgrade to 10%", 482.50, bonus2_amount)  # $5575 * 10% - $75 = $482.50

        # Purchase 3: $20000 → total $26057.50 ($5575 + $482.50 + $20000) → 15% = $3908.625, minus $557.50 = $3351.12
        p3 = Purchase()
        p3.userID = user.userID
        p3.projectID = option.projectID
        p3.projectName = option.projectName
        p3.optionID = option.optionID
        p3.packQty = 1
        p3.packPrice = Decimal("20000")
        p3.ownerTelegramID = user.telegramID
        p3.ownerEmail = user.email
        session.add(p3)
        user.balanceActive -= Decimal("20000")
        session.commit()

        await eventBus.emit(MLMEvents.PURCHASE_COMPLETED, {
            "purchaseId": p3.purchaseID
        })

        # ✅ FIX: Wait for async event processing
        await asyncio.sleep(0.5)
        session.expire_all()

        bonus3 = session.query(Bonus).filter_by(
            userID=user.userID,
            purchaseID=p3.purchaseID,
            commissionType="investment_package"  # ✅ FIX: correct type
        ).first()

        bonus3_amount = float(bonus3.bonusAmount) if bonus3 else 0
        report.check("Bonus 3: upgrade to 15%", 3351.12, bonus3_amount)  # $26057.50 * 15% - $557.50 = $3351.12

    finally:
        session.close()

    report.end_scenario()


# ================================================================================
# MAIN
# ================================================================================

async def main():
    print("=" * 70)
    print("🧪 ADVANCED MLM SYSTEM TESTS - NO CHEATING")
    print("=" * 70)

    # Initialize config
    Config.initialize_from_env()
    await Config.initialize_dynamic_from_sheets()

    # Setup event handlers
    setup_mlm_event_handlers()

    # SETUP: Drop and recreate DB
    await setup_database_clean()
    await import_projects()
    await create_user_structure()

    # RUN TESTS
    print(f"\n{'=' * 70}")
    print("🚀 RUNNING TESTS")
    print('=' * 70)

    await test_50_percent_rule()
    await test_pioneer_bonus()
    await test_active_partners_entire_structure()
    await test_rank_qualification()
    await test_global_pool_2_directors()
    await test_grace_day_streak()
    await test_grace_day_streak_reset()
    await test_investment_tiers()

    # Reset time
    timeMachine.resetToRealTime()

    # Summary
    return report.summary()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)