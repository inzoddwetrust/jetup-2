#!/usr/bin/env python3
"""
Test script for commission flow.

Runs a complete test of differential commissions with compression.
Use after populate_commission_test.py to populate the database.

Usage:
    python scripts/test_commission_flow.py
"""

import sys
import os
import asyncio
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session
from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus
from mlm_system.services.commission_service import CommissionService

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Run commission flow test."""
    print("\n" + "=" * 80)
    print("🧪 COMMISSION FLOW TEST")
    print("=" * 80 + "\n")

    # Initialize config
    Config.initialize_from_env()

    session = get_session()

    try:
        # Step 1: Find buyer (Зодд)
        print("Step 1: Finding buyer...")
        buyer = session.query(User).filter_by(telegramID=5971989877).first()
        if not buyer:
            print("❌ Buyer (Зодд) not found. Run populate_commission_test.py first!")
            return

        print(f"✓ Found buyer: {buyer.firstname} (ID: {buyer.userID})\n")

        # Step 2: Create test purchase
        print("Step 2: Creating test purchase...")
        purchase_amount = Decimal("1000.00")

        purchase = Purchase()
        purchase.userID = buyer.userID
        purchase.projectID = 1  # Assuming project 1 exists
        purchase.optionID = 1  # Assuming option 1 exists
        purchase.projectName = "Test Project"
        purchase.packQty = 100
        purchase.packPrice = purchase_amount
        purchase.ownerTelegramID = buyer.telegramID
        purchase.ownerEmail = buyer.email

        session.add(purchase)
        session.commit()
        session.refresh(purchase)

        print(f"✓ Created purchase: ID={purchase.purchaseID}, amount=${purchase_amount}\n")

        # Step 3: Process commissions
        print("Step 3: Processing commissions...")
        commission_service = CommissionService(session)
        result = await commission_service.processPurchase(purchase.purchaseID)

        if not result.get("success"):
            print(f"❌ Commission processing failed: {result.get('error')}")
            return

        print(f"✓ Commissions processed successfully\n")

        # Step 4: Display results
        print("=" * 80)
        print("COMMISSION BREAKDOWN")
        print("=" * 80 + "\n")

        print(f"Purchase amount: ${purchase_amount}")
        print(f"Total distributed: ${result['totalDistributed']}")
        print(f"Expected (18%): ${purchase_amount * Decimal('0.18')}")
        print(f"Commission count: {len(result['commissions'])}\n")

        print("Individual commissions:")
        print("-" * 80)

        total_check = Decimal("0")
        for comm in result['commissions']:
            user = session.query(User).filter_by(userID=comm['userId']).first()
            active_marker = "✅" if comm['isActive'] else "❌"
            compressed_marker = " [COMPRESSED]" if comm.get('compressed') else ""
            root_marker = " [SYSTEM ROOT]" if comm.get('isSystemRoot') else ""

            print(
                f"Level {comm['level']}: {user.firstname:12} {active_marker} "
                f"[{comm['rank']:10}] "
                f"{float(comm['percentage'])*100:5.1f}% = ${float(comm['amount']):8.2f}"
                f"{compressed_marker}{root_marker}"
            )

            if comm['isActive'] or comm.get('isSystemRoot'):
                total_check += comm['amount']

        print("-" * 80)
        print(f"Total paid out: ${float(total_check):.2f}")
        print(f"Expected:       ${float(purchase_amount * Decimal('0.18')):.2f}")
        print(f"Difference:     ${float(abs(total_check - purchase_amount * Decimal('0.18'))):.2f}")

        if abs(total_check - purchase_amount * Decimal('0.18')) < Decimal('0.01'):
            print("\n✅ TEST PASSED: Commission calculation correct!")
        else:
            print("\n❌ TEST FAILED: Commission sum mismatch!")

        print("\n" + "=" * 80 + "\n")

        # Step 5: Detailed database check
        print("Database verification:")
        print("-" * 80)

        bonuses = session.query(Bonus).filter_by(purchaseID=purchase.purchaseID).all()
        print(f"Bonus records created: {len(bonuses)}")

        for bonus in bonuses:
            user = session.query(User).filter_by(userID=bonus.userID).first()
            print(
                f"  • {user.firstname}: ${bonus.bonusAmount} "
                f"({bonus.bonusRate*100:.1f}%), status={bonus.status}, "
                f"type={bonus.commissionType}"
            )

        print("\n" + "=" * 80 + "\n")

    except Exception as e:
        logger.error(f"Test failed with error: {e}", exc_info=True)
        print(f"\n❌ TEST FAILED: {e}\n")

    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())
