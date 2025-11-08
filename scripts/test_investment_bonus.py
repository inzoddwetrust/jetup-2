#!/usr/bin/env python3
"""
Test script for Investment Bonus (cumulative tiers).

Tests the cumulative bonus calculation across multiple purchases.

Tiers:
- $1,000 → 5% cumulative
- $5,000 → 10% cumulative
- $10,000 → 15% cumulative
- $20,000 → 20% cumulative

Usage:
    python scripts/test_investment_bonus.py [--user-id TELEGRAM_ID]
"""

import sys
import os
import asyncio
import argparse
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session
from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from mlm_system.services.investment_bonus_service import InvestmentBonusService
from sqlalchemy import func

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Test purchase sequence
TEST_PURCHASES = [
    {"amount": Decimal("400"), "expected_bonus": Decimal("0")},  # Total: $400, no tier
    {"amount": Decimal("700"), "expected_bonus": Decimal("55")},  # Total: $1100, 5% tier
    {"amount": Decimal("4000"), "expected_bonus": Decimal("455")},  # Total: $5100, 10% tier
    {"amount": Decimal("5000"), "expected_bonus": Decimal("1065")},  # Total: $10100, 15% tier
    {"amount": Decimal("10000"), "expected_bonus": Decimal("3510")},  # Total: $20100, 20% tier
]


async def main():
    """Run investment bonus test."""
    parser = argparse.ArgumentParser(description='Test Investment Bonus')
    parser.add_argument('--user-id', type=int, default=5971989877,
                        help='Telegram ID of test user (default: Зодд)')
    args = parser.parse_args()

    print("\n" + "=" * 80)
    print("🧪 INVESTMENT BONUS TEST")
    print("=" * 80 + "\n")

    # Initialize config
    Config.initialize_from_env()

    session = get_session()

    try:
        # Step 1: Find user
        print(f"Step 1: Finding user (ID: {args.user_id})...")
        user = session.query(User).filter_by(telegramID=args.user_id).first()
        if not user:
            print(f"❌ User with telegram ID {args.user_id} not found!")
            return

        print(f"✓ Found user: {user.firstname} (userID: {user.userID})\n")

        # Step 2: Clear previous test data
        print("Step 2: Clearing previous test data...")
        session.query(Purchase).filter_by(userID=user.userID).delete()
        session.query(Bonus).filter_by(userID=user.userID).delete()
        session.commit()
        print("✓ Test data cleared\n")

        # Step 3: Run purchase sequence
        print("Step 3: Running purchase sequence...")
        print("=" * 80)

        investment_service = InvestmentBonusService(session)
        project_id = 1  # Assuming project 1 exists

        total_invested = Decimal("0")
        total_bonuses = Decimal("0")

        for i, purchase_config in enumerate(TEST_PURCHASES, start=1):
            print(f"\nPurchase {i}: ${purchase_config['amount']}")
            print("-" * 80)

            # Create purchase
            purchase = Purchase()
            purchase.userID = user.userID
            purchase.projectID = project_id
            purchase.optionID = 1  # Assuming option 1 exists
            purchase.projectName = f"Test Project {project_id}"
            purchase.packQty = int(purchase_config['amount'] / 10)  # Arbitrary qty
            purchase.packPrice = purchase_config['amount']
            purchase.ownerTelegramID = user.telegramID
            purchase.ownerEmail = user.email

            session.add(purchase)
            session.commit()
            session.refresh(purchase)

            # Process investment bonus
            bonus_amount = await investment_service.processPurchaseBonus(purchase)

            total_invested += purchase_config['amount']
            if bonus_amount:
                total_bonuses += bonus_amount

            # Calculate totals
            actual_total = await investment_service._calculateTotalPurchased(
                user.userID, project_id
            )
            actual_granted = await investment_service._calculateAlreadyGranted(
                user.userID, project_id
            )

            print(f"  Purchase amount:     ${purchase_config['amount']}")
            print(f"  Total invested:      ${actual_total}")
            print(f"  Expected bonus:      ${purchase_config['expected_bonus']}")
            print(f"  Actual bonus:        ${bonus_amount or Decimal('0')}")
            print(f"  Total bonuses:       ${actual_granted}")

            # Verify
            if bonus_amount:
                if abs(bonus_amount - purchase_config['expected_bonus']) < Decimal('1'):
                    print(f"  ✅ Bonus calculation correct!")
                else:
                    print(f"  ❌ Bonus mismatch! Expected ${purchase_config['expected_bonus']}, got ${bonus_amount}")
            else:
                if purchase_config['expected_bonus'] == Decimal('0'):
                    print(f"  ✅ No bonus expected, none granted")
                else:
                    print(f"  ❌ Bonus expected but not granted!")

        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80 + "\n")

        # Final verification
        final_total = await investment_service._calculateTotalPurchased(user.userID, project_id)
        final_bonuses = await investment_service._calculateAlreadyGranted(user.userID, project_id)

        print(f"Total invested:        ${final_total}")
        print(f"Total bonuses granted: ${final_bonuses}")
        print(f"Bonus percentage:      {float(final_bonuses / final_total * 100):.2f}%")

        # Check database records
        print("\n" + "=" * 80)
        print("DATABASE VERIFICATION")
        print("=" * 80 + "\n")

        # Purchases
        purchases = session.query(Purchase).filter_by(
            userID=user.userID,
            projectID=project_id
        ).order_by(Purchase.createdAt).all()

        print(f"Purchase records: {len(purchases)}")
        purchase_sum = sum(p.packPrice for p in purchases)
        print(f"  Total amount: ${purchase_sum}")

        # Bonuses
        bonuses = session.query(Bonus).filter_by(
            userID=user.userID,
            projectID=project_id,
            commissionType='investment_package'
        ).order_by(Bonus.createdAt).all()

        print(f"\nInvestment bonus records: {len(bonuses)}")
        for bonus in bonuses:
            print(f"  • ${bonus.bonusAmount} ({bonus.bonusRate*100:.1f}%) - {bonus.notes}")

        bonus_sum = sum(b.bonusAmount for b in bonuses)
        print(f"  Total bonuses: ${bonus_sum}")

        # Auto-purchases
        auto_purchases = session.query(Purchase).filter_by(
            userID=user.userID,
            projectID=project_id
        ).filter(
            Purchase.packPrice.in_([b.bonusAmount for b in bonuses])
        ).all()

        print(f"\nAuto-purchase records: {len(auto_purchases)}")
        auto_purchase_sum = sum(p.packPrice for p in auto_purchases)
        print(f"  Total auto-purchases: ${auto_purchase_sum}")

        # Final verdict
        print("\n" + "=" * 80)
        if abs(final_bonuses - sum(p['expected_bonus'] for p in TEST_PURCHASES)) < Decimal('1'):
            print("✅ ALL TESTS PASSED!")
        else:
            print("❌ TESTS FAILED - Bonus calculation mismatch")
        print("=" * 80 + "\n")

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        print(f"\n❌ TEST FAILED: {e}\n")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
