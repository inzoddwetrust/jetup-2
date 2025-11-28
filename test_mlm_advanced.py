# tests/test_mlm_advanced.py
# FIXED VERSION - corrected model fields and method names
"""
Advanced MLM System Tests.

Tests for:
- 50% Rule (Team Volume limitation per branch)
- Pioneer +4% bonus application to commissions
- Rank qualification logic
- Grace Day streak (3 months loyalty)
- Grace Day streak reset (2nd of month)
- Global Pool 2 Directors requirement
- Investment Tiers ($1000, $5000, $25000, $125000)
- Cumulative Investment bonus calculation
- Active Partners count (entire structure via ChainWalker)
"""
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Optional, List, Dict

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# TEST REPORT CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class TestReport:
    """Tracks test results for a scenario."""

    def __init__(self, scenario_name: str):
        self.scenario_name = scenario_name
        self.checks: List[Dict] = []
        self.passed = 0
        self.failed = 0

    def check(self, name: str, expected, actual, tolerance: float = 0.01) -> bool:
        """Check if expected matches actual."""
        if isinstance(expected, (int, float, Decimal)) and isinstance(actual, (int, float, Decimal)):
            passed = abs(float(expected) - float(actual)) <= tolerance
        else:
            passed = expected == actual

        self.checks.append({
            'name': name,
            'expected': expected,
            'actual': actual,
            'passed': passed
        })

        if passed:
            self.passed += 1
            logger.info(f"  ✅ {name}")
        else:
            self.failed += 1
            logger.error(f"  ❌ {name}")
            logger.error(f"      Expected: {expected}")
            logger.error(f"      Actual:   {actual}")

        return passed

    def is_passed(self) -> bool:
        return self.failed == 0


# ═══════════════════════════════════════════════════════════════════════════════
# TEST SCENARIOS
# ═══════════════════════════════════════════════════════════════════════════════

async def test_50_percent_rule(session: Session) -> TestReport:
    """
    Test 50% Rule for Team Volume calculation.
    
    Scenario:
    - Partner needs 50,000$ TV for Builder rank
    - Branch A: 40,000$ (80% of requirement) → limited to 25,000$ (50%)
    - Branch B: 8,000$
    - Branch C: 7,000$
    
    Expected:
    - Qualifying TV = min(40000, 25000) + 8000 + 7000 = 40,000$
    - NOT qualified for Builder (needs 50,000$)
    """
    from models import User, Purchase
    from mlm_system.services.volume_service import VolumeService
    from mlm_system.services.rank_service import RankService
    from config import Config

    report = TestReport("50% Rule (Team Volume)")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: 50% Rule (Team Volume)")
    logger.info("=" * 60)

    # Create test user structure
    # ROOT → Branch A (40k), Branch B (8k), Branch C (7k)
    
    root = session.query(User).filter_by(telegramID=1000).first()
    if not root:
        logger.error("Root user not found, skipping test")
        report.check("Root user exists", True, False)
        return report

    # Get or create branch leaders (Level 1 under root)
    branch_a_leader = session.query(User).filter_by(telegramID=2001).first()
    branch_b_leader = session.query(User).filter_by(telegramID=2002).first()
    branch_c_leader = session.query(User).filter_by(telegramID=2003).first()

    if not all([branch_a_leader, branch_b_leader, branch_c_leader]):
        # Create branch leaders
        from models import User as UserModel
        
        for tg_id, name in [(2001, "BranchA"), (2002, "BranchB"), (2003, "BranchC")]:
            user = session.query(User).filter_by(telegramID=tg_id).first()
            if not user:
                user = User(
                    telegramID=tg_id,
                    firstname=name,
                    upline=root.telegramID,
                    isActive=True,
                    rank="start"
                )
                session.add(user)
        
        session.commit()
        
        branch_a_leader = session.query(User).filter_by(telegramID=2001).first()
        branch_b_leader = session.query(User).filter_by(telegramID=2002).first()
        branch_c_leader = session.query(User).filter_by(telegramID=2003).first()

    # Set branch volumes directly in totalVolume JSON for testing
    # Branch A: 40,000$ (будет ограничена 50% от 50k = 25k)
    # Branch B: 8,000$
    # Branch C: 7,000$
    
    root.totalVolume = {
        "branches": {
            str(branch_a_leader.userID): 40000,
            str(branch_b_leader.userID): 8000,
            str(branch_c_leader.userID): 7000
        },
        "totalTV": 55000,  # Raw total
        "qualifyingVolume": 40000  # After 50% rule: 25000 + 8000 + 7000
    }
    flag_modified(root, 'totalVolume')
    session.commit()

    # Test 1: Check qualifying volume calculation
    volume_service = VolumeService(session)
    
    # Recalculate volumes to verify 50% rule
    await volume_service.recalculateTotalVolume(root.userID)
    session.refresh(root)
    
    qualifying_tv = Decimal(str(root.totalVolume.get("qualifyingVolume", 0)))
    
    # For Builder rank: requirement is 50,000$
    # 50% limit = 25,000$
    # Branch A (40k) → limited to 25k
    # Total qualifying = 25k + 8k + 7k = 40k
    
    report.check(
        "Qualifying TV with 50% rule applied",
        expected=40000,
        actual=float(qualifying_tv),
        tolerance=100
    )

    # Test 2: Check rank qualification fails
    rank_service = RankService(session)
    is_qualified = await rank_service._isQualifiedForRank(root, "builder")
    
    report.check(
        "Not qualified for Builder (TV < 50k)",
        expected=False,
        actual=is_qualified
    )

    # Test 3: Now add more volume to other branches to qualify
    root.totalVolume = {
        "branches": {
            str(branch_a_leader.userID): 40000,
            str(branch_b_leader.userID): 15000,  # Increased
            str(branch_c_leader.userID): 12000   # Increased
        },
        "totalTV": 67000,
        "qualifyingVolume": 52000  # 25k + 15k + 12k = 52k
    }
    flag_modified(root, 'totalVolume')
    session.commit()
    
    await volume_service.recalculateTotalVolume(root.userID)
    session.refresh(root)
    
    qualifying_tv_new = Decimal(str(root.totalVolume.get("qualifyingVolume", 0)))
    
    report.check(
        "Qualifying TV after adding volume to other branches",
        expected=52000,
        actual=float(qualifying_tv_new),
        tolerance=100
    )

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_pioneer_bonus_applied(session: Session) -> TestReport:
    """
    Test Pioneer +4% bonus applied to differential commissions.
    
    Scenario:
    - Pioneer user with Builder rank (8%)
    - Effective percentage should be 8% + 4% = 12%
    - Purchase of $1000 in their downline
    - Pioneer should receive 12% commission instead of 8%
    """
    from models import User, Purchase, Bonus
    from mlm_system.services.commission_service import CommissionService
    from mlm_system.utils.time_machine import timeMachine

    report = TestReport("Pioneer +4% Bonus Application")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Pioneer +4% Bonus Application")
    logger.info("=" * 60)

    # Find or create Pioneer user
    pioneer = session.query(User).filter_by(telegramID=3001).first()
    if not pioneer:
        pioneer = User(
            telegramID=3001,
            firstname="Pioneer_User",
            upline=1000,  # Under root
            isActive=True,
            rank="builder",  # 8% base
            mlmStatus={
                "hasPioneerBonus": True,
                "pioneerNumber": 1,
                "pioneerQualifiedAt": datetime.now(timezone.utc).isoformat()
            }
        )
        session.add(pioneer)
        session.commit()
    else:
        # Ensure Pioneer status
        pioneer.rank = "builder"
        pioneer.isActive = True
        if not pioneer.mlmStatus:
            pioneer.mlmStatus = {}
        pioneer.mlmStatus["hasPioneerBonus"] = True
        pioneer.mlmStatus["pioneerNumber"] = 1
        flag_modified(pioneer, 'mlmStatus')
        session.commit()

    # Create buyer under Pioneer
    buyer = session.query(User).filter_by(telegramID=3002).first()
    if not buyer:
        buyer = User(
            telegramID=3002,
            firstname="Pioneer_Buyer",
            upline=pioneer.telegramID,
            isActive=True,
            rank="start"  # 4%
        )
        session.add(buyer)
        session.commit()

    # Create purchase
    purchase = Purchase(
        userID=buyer.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("1000"),
        packQty=1,
        
        
    )
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

    report.check(
        "Pioneer found in commission list",
        expected=True,
        actual=pioneer_commission is not None
    )

    if pioneer_commission:
        # Pioneer has Builder (8%) + Pioneer bonus (4%) = 12%
        # Buyer has Start (4%)
        # Differential = 12% - 4% = 8% = $80
        
        expected_percentage = Decimal("0.08")  # 8% differential (12% - 4%)
        expected_amount = Decimal("80")  # $1000 * 8%
        
        report.check(
            "Pioneer commission percentage (8% + 4% - 4% buyer)",
            expected=float(expected_percentage),
            actual=float(pioneer_commission.get("percentage", 0)),
            tolerance=0.001
        )
        
        report.check(
            "Pioneer commission amount",
            expected=float(expected_amount),
            actual=float(pioneer_commission.get("amount", 0)),
            tolerance=1
        )

    # Cleanup
    session.delete(purchase)
    session.commit()

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_rank_qualification(session: Session) -> TestReport:
    """
    Test rank qualification logic.
    
    Requirements for Builder:
    - Personal Volume: any (not required per TZ)
    - Team Volume: 50,000$ (with 50% rule)
    - Active Partners: 2 (in ENTIRE structure)
    
    Scenario:
    - User with 55,000$ TV (qualifies after 50% rule)
    - 3 active partners in downline
    - Should qualify for Builder
    """
    from models import User
    from mlm_system.services.rank_service import RankService

    report = TestReport("Rank Qualification")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Rank Qualification")
    logger.info("=" * 60)

    # Create test user with structure
    candidate = session.query(User).filter_by(telegramID=4001).first()
    if not candidate:
        candidate = User(
            telegramID=4001,
            firstname="Rank_Candidate",
            upline=1000,
            isActive=True,
            rank="start",
            totalVolume={
                "qualifyingVolume": 55000  # Above 50k requirement
            }
        )
        session.add(candidate)
        session.commit()
    else:
        candidate.rank = "start"
        candidate.isActive = True
        candidate.totalVolume = {"qualifyingVolume": 55000}
        flag_modified(candidate, 'totalVolume')
        session.commit()

    # Create active partners in downline
    for i, tg_id in enumerate([4002, 4003, 4004]):
        partner = session.query(User).filter_by(telegramID=tg_id).first()
        if not partner:
            partner = User(
                telegramID=tg_id,
                firstname=f"Partner_{i+1}",
                upline=candidate.telegramID,
                isActive=True,
                rank="start"
            )
            session.add(partner)
    
    session.commit()

    # Test qualification
    rank_service = RankService(session)
    
    # Count active partners
    active_count = await rank_service._countActivePartners(candidate)
    report.check(
        "Active partners count (entire structure)",
        expected=3,
        actual=active_count
    )

    # Check Builder qualification
    is_qualified = await rank_service._isQualifiedForRank(candidate, "builder")
    report.check(
        "Qualified for Builder rank",
        expected=True,
        actual=is_qualified
    )

    # Test NOT qualified when TV too low
    candidate.totalVolume = {"qualifyingVolume": 30000}
    flag_modified(candidate, 'totalVolume')
    session.commit()
    
    is_qualified_low_tv = await rank_service._isQualifiedForRank(candidate, "builder")
    report.check(
        "Not qualified when TV < 50k",
        expected=False,
        actual=is_qualified_low_tv
    )

    # Test NOT qualified when not enough active partners
    candidate.totalVolume = {"qualifyingVolume": 60000}
    flag_modified(candidate, 'totalVolume')
    
    # Deactivate partners
    for tg_id in [4002, 4003, 4004]:
        partner = session.query(User).filter_by(telegramID=tg_id).first()
        if partner:
            partner.isActive = False
    session.commit()
    
    is_qualified_no_partners = await rank_service._isQualifiedForRank(candidate, "builder")
    report.check(
        "Not qualified when active partners < 2",
        expected=False,
        actual=is_qualified_no_partners
    )

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_grace_day_streak(session: Session) -> TestReport:
    """
    Test Grace Day streak (3 months loyalty program).
    
    Scenario:
    - Purchase on 1st of Month 1 → streak = 1
    - Purchase on 1st of Month 2 → streak = 2
    - Purchase on 1st of Month 3 → streak = 3, loyaltyQualified = True, +10% JetUp tokens
    """
    from models import User, Purchase
    from mlm_system.services.grace_day_service import GraceDayService
    from mlm_system.utils.time_machine import timeMachine

    report = TestReport("Grace Day Streak (3 months)")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Grace Day Streak (3 months)")
    logger.info("=" * 60)

    # Create test user
    user = session.query(User).filter_by(telegramID=5001).first()
    if not user:
        user = User(
            telegramID=5001,
            firstname="Streak_User",
            upline=1000,
            isActive=True,
            rank="start",
            mlmVolumes={"graceDayStreak": 0},
            mlmStatus={}
        )
        session.add(user)
        session.commit()
    else:
        user.mlmVolumes["graceDayStreak"] = 0
        if not user.mlmStatus:
            user.mlmStatus = {}
        user.mlmStatus["loyaltyQualified"] = False
        flag_modified(user, 'mlmStatus')
        session.commit()

    grace_day_service = GraceDayService(session)

    # Month 1: Purchase on 1st
    timeMachine.setTime(datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc))
    
    purchase1 = Purchase(
        userID=user.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("200"),
        packQty=1,
        
        
    )
    session.add(purchase1)
    session.commit()
    
    await grace_day_service.processGraceDayBonus(purchase1)
    session.refresh(user)
    
    report.check("Streak after Month 1", expected=1, actual=user.mlmVolumes.get("graceDayStreak", 0))

    # Month 2: Purchase on 1st
    timeMachine.setTime(datetime(2025, 2, 1, 10, 0, tzinfo=timezone.utc))
    
    purchase2 = Purchase(
        userID=user.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("200"),
        packQty=1,
        
        
    )
    session.add(purchase2)
    session.commit()
    
    await grace_day_service.processGraceDayBonus(purchase2)
    session.refresh(user)
    
    report.check("Streak after Month 2", expected=2, actual=user.mlmVolumes.get("graceDayStreak", 0))

    # Month 3: Purchase on 1st → Loyalty qualified!
    timeMachine.setTime(datetime(2025, 3, 1, 10, 0, tzinfo=timezone.utc))
    
    purchase3 = Purchase(
        userID=user.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("200"),
        packQty=1,
        
        
    )
    session.add(purchase3)
    session.commit()
    
    await grace_day_service.processGraceDayBonus(purchase3)
    session.refresh(user)
    
    report.check("Streak after Month 3", expected=3, actual=user.mlmVolumes.get("graceDayStreak", 0))
    
    loyalty_qualified = user.mlmStatus.get("loyaltyQualified", False)
    report.check("Loyalty qualified after 3 months", expected=True, actual=loyalty_qualified)

    # Cleanup
    timeMachine.resetToRealTime()

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_grace_day_streak_reset(session: Session) -> TestReport:
    """
    Test Grace Day streak reset on 2nd of month.
    
    Scenario:
    - User has streak = 2
    - No purchase on 1st of next month
    - 2nd of month: streak resets to 0
    """
    from models import User
    from mlm_system.services.grace_day_service import GraceDayService
    from mlm_system.utils.time_machine import timeMachine

    report = TestReport("Grace Day Streak Reset")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Grace Day Streak Reset")
    logger.info("=" * 60)

    # Create test user with streak
    user = session.query(User).filter_by(telegramID=5002).first()
    if not user:
        user = User(
            telegramID=5002,
            firstname="Reset_User",
            upline=1000,
            isActive=True,
            rank="start",
            mlmVolumes={"graceDayStreak": 2, "lastGraceDayMonth": "2025-02"},
            mlmStatus={"lastGraceDayMonth": "2025-02"}
        )
        session.add(user)
        session.commit()
    else:
        user.mlmVolumes["graceDayStreak"] = 2
        user.mlmStatus = {"lastGraceDayMonth": "2025-02"}
        flag_modified(user, 'mlmStatus')
        session.commit()

    report.check("Initial streak", expected=2, actual=user.mlmVolumes.get("graceDayStreak", 0))

    # Set time to 2nd of next month (missed Grace Day)
    timeMachine.setTime(datetime(2025, 3, 2, 0, 1, tzinfo=timezone.utc))

    grace_day_service = GraceDayService(session)
    
    # Run streak reset check (should be triggered by scheduler on 2nd)
    await grace_day_service.resetMonthlyStreaks()
    session.refresh(user)
    
    report.check("Streak reset to 0", expected=0, actual=user.mlmVolumes.get("graceDayStreak", 0))

    # Cleanup
    timeMachine.resetToRealTime()

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_global_pool_2_directors(session: Session) -> TestReport:
    """
    Test Global Pool qualification: requires 2 Directors in DIFFERENT branches.
    
    Scenario A (Qualified):
    - User has Branch A with Director
    - User has Branch B with Director
    - Result: Qualified for Global Pool
    
    Scenario B (Not Qualified):
    - User has Branch A with Director
    - User has Branch B with Growth (not Director)
    - Result: NOT Qualified
    """
    from models import User
    from mlm_system.services.global_pool_service import GlobalPoolService

    report = TestReport("Global Pool 2 Directors Requirement")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Global Pool 2 Directors Requirement")
    logger.info("=" * 60)

    # Create candidate user
    candidate = session.query(User).filter_by(telegramID=6001).first()
    if not candidate:
        candidate = User(
            telegramID=6001,
            firstname="Pool_Candidate",
            upline=1000,
            isActive=True,
            rank="director"
        )
        session.add(candidate)
        session.commit()

    # Create Branch A leader (Director)
    branch_a = session.query(User).filter_by(telegramID=6002).first()
    if not branch_a:
        branch_a = User(
            telegramID=6002,
            firstname="Branch_A_Director",
            upline=candidate.telegramID,
            isActive=True,
            rank="director"
        )
        session.add(branch_a)

    # Create Branch B leader (Director)
    branch_b = session.query(User).filter_by(telegramID=6003).first()
    if not branch_b:
        branch_b = User(
            telegramID=6003,
            firstname="Branch_B_Director",
            upline=candidate.telegramID,
            isActive=True,
            rank="director"
        )
        session.add(branch_b)
    
    session.commit()

    global_pool_service = GlobalPoolService(session)

    # Test Scenario A: 2 Directors in different branches
    result = await global_pool_service.checkUserQualification(candidate.userID)
    is_qualified = result.get("qualified", False)
    report.check(
        "Qualified with 2 Directors in different branches",
        expected=True,
        actual=is_qualified
    )

    # Test Scenario B: Downgrade Branch B to Growth
    branch_b.rank = "growth"
    session.commit()
    
    result_one = await global_pool_service.checkUserQualification(candidate.userID)
    is_qualified_one_director = result_one.get("qualified", False)
    report.check(
        "NOT qualified with only 1 Director branch",
        expected=False,
        actual=is_qualified_one_director
    )

    # Restore for other tests
    branch_b.rank = "director"
    session.commit()

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_investment_tiers_cumulative(session: Session) -> TestReport:
    """
    Test cumulative Investment Tier bonus calculation.
    
    Tiers:
    - $1,000 → 5% bonus
    - $5,000 → 10% bonus
    - $25,000 → 15% bonus
    - $125,000 → 20% bonus
    
    Scenario:
    - Purchase 1: $1,000 → 5% of $1,000 = $50 bonus
    - Purchase 2: $4,000 (total $5,000) → 10% of $5,000 = $500, minus already paid $50 = $450 new bonus
    - Purchase 3: $20,000 (total $25,000) → 15% of $25,000 = $3,750, minus already paid $500 = $3,250 new bonus
    """
    from models import User, Purchase, Bonus
    from mlm_system.services.investment_bonus_service import InvestmentBonusService
    from mlm_system.utils.time_machine import timeMachine

    report = TestReport("Investment Tiers (Cumulative)")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Investment Tiers (Cumulative)")
    logger.info("=" * 60)

    # Create test user
    user = session.query(User).filter_by(telegramID=7001).first()
    if not user:
        user = User(
            telegramID=7001,
            firstname="Investor",
            upline=1000,
            isActive=True,
            rank="start",
            mlmStatus={"totalInvested": 0, "investmentBonusesPaid": 0}
        )
        session.add(user)
        session.commit()
    else:
        user.mlmStatus = {"totalInvested": 0, "investmentBonusesPaid": 0}
        flag_modified(user, 'mlmStatus')
        session.commit()

    investment_service = InvestmentBonusService(session)

    # Purchase 1: $1,000 → enters 5% tier
    purchase1 = Purchase(
        userID=user.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("1000"),
        packQty=1,
        
        
    )
    session.add(purchase1)
    session.commit()
    
    bonus1 = await investment_service.processPurchaseBonus(purchase1)
    session.refresh(user)
    
    report.check(
        "Bonus 1: $1,000 at 5% tier",
        expected=50,
        actual=float(bonus1) if bonus1 else 0
    )

    total_invested = Decimal(str(user.mlmStatus.get("totalInvested", 0)))
    report.check("Total invested after P1", expected=1000, actual=float(total_invested))

    # Purchase 2: $4,000 → total $5,000, enters 10% tier
    purchase2 = Purchase(
        userID=user.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("4000"),
        packQty=1,
        
        
    )
    session.add(purchase2)
    session.commit()
    
    bonus2 = await investment_service.processPurchaseBonus(purchase2)
    session.refresh(user)
    
    # 10% of $5000 = $500, minus $50 already paid = $450
    report.check(
        "Bonus 2: upgrade to 10% tier, differential",
        expected=450,
        actual=float(bonus2) if bonus2 else 0
    )

    # Purchase 3: $20,000 → total $25,000, enters 15% tier
    purchase3 = Purchase(
        userID=user.userID,
        projectID=1,
        optionID=1,
        packPrice=Decimal("20000"),
        packQty=1,
        
        
    )
    session.add(purchase3)
    session.commit()
    
    bonus3 = await investment_service.processPurchaseBonus(purchase3)
    session.refresh(user)
    
    # 15% of $25000 = $3750, minus $500 already paid = $3250
    report.check(
        "Bonus 3: upgrade to 15% tier, differential",
        expected=3250,
        actual=float(bonus3) if bonus3 else 0
    )

    # Verify total bonuses paid
    total_bonuses = Decimal(str(user.mlmStatus.get("investmentBonusesPaid", 0)))
    report.check(
        "Total investment bonuses paid",
        expected=3750,  # 50 + 450 + 3250
        actual=float(total_bonuses)
    )

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


async def test_active_partners_entire_structure(session: Session) -> TestReport:
    """
    Test that active partners are counted from ENTIRE structure, not just Level 1.
    
    Structure:
    - Candidate
      ├── Partner A (active) - Level 1
      │   ├── Partner A1 (active) - Level 2
      │   └── Partner A2 (inactive) - Level 2
      └── Partner B (inactive) - Level 1
          └── Partner B1 (active) - Level 2
    
    Expected active count: 3 (A, A1, B1)
    """
    from models import User
    from mlm_system.services.rank_service import RankService

    report = TestReport("Active Partners (Entire Structure)")
    logger.info("=" * 60)
    logger.info("📋 SCENARIO: Active Partners (Entire Structure)")
    logger.info("=" * 60)

    # Create candidate
    candidate = session.query(User).filter_by(telegramID=8001).first()
    if not candidate:
        candidate = User(
            telegramID=8001,
            firstname="AP_Candidate",
            upline=1000,
            isActive=True,
            rank="start"
        )
        session.add(candidate)
        session.commit()

    # Level 1: Partner A (active)
    partner_a = session.query(User).filter_by(telegramID=8002).first()
    if not partner_a:
        partner_a = User(
            telegramID=8002,
            firstname="Partner_A",
            upline=candidate.telegramID,
            isActive=True,
            rank="start"
        )
        session.add(partner_a)

    # Level 1: Partner B (inactive)
    partner_b = session.query(User).filter_by(telegramID=8003).first()
    if not partner_b:
        partner_b = User(
            telegramID=8003,
            firstname="Partner_B",
            upline=candidate.telegramID,
            isActive=False,
            rank="start"
        )
        session.add(partner_b)
    
    session.commit()

    # Level 2: Partner A1 (active, under A)
    partner_a1 = session.query(User).filter_by(telegramID=8004).first()
    if not partner_a1:
        partner_a1 = User(
            telegramID=8004,
            firstname="Partner_A1",
            upline=partner_a.telegramID,
            isActive=True,
            rank="start"
        )
        session.add(partner_a1)

    # Level 2: Partner A2 (inactive, under A)
    partner_a2 = session.query(User).filter_by(telegramID=8005).first()
    if not partner_a2:
        partner_a2 = User(
            telegramID=8005,
            firstname="Partner_A2",
            upline=partner_a.telegramID,
            isActive=False,
            rank="start"
        )
        session.add(partner_a2)

    # Level 2: Partner B1 (active, under B)
    partner_b1 = session.query(User).filter_by(telegramID=8006).first()
    if not partner_b1:
        partner_b1 = User(
            telegramID=8006,
            firstname="Partner_B1",
            upline=partner_b.telegramID,
            isActive=True,
            rank="start"
        )
        session.add(partner_b1)
    
    session.commit()

    # Test active partners count
    rank_service = RankService(session)
    active_count = await rank_service._countActivePartners(candidate)
    
    # Expected: A (active) + A1 (active) + B1 (active) = 3
    # NOT counted: A2 (inactive), B (inactive)
    report.check(
        "Active partners in entire structure",
        expected=3,
        actual=active_count
    )

    # Verify Level 1 only would give wrong result
    level1_active = session.query(User).filter(
        User.upline == candidate.telegramID,
        User.isActive == True
    ).count()
    
    report.check(
        "Level 1 only count (for comparison)",
        expected=1,  # Only Partner A
        actual=level1_active
    )

    report.check(
        "Entire structure > Level 1 only",
        expected=True,
        actual=active_count > level1_active
    )

    status = "✅ PASSED" if report.is_passed() else "❌ FAILED"
    logger.info(f"{status} ({report.passed}/{len(report.checks)} tests)")
    
    return report


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN RUNNER
# ═══════════════════════════════════════════════════════════════════════════════

async def run_all_tests():
    """Run all advanced MLM tests."""
    from core.db import get_db_session_ctx
    from config import Config
    from mlm_system.utils.time_machine import timeMachine

    logger.info("=" * 70)
    logger.info("🧪 ADVANCED MLM SYSTEM TESTS")
    logger.info("=" * 70)

    # Initialize config
    Config.initialize_from_env()
    await Config.initialize_dynamic_from_sheets()

    all_reports = []

    with get_db_session_ctx() as session:
        # Run all test scenarios
        test_functions = [
            test_50_percent_rule,
            test_pioneer_bonus_applied,
            test_rank_qualification,
            test_grace_day_streak,
            test_grace_day_streak_reset,
            test_global_pool_2_directors,
            test_investment_tiers_cumulative,
            test_active_partners_entire_structure,
        ]

        for test_func in test_functions:
            try:
                report = await test_func(session)
                all_reports.append(report)
            except Exception as e:
                logger.error(f"❌ {test_func.__name__} CRASHED: {e}", exc_info=True)
                report = TestReport(test_func.__name__)
                report.check("Test execution", True, False)
                all_reports.append(report)

    # Return to real time
    timeMachine.resetToRealTime()

    # Print summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("📊 TEST SUMMARY")
    logger.info("=" * 70)

    total_passed = sum(r.passed for r in all_reports)
    total_failed = sum(r.failed for r in all_reports)
    total_tests = total_passed + total_failed

    scenarios_passed = sum(1 for r in all_reports if r.is_passed())
    scenarios_total = len(all_reports)

    logger.info(f"Scenarios: {scenarios_passed}/{scenarios_total} passed")
    logger.info(f"Tests:     {total_passed}/{total_tests} passed")

    if total_failed > 0:
        logger.info("")
        logger.info("❌ FAILED TESTS:")
        for report in all_reports:
            for check in report.checks:
                if not check['passed']:
                    logger.info(f"  • [{report.scenario_name}] {check['name']}")
                    logger.info(f"    Expected: {check['expected']}")
                    logger.info(f"    Actual:   {check['actual']}")

    logger.info("=" * 70)
    
    return total_failed == 0


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
