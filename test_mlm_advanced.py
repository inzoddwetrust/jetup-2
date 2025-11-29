# tests/test_mlm_advanced.py
"""
Advanced MLM System Tests - DROPS DB AND RECREATES FROM SCRATCH.

Tests:
- 50% Rule (Team Volume limitation per branch)
- Pioneer +4% bonus application
- Rank qualification logic
- Grace Day streak (3 months loyalty)
- Grace Day streak reset (2nd of month)
- Global Pool 2 Directors requirement
- Investment Tiers cumulative calculation
- Active Partners count (entire structure)
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
from models import User, Purchase, Bonus, Option
from mlm_system.services.commission_service import CommissionService
from mlm_system.services.volume_service import VolumeService
from mlm_system.services.rank_service import RankService
from mlm_system.services.global_pool_service import GlobalPoolService
from mlm_system.services.grace_day_service import GraceDayService
from mlm_system.services.investment_bonus_service import InvestmentBonusService
from mlm_system.utils.time_machine import timeMachine
from services.imports import import_projects_and_options

import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


# ================================================================================
# TEST REPORT
# ================================================================================

@dataclass
class TestResult:
    name: str
    passed: bool
    expected: Any
    actual: Any


@dataclass
class ScenarioResult:
    name: str
    tests: List[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.tests)

    @property
    def passed_count(self) -> int:
        return sum(1 for t in self.tests if t.passed)


class TestReport:
    def __init__(self):
        self.scenarios: List[ScenarioResult] = []
        self.current_scenario: Optional[ScenarioResult] = None

    def start_scenario(self, name: str):
        self.current_scenario = ScenarioResult(name=name)
        print(f"\n{'=' * 60}")
        print(f"📋 SCENARIO: {name}")
        print('=' * 60)

    def end_scenario(self):
        if self.current_scenario:
            self.scenarios.append(self.current_scenario)
            status = "✅ PASSED" if self.current_scenario.passed else "❌ FAILED"
            print(f"\n{status} ({self.current_scenario.passed_count}/{len(self.current_scenario.tests)} tests)")

    def check(self, name: str, expected: Any, actual: Any) -> bool:
        if isinstance(expected, (int, float, Decimal)) and isinstance(actual, (int, float, Decimal)):
            passed = abs(float(expected) - float(actual)) < 0.01
        else:
            passed = expected == actual

        result = TestResult(name=name, passed=passed, expected=expected, actual=actual)
        if self.current_scenario:
            self.current_scenario.tests.append(result)

        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
        if not passed:
            print(f"      Expected: {expected}")
            print(f"      Actual:   {actual}")

        return passed

    def summary(self) -> bool:
        total_tests = sum(len(s.tests) for s in self.scenarios)
        passed_tests = sum(s.passed_count for s in self.scenarios)
        failed_tests = total_tests - passed_tests

        print(f"\n{'=' * 60}")
        print(f"📊 TEST SUMMARY")
        print(f"{'=' * 60}")
        print(f"Scenarios: {sum(1 for s in self.scenarios if s.passed)}/{len(self.scenarios)} passed")
        print(f"Tests:     {passed_tests}/{total_tests} passed")

        if failed_tests > 0:
            print(f"\n❌ FAILED TESTS:")
            for scenario in self.scenarios:
                for test in scenario.tests:
                    if not test.passed:
                        print(f"  • [{scenario.name}] {test.name}")
                        print(f"    Expected: {test.expected}")
                        print(f"    Actual:   {test.actual}")

        print("=" * 60)
        return failed_tests == 0


report = TestReport()

# ================================================================================
# USER STRUCTURE FOR ADVANCED TESTS
# ================================================================================

USERS = {
    # ROOT - Director at top
    "ROOT": {
        "telegram_id": 9000,
        "firstname": "Root",
        "rank": "director",
        "is_active": True,
        "upline_key": None,
    },
    # Branch A - Director (for Global Pool test)
    "BRANCH_A_DIRECTOR": {
        "telegram_id": 9001,
        "firstname": "BranchA_Dir",
        "rank": "director",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # Branch B - Director (for Global Pool test)
    "BRANCH_B_DIRECTOR": {
        "telegram_id": 9002,
        "firstname": "BranchB_Dir",
        "rank": "director",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # Branch C - Growth (NOT Director, for Global Pool negative test)
    "BRANCH_C_GROWTH": {
        "telegram_id": 9003,
        "firstname": "BranchC_Growth",
        "rank": "growth",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # Pioneer user with Builder rank
    "PIONEER": {
        "telegram_id": 9004,
        "firstname": "Pioneer_User",
        "rank": "builder",
        "is_active": True,
        "upline_key": "ROOT",
        "is_pioneer": True,
    },
    # Buyer under Pioneer
    "PIONEER_BUYER": {
        "telegram_id": 9005,
        "firstname": "Pioneer_Buyer",
        "rank": "start",
        "is_active": True,
        "upline_key": "PIONEER",
    },
    # Rank qualification candidate
    "RANK_CANDIDATE": {
        "telegram_id": 9006,
        "firstname": "Rank_Candidate",
        "rank": "start",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # Active partners for rank candidate (Level 1)
    "PARTNER_1": {
        "telegram_id": 9007,
        "firstname": "Partner_1",
        "rank": "start",
        "is_active": True,
        "upline_key": "RANK_CANDIDATE",
    },
    "PARTNER_2": {
        "telegram_id": 9008,
        "firstname": "Partner_2",
        "rank": "start",
        "is_active": True,
        "upline_key": "RANK_CANDIDATE",
    },
    "PARTNER_3": {
        "telegram_id": 9009,
        "firstname": "Partner_3",
        "rank": "start",
        "is_active": True,
        "upline_key": "RANK_CANDIDATE",
    },
    # Active partner on Level 2 (under Partner_1)
    "PARTNER_1_SUB": {
        "telegram_id": 9010,
        "firstname": "Partner_1_Sub",
        "rank": "start",
        "is_active": True,
        "upline_key": "PARTNER_1",
    },
    # Inactive partner (for counting test)
    "INACTIVE_PARTNER": {
        "telegram_id": 9011,
        "firstname": "Inactive_Partner",
        "rank": "start",
        "is_active": False,
        "upline_key": "RANK_CANDIDATE",
    },
    # Grace Day user
    "GRACE_USER": {
        "telegram_id": 9012,
        "firstname": "Grace_User",
        "rank": "start",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # Investment user
    "INVESTOR": {
        "telegram_id": 9013,
        "firstname": "Investor",
        "rank": "start",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # 50% Rule test - user with branches
    "VOLUME_USER": {
        "telegram_id": 9014,
        "firstname": "Volume_User",
        "rank": "start",
        "is_active": True,
        "upline_key": "ROOT",
    },
    # Branches for 50% rule test
    "VOL_BRANCH_A": {
        "telegram_id": 9015,
        "firstname": "Vol_Branch_A",
        "rank": "start",
        "is_active": True,
        "upline_key": "VOLUME_USER",
    },
    "VOL_BRANCH_B": {
        "telegram_id": 9016,
        "firstname": "Vol_Branch_B",
        "rank": "start",
        "is_active": True,
        "upline_key": "VOLUME_USER",
    },
    "VOL_BRANCH_C": {
        "telegram_id": 9017,
        "firstname": "Vol_Branch_C",
        "rank": "start",
        "is_active": True,
        "upline_key": "VOLUME_USER",
    },
}

created_users: Dict[str, User] = {}


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
    """Create a single user."""
    user = User()
    user.telegramID = data["telegram_id"]
    user.firstname = data["firstname"]
    user.surname = "Test"
    user.email = f"{data['firstname'].lower()}@test.com"
    user.rank = data["rank"]
    user.isActive = data["is_active"]
    user.balanceActive = Decimal("10000")
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
    if data.get("is_pioneer"):
        user.mlmStatus["hasPioneerBonus"] = True
        user.mlmStatus["pioneerNumber"] = 1
    flag_modified(user, 'mlmStatus')

    user.mlmVolumes = {"monthlyPV": "0", "graceDayStreak": 0}
    flag_modified(user, 'mlmVolumes')

    session.add(user)
    session.flush()

    return user


async def create_user_structure():
    """Create user structure."""
    print("\n👥 Creating user structure...")

    session = get_session()
    try:
        # Create in order (ROOT first, then dependents)
        order = [
            "ROOT",
            "BRANCH_A_DIRECTOR", "BRANCH_B_DIRECTOR", "BRANCH_C_GROWTH",
            "PIONEER", "PIONEER_BUYER",
            "RANK_CANDIDATE", "PARTNER_1", "PARTNER_2", "PARTNER_3",
            "PARTNER_1_SUB", "INACTIVE_PARTNER",
            "GRACE_USER", "INVESTOR",
            "VOLUME_USER", "VOL_BRANCH_A", "VOL_BRANCH_B", "VOL_BRANCH_C",
        ]

        for key in order:
            data = USERS[key]
            user = create_user(session, key, data)
            created_users[key] = user
            active_str = "✅" if data["is_active"] else "❌"
            print(f"  Created: {key} (ID:{user.userID}, rank:{user.rank}) {active_str}")

        session.commit()
        print(f"\n✅ Created {len(created_users)} users")

    finally:
        session.close()


# ================================================================================
# TEST SCENARIOS
# ================================================================================

async def test_50_percent_rule():
    """Test 50% rule for Team Volume."""
    report.start_scenario("50% Rule (Team Volume)")

    session = get_session()
    try:
        volume_user = session.query(User).filter_by(telegramID=9014).first()
        branch_a = session.query(User).filter_by(telegramID=9015).first()
        branch_b = session.query(User).filter_by(telegramID=9016).first()
        branch_c = session.query(User).filter_by(telegramID=9017).first()

        # Simulate purchases in branches
        option = session.query(Option).first()
        if not option:
            print("  ⚠️ No options - skipping purchase simulation")
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        # Create purchases: Branch A = $40k, Branch B = $8k, Branch C = $7k
        for buyer, amount in [(branch_a, 40000), (branch_b, 8000), (branch_c, 7000)]:
            purchase = Purchase()
            purchase.userID = buyer.userID
            purchase.projectID = option.projectID
            purchase.optionID = option.optionID
            purchase.packQty = 1
            purchase.packPrice = Decimal(str(amount))
            purchase.ownerTelegramID = buyer.telegramID
            session.add(purchase)

        session.commit()

        # Recalculate volumes
        volume_service = VolumeService(session)
        await volume_service.recalculateTotalVolume(volume_user.userID)

        session.refresh(volume_user)

        # Check qualifying volume
        # For Builder: requirement = 50k, 50% cap = 25k
        # Branch A (40k) -> capped to 25k
        # Total qualifying = 25k + 8k + 7k = 40k
        qualifying_tv = float(volume_user.totalVolume.get("qualifyingVolume", 0)) if volume_user.totalVolume else 0
        full_tv = float(volume_user.totalVolume.get("fullVolume", 0)) if volume_user.totalVolume else 0

        report.check("Full TV (raw sum)", 55000, full_tv)
        report.check("Qualifying TV (with 50% rule)", 40000, qualifying_tv)

        # Should NOT qualify for Builder (needs 50k)
        rank_service = RankService(session)
        is_qualified = await rank_service._isQualifiedForRank(volume_user, "builder")
        report.check("Not qualified for Builder (TV < 50k)", False, is_qualified)

    finally:
        session.close()

    report.end_scenario()


async def test_pioneer_bonus():
    """Test Pioneer +4% bonus to commissions."""
    report.start_scenario("Pioneer +4% Bonus")

    session = get_session()
    try:
        pioneer = session.query(User).filter_by(telegramID=9004).first()
        buyer = session.query(User).filter_by(telegramID=9005).first()

        option = session.query(Option).first()
        if not option:
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        # Create purchase
        purchase = Purchase()
        purchase.userID = buyer.userID
        purchase.projectID = option.projectID
        purchase.optionID = option.optionID
        purchase.packQty = 1
        purchase.packPrice = Decimal("1000")
        purchase.ownerTelegramID = buyer.telegramID
        session.add(purchase)
        session.commit()

        # Calculate commissions
        commission_service = CommissionService(session)
        commissions = await commission_service._calculateDifferentialCommissions(purchase)

        # Find Pioneer's commission
        pioneer_commission = None
        for c in commissions:
            if c["userId"] == pioneer.userID:
                pioneer_commission = c
                break

        report.check("Pioneer in commission list", True, pioneer_commission is not None)

        if pioneer_commission:
            # Pioneer: Builder (8%) + Pioneer bonus (4%) = 12%
            # Buyer: Start (4%)
            # Differential: 12% - 4% = 8% = $80
            report.check("Pioneer effective rate (8% + 4%)", 0.08, float(pioneer_commission.get("percentage", 0)))
            report.check("Pioneer commission amount", 80, float(pioneer_commission.get("amount", 0)))

    finally:
        session.close()

    report.end_scenario()


async def test_active_partners_entire_structure():
    """Test active partners counted from ENTIRE structure."""
    report.start_scenario("Active Partners (Entire Structure)")

    session = get_session()
    try:
        candidate = session.query(User).filter_by(telegramID=9006).first()

        rank_service = RankService(session)
        active_count = await rank_service._countActivePartners(candidate)

        # Expected: Partner_1, Partner_2, Partner_3, Partner_1_Sub = 4 active
        # Inactive_Partner is NOT counted
        report.check("Active partners in structure", 4, active_count)

        # Level 1 only would be 3 (not counting Partner_1_Sub)
        from sqlalchemy import func
        level1_count = session.query(func.count(User.userID)).filter(
            User.upline == candidate.telegramID,
            User.isActive == True
        ).scalar()
        report.check("Level 1 only (for comparison)", 3, level1_count)

        report.check("Entire structure > Level 1", True, active_count > level1_count)

    finally:
        session.close()

    report.end_scenario()


async def test_rank_qualification():
    """Test rank qualification logic."""
    report.start_scenario("Rank Qualification")

    session = get_session()
    try:
        candidate = session.query(User).filter_by(telegramID=9006).first()

        # Set qualifying TV manually
        candidate.totalVolume = {"qualifyingVolume": 55000, "fullVolume": 55000}
        flag_modified(candidate, 'totalVolume')
        session.commit()

        rank_service = RankService(session)

        # With TV=55k and 4 active partners, should qualify for Builder
        is_qualified = await rank_service._isQualifiedForRank(candidate, "builder")
        report.check("Qualified for Builder (TV=55k, partners=4)", True, is_qualified)

        # Lower TV - should NOT qualify
        candidate.totalVolume = {"qualifyingVolume": 30000, "fullVolume": 30000}
        flag_modified(candidate, 'totalVolume')
        session.commit()

        is_qualified_low = await rank_service._isQualifiedForRank(candidate, "builder")
        report.check("NOT qualified when TV < 50k", False, is_qualified_low)

    finally:
        session.close()

    report.end_scenario()


async def test_global_pool_2_directors():
    """Test Global Pool requires 2 Directors in different branches."""
    report.start_scenario("Global Pool 2 Directors")

    session = get_session()
    try:
        # Create isolated test user with exactly 2 branches
        test_user = User()
        test_user.telegramID = 88888
        test_user.firstname = "GlobalPool_Test"
        test_user.surname = "User"
        test_user.email = "gptest@test.com"
        test_user.rank = "director"
        test_user.isActive = True
        test_user.upline = 88888  # Self-reference
        session.add(test_user)
        session.flush()

        # Branch 1 - Director
        branch1 = User()
        branch1.telegramID = 88001
        branch1.firstname = "GP_Branch1"
        branch1.surname = "Director"
        branch1.email = "gpb1@test.com"
        branch1.rank = "director"
        branch1.isActive = True
        branch1.upline = test_user.telegramID
        session.add(branch1)

        # Branch 2 - Director (will be downgraded)
        branch2 = User()
        branch2.telegramID = 88002
        branch2.firstname = "GP_Branch2"
        branch2.surname = "Director"
        branch2.email = "gpb2@test.com"
        branch2.rank = "director"
        branch2.isActive = True
        branch2.upline = test_user.telegramID
        session.add(branch2)

        session.commit()

        global_pool_service = GlobalPoolService(session)

        # Test 1: With 2 Directors - should qualify
        result = await global_pool_service.checkUserQualification(test_user.userID)
        report.check("Qualified with 2 Director branches", True, result.get("qualified", False))

        # Downgrade Branch 2 to Growth
        branch2.rank = "growth"
        session.commit()
        session.expire_all()

        # Test 2: With only 1 Director - should NOT qualify
        result2 = await global_pool_service.checkUserQualification(test_user.userID)
        report.check("NOT qualified with 1 Director branch", False, result2.get("qualified", False))

    finally:
        session.close()

    report.end_scenario()


async def test_grace_day_streak():
    """Test Grace Day streak (3 months loyalty)."""
    report.start_scenario("Grace Day Streak (3 months)")

    session = get_session()
    try:
        user = session.query(User).filter_by(telegramID=9012).first()
        option = session.query(Option).first()

        if not option:
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        grace_service = GraceDayService(session)

        # Month 1
        timeMachine.setTime(datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))

        p1 = Purchase()
        p1.userID = user.userID
        p1.projectID = option.projectID
        p1.optionID = option.optionID
        p1.packQty = 1
        p1.packPrice = Decimal("200")
        p1.ownerTelegramID = user.telegramID
        session.add(p1)
        session.commit()

        await grace_service.processGraceDayBonus(p1)
        session.refresh(user)

        streak1 = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak after Month 1", 1, streak1)

        # Month 2
        timeMachine.setTime(datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc))

        p2 = Purchase()
        p2.userID = user.userID
        p2.projectID = option.projectID
        p2.optionID = option.optionID
        p2.packQty = 1
        p2.packPrice = Decimal("200")
        p2.ownerTelegramID = user.telegramID
        session.add(p2)
        session.commit()

        await grace_service.processGraceDayBonus(p2)
        session.refresh(user)

        streak2 = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak after Month 2", 2, streak2)

        # Month 3 - should qualify for loyalty
        timeMachine.setTime(datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc))

        p3 = Purchase()
        p3.userID = user.userID
        p3.projectID = option.projectID
        p3.optionID = option.optionID
        p3.packQty = 1
        p3.packPrice = Decimal("200")
        p3.ownerTelegramID = user.telegramID
        session.add(p3)
        session.commit()

        await grace_service.processGraceDayBonus(p3)
        session.refresh(user)

        streak3 = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak after Month 3", 3, streak3)

        loyalty = user.mlmVolumes.get("loyaltyQualified", False) if user.mlmVolumes else False
        report.check("Loyalty qualified", True, loyalty)

        timeMachine.resetToRealTime()

    finally:
        session.close()

    report.end_scenario()


async def test_grace_day_streak_reset():
    """Test Grace Day streak reset on 2nd of month."""
    report.start_scenario("Grace Day Streak Reset")

    session = get_session()
    try:
        # Create fresh user for this test
        user = User()
        user.telegramID = 99999
        user.firstname = "Reset_Test"
        user.surname = "User"
        user.email = "reset@test.com"
        user.rank = "start"
        user.isActive = True
        user.upline = 9000
        user.mlmVolumes = {"graceDayStreak": 2, "lastGraceDayMonth": "2025-02"}
        flag_modified(user, 'mlmVolumes')
        session.add(user)
        session.commit()

        report.check("Initial streak", 2, user.mlmVolumes.get("graceDayStreak", 0))

        # Set to 2nd of March (missed Grace Day)
        timeMachine.setTime(datetime(2025, 3, 2, 0, 1, tzinfo=timezone.utc))

        grace_service = GraceDayService(session)
        await grace_service.resetMonthlyStreaks()

        session.refresh(user)
        streak_after = user.mlmVolumes.get("graceDayStreak", 0) if user.mlmVolumes else 0
        report.check("Streak reset to 0", 0, streak_after)

        timeMachine.resetToRealTime()

    finally:
        session.close()

    report.end_scenario()


async def test_investment_tiers():
    """Test cumulative investment tiers.

    IMPORTANT: Auto-purchase bonuses count towards total invested!

    Tier thresholds:
    - $1,000 → 5%
    - $5,000 → 10%
    - $25,000 → 15%
    - $125,000 → 20%
    """
    report.start_scenario("Investment Tiers (Cumulative)")

    session = get_session()
    try:
        user = session.query(User).filter_by(telegramID=9013).first()
        option = session.query(Option).first()

        if not option:
            report.check("Options exist", True, False)
            report.end_scenario()
            return

        investment_service = InvestmentBonusService(session)

        # Purchase 1: $1000 → 5% tier = $50 bonus
        # Total after: $1000 + $50 (auto-purchase) = $1050
        p1 = Purchase()
        p1.userID = user.userID
        p1.projectID = option.projectID
        p1.optionID = option.optionID
        p1.packQty = 1
        p1.packPrice = Decimal("1000")
        p1.ownerTelegramID = user.telegramID
        session.add(p1)
        session.commit()

        bonus1 = await investment_service.processPurchaseBonus(p1)
        report.check("Bonus 1: $1000 at 5%", 50, float(bonus1) if bonus1 else 0)

        # Purchase 2: $4000
        # Total: $1050 + $4000 = $5050 → 10% tier
        # Expected: 10% of $5050 = $505, minus $50 already = $455
        # Total after: $5050 + $455 = $5505
        p2 = Purchase()
        p2.userID = user.userID
        p2.projectID = option.projectID
        p2.optionID = option.optionID
        p2.packQty = 1
        p2.packPrice = Decimal("4000")
        p2.ownerTelegramID = user.telegramID
        session.add(p2)
        session.commit()

        bonus2 = await investment_service.processPurchaseBonus(p2)
        report.check("Bonus 2: upgrade to 10%", 455, float(bonus2) if bonus2 else 0)

        # Purchase 3: $20000
        # Total: $5505 + $20000 = $25505 → 15% tier
        # Expected: 15% of $25505 = $3825.75, minus $505 already = $3320.75
        p3 = Purchase()
        p3.userID = user.userID
        p3.projectID = option.projectID
        p3.optionID = option.optionID
        p3.packQty = 1
        p3.packPrice = Decimal("20000")
        p3.ownerTelegramID = user.telegramID
        session.add(p3)
        session.commit()

        bonus3 = await investment_service.processPurchaseBonus(p3)
        report.check("Bonus 3: upgrade to 15%", 3320.75, float(bonus3) if bonus3 else 0)

    finally:
        session.close()

    report.end_scenario()


# ================================================================================
# MAIN
# ================================================================================

async def main():
    print("=" * 70)
    print("🧪 ADVANCED MLM SYSTEM TESTS")
    print("=" * 70)

    # Initialize config
    Config.initialize_from_env()
    await Config.initialize_dynamic_from_sheets()

    # SETUP: Drop and recreate DB
    await setup_database_clean()
    await import_projects()
    await create_user_structure()

    # RUN TESTS
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