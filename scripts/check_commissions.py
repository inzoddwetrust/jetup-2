#!/usr/bin/env python3
"""
Check commissions for a purchase.

Displays detailed commission breakdown from database.

Usage:
    python scripts/check_commissions.py --purchase-id 123
    python scripts/check_commissions.py --last  # Check last purchase
"""

import sys
import os
import argparse
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session
from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus

import logging

logging.basicConfig(level=logging.WARNING)


def main():
    """Check commissions."""
    parser = argparse.ArgumentParser(description='Check commissions for purchase')
    parser.add_argument('--purchase-id', type=int, help='Purchase ID to check')
    parser.add_argument('--last', action='store_true', help='Check last purchase')
    args = parser.parse_args()

    Config.initialize_from_env()
    session = get_session()

    try:
        # Find purchase
        if args.last:
            purchase = session.query(Purchase).order_by(
                Purchase.createdAt.desc()
            ).first()
        elif args.purchase_id:
            purchase = session.query(Purchase).filter_by(
                purchaseID=args.purchase_id
            ).first()
        else:
            print("❌ Specify --purchase-id or --last")
            return

        if not purchase:
            print("❌ Purchase not found")
            return

        # Get buyer
        buyer = session.query(User).filter_by(userID=purchase.userID).first()

        print("\n" + "=" * 80)
        print("COMMISSION CHECK")
        print("=" * 80)
        print(f"\nPurchase ID: {purchase.purchaseID}")
        print(f"Buyer: {buyer.firstname} (ID: {buyer.telegramID})")
        print(f"Amount: ${purchase.packPrice}")
        print(f"Date: {purchase.createdAt}")

        # Get commissions
        bonuses = session.query(Bonus).filter_by(
            purchaseID=purchase.purchaseID
        ).order_by(Bonus.uplineLevel).all()

        if not bonuses:
            print("\n❌ No commissions found for this purchase")
            return

        print(f"\n{len(bonuses)} commission(s) found:")
        print("-" * 80)

        total_paid = Decimal("0")
        total_compressed = Decimal("0")

        for bonus in bonuses:
            user = session.query(User).filter_by(userID=bonus.userID).first()

            # Markers
            active_marker = "✅" if user.isActive else "❌"
            compressed_marker = " [COMPRESSED]" if bonus.compressionApplied else ""
            system_marker = " [SYSTEM ROOT]" if bonus.commissionType == "system_compression" else ""
            referral_marker = " [REFERRAL]" if bonus.commissionType == "referral" else ""
            pioneer_marker = " [PIONEER]" if bonus.commissionType == "pioneer" else ""

            print(
                f"Level {bonus.uplineLevel:2}: "
                f"{user.firstname:15} {active_marker} "
                f"[{user.rank:10}] "
                f"{bonus.bonusRate*100:5.1f}% = ${float(bonus.bonusAmount):8.2f} "
                f"({bonus.status:7})"
                f"{compressed_marker}{system_marker}{referral_marker}{pioneer_marker}"
            )

            if bonus.compressionApplied:
                total_compressed += bonus.bonusAmount
            else:
                total_paid += bonus.bonusAmount

        print("-" * 80)

        expected = purchase.packPrice * Decimal("0.18")
        difference = abs(total_paid - expected)

        print(f"\nTotal paid:        ${float(total_paid):.2f}")
        print(f"Total compressed:  ${float(total_compressed):.2f}")
        print(f"Expected (18%):    ${float(expected):.2f}")
        print(f"Difference:        ${float(difference):.2f}")

        if difference < Decimal("0.01"):
            print("\n✅ COMMISSION CALCULATION CORRECT!")
        else:
            print("\n⚠️  WARNING: Commission sum mismatch!")

        # Detailed breakdown
        print("\n" + "=" * 80)
        print("DETAILED BREAKDOWN")
        print("=" * 80)

        for bonus in bonuses:
            user = session.query(User).filter_by(userID=bonus.userID).first()
            print(f"\n{user.firstname} (ID: {user.userID}):")
            print(f"  Rank: {user.rank}")
            print(f"  Active: {user.isActive}")
            print(f"  Commission type: {bonus.commissionType}")
            print(f"  Rate: {bonus.bonusRate*100:.1f}%")
            print(f"  Amount: ${bonus.bonusAmount}")
            print(f"  Status: {bonus.status}")
            print(f"  Notes: {bonus.notes or 'N/A'}")

        print("\n" + "=" * 80 + "\n")

    finally:
        session.close()


if __name__ == "__main__":
    main()
