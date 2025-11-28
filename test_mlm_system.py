"""
Comprehensive MLM System Test Suite.
Tests all MLM functionality against TZ specifications.

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

# User definitions with exact telegram IDs and ranks
USERS = {
    "ROOT": {
        "telegram_id": 1000,
        "firstname": "Root",
        "surname": "Director",
        "email": "root@test.com",
        "rank": "director",
        "is_active": True,
        "balance": Decimal("100000"),
        "upline_key": None,  # Self-referencing
    },
    "L1_A": {
        "telegram_id": 1001,
        "firstname": "L1_A",
        "surname": "Leadership",
        "email": "l1a@test.com",
        "rank": "leadership",
        "is_active": True,
        "balance": Decimal("10000"),
        "upline_key": "ROOT",
    },
    "L2_A": {
        "telegram_id": 1002,
        "firstname": "L2_A",
        "surname": "Growth",
        "email": "l2a@test.com",
        "rank": "growth",
        "is_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L1_A",
    },
    "L3_A": {
        "telegram_id": 1003,
        "firstname": "L3_A",
        "surname": "Builder_Inactive",
        "email": "l3a@test.com",
        "rank": "builder",
        "is_active": False,  # INACTIVE - for compression test
        "balance": Decimal("0"),
        "upline_key": "L2_A",
    },
    "L4_A": {
        "telegram_id": 1004,
        "firstname": "L4_A",
        "surname": "Start",
        "email": "l4a@test.com",
        "rank": "start",
        "is_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L3_A",
    },
    "BUYER_1": {
        "telegram_id": 1005,
        "firstname": "Buyer1",
        "surname": "Test",
        "email": "buyer1@test.com",
        "rank": "start",
        "is_active": True,
        "balance": Decimal("10000"),
        "upline_key": "L4_A",
    },
    "L2_B": {
        "telegram_id": 1006,
        "firstname": "L2_B",
        "surname": "Builder",
        "email": "l2b@test.com",
        "rank": "builder",
        "is_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L1_A",
    },
    "L3_B": {
        "telegram_id": 1007,
        "firstname": "L3_B",
        "surname": "Start",
        "email": "l3b@test.com",
        "rank": "start",
        "is_active": True,
        "balance": Decimal("10000"),
        "upline_key": "L2_B",
    },
    "L1_B": {
        "telegram_id": 1008,
        "firstname": "L1_B",
        "surname": "Director2",
        "email": "l1b@test.com",
        "rank": "director",
        "is_active": True,
        "balance": Decimal("10000"),
        "upline_key": "ROOT",
    },
    "L2_C": {
        "telegram_id": 1009,
        "firstname": "L2_C",
        "surname": "Start",
        "email": "l2c@test.com",
        "rank": "start",
        "is_active": True,
        "balance": Decimal("5000"),
        "upline_key": "L1_B",
    },
    "L1_C": {
        "telegram_id": 1010,
        "firstname": "L1_C",
        "surname": "Start",
        "email": "l1c@test.com",
        "rank": "start",
        "is_active": True,
        "balance": Decimal("5000"),
        "upline_key": "ROOT",
    },
    "BUYER_2": {
        "telegram_id": 1011,
        "firstname": "Buyer2",
        "surname": "Pioneer",
        "email": "buyer2@test.com",
        "rank": "start",
        "is_active": True,
        "balance": Decimal("10000"),
        "upline_key": "L1_C",
    },
}

# Map to store created users by key
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
    """Create a single user with exact specifications."""
    user = User()
    user.telegramID = data["telegram_id"]
    user.firstname = data["firstname"]
    user.surname = data["surname"]
    user.email = data["email"]
    user.rank = data["rank"]
    user.isActive = data["is_active"]
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


async def create_user_structure():
    """Create deterministic user structure."""
    print("\n👥 Creating user structure...")

    session = get_session()
    try:
        # Create users in order (ROOT first, then by dependency)
        order = [
            "ROOT", "L1_A", "L1_B", "L1_C",
            "L2_A", "L2_B", "L2_C",
            "L3_A", "L3_B",
            "L4_A",
            "BUYER_1", "BUYER_2"
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


def print_structure():
    """Print user structure tree."""
    print("\n🌳 USER STRUCTURE:")
    print("=" * 50)
    print("""
ROOT (Director 18%, active)
├── L1_A (Leadership 15%, active)
│   ├── L2_A (Growth 12%, active)
│   │   └── L3_A (Builder 8%, INACTIVE) ← compression test
│   │       └── L4_A (Start 4%, active)
│   │           └── BUYER_1 (Start 4%, active)
│   └── L2_B (Builder 8%, active)
│       └── L3_B (Start 4%, active) ← referral test
├── L1_B (Director 18%, active) ← 2nd Director branch
│   └── L2_C (Start 4%, active)
└── L1_C (Start 4%, active) ← pioneer test
    └── BUYER_2 (Start 4%, active)
    """)
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
    else:
        report.check("L4_A bonus exists", expected=True, actual=False)

    # Check L3_A (Builder 8%, INACTIVE) - should be compressed, $0
    bonus_l3a = get_bonus_for_user(purchase.purchaseID, "L3_A")
    if bonus_l3a:
        report.check_decimal(
            "L3_A (INACTIVE) commission = $0",
            expected=Decimal("0.00"),
            actual=bonus_l3a.bonusAmount
        )
        report.check(
            "L3_A marked as compressed",
            expected=1,
            actual=bonus_l3a.compressionApplied
        )
    else:
        report.check("L3_A bonus exists (even if $0)", expected=True, actual=False)

    # Check L2_A (Growth 12%) - gets 12%-4% = 8% (compression from L3_A included)
    bonus_l2a = get_bonus_for_user(purchase.purchaseID, "L2_A")
    if bonus_l2a:
        report.check_decimal(
            "L2_A (Growth 12%) commission with compression",
            expected=Decimal("80.00"),
            actual=bonus_l2a.bonusAmount
        )
    else:
        report.check("L2_A bonus exists", expected=True, actual=False)

    # Check L1_A (Leadership 15%) - gets 15%-12% = 3%
    bonus_l1a = get_bonus_for_user(purchase.purchaseID, "L1_A")
    if bonus_l1a:
        report.check_decimal(
            "L1_A (Leadership 15%) commission",
            expected=Decimal("30.00"),
            actual=bonus_l1a.bonusAmount
        )
    else:
        report.check("L1_A bonus exists", expected=True, actual=False)

    # Check ROOT (Director 18%) - gets 18%-15% = 3%
    bonus_root = get_bonus_for_user(purchase.purchaseID, "ROOT")
    if bonus_root:
        report.check_decimal(
            "ROOT (Director 18%) commission",
            expected=Decimal("30.00"),
            actual=bonus_root.bonusAmount
        )
    else:
        report.check("ROOT bonus exists", expected=True, actual=False)

    # Check total distributed = 18%
    total = sum(b.bonusAmount for b in differential_bonuses)
    report.check_decimal(
        "Total distributed = 18% of $1000",
        expected=Decimal("180.00"),
        actual=total
    )

    # Check all are pending (paid on 5th)
    pending_count = sum(1 for b in differential_bonuses if b.status == "pending")
    report.check(
        "All bonuses have status=pending",
        expected=len(differential_bonuses),
        actual=pending_count
    )

    report.end_scenario()


async def test_monthly_payments():
    """
    Test 2: Monthly Payments (5th of month).

    Set time to 5th and run processMonthlyPayments.
    All pending bonuses should become paid.
    PassiveBalance records should be created.
    User balancePassive should be updated.
    """
    report.start_scenario("Monthly Payments (5th of month)")

    session = get_session()
    try:
        # Count pending bonuses before
        pending_before = session.query(Bonus).filter_by(status="pending").count()
        report.check(
            "Pending bonuses exist before payment",
            expected=True,
            actual=pending_before > 0,
            details=f"Count: {pending_before}"
        )

        # Get L4_A balance before
        l4a_user = session.query(User).filter_by(
            telegramID=USERS["L4_A"]["telegram_id"]
        ).first()
        balance_before = l4a_user.balancePassive or Decimal("0")

    finally:
        session.close()

    # Set time to 5th of month
    timeMachine.setTime(datetime(2024, 12, 5, 0, 0, 0, tzinfo=timezone.utc))

    # Run scheduler tasks
    from background.mlm_scheduler import MLMScheduler

    session = get_session()
    try:
        # Manually call processMonthlyPayments
        scheduler = MLMScheduler(bot=None)
        await scheduler.processMonthlyPayments(session)
        session.commit()

        # Check pending bonuses after
        pending_after = session.query(Bonus).filter_by(status="pending").count()
        report.check(
            "No pending bonuses after payment",
            expected=0,
            actual=pending_after
        )

        # Check paid bonuses
        paid_differential = session.query(Bonus).filter(
            Bonus.status == "paid",
            Bonus.commissionType.in_(["differential", "global_pool", "system_compression"])
        ).count()
        report.check(
            "Differential/pool bonuses now have status=paid",
            expected=pending_before,
            actual=paid_differential
        )

        # Check PassiveBalance records created
        pb_count = session.query(PassiveBalance).filter(
            PassiveBalance.reason.like("bonus=%")
        ).count()
        report.check(
            "PassiveBalance records created",
            expected=True,
            actual=pb_count > 0,
            details=f"Count: {pb_count}"
        )

        # Check L4_A balance updated
        l4a_user = session.query(User).filter_by(
            telegramID=USERS["L4_A"]["telegram_id"]
        ).first()
        balance_after = l4a_user.balancePassive or Decimal("0")

        report.check(
            "L4_A balancePassive increased",
            expected=True,
            actual=balance_after > balance_before,
            details=f"Before: ${balance_before}, After: ${balance_after}"
        )

        report.check_decimal(
            "L4_A received $40",
            expected=Decimal("40.00"),
            actual=balance_after - balance_before
        )

    finally:
        session.close()

    # Reset time
    timeMachine.resetToRealTime()

    report.end_scenario()


async def test_grace_day():
    """
    Test 3: Grace Day Bonus (+5%).

    Set time to 1st of month.
    BUYER_2 purchases $1000.
    Should receive +5% = $50 in OPTIONS.
    """
    report.start_scenario("Grace Day Bonus (+5%)")

    # Set time to 1st of month
    timeMachine.setTime(datetime(2024, 12, 1, 10, 0, 0, tzinfo=timezone.utc))

    report.check(
        "Time Machine set to Grace Day",
        expected=True,
        actual=timeMachine.isGraceDay
    )

    # Create purchase on Grace Day
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

        # Check Purchase created for auto-buy
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
                "Investment bonus = 5% of $1000",
                expected=Decimal("50.00"),
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
    print("🧪 MLM SYSTEM TEST SUITE")
    print("=" * 60)
    print("\nThis will test all MLM functionality against TZ specifications.")
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