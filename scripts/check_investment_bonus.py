#!/usr/bin/env python3
"""
Check investment bonuses for a user.

Shows all investment bonuses and purchase history.

Usage:
    python scripts/check_investment_bonus.py --user-id 5971989877
"""

import sys
import os
import argparse
from decimal import Decimal
from sqlalchemy import func

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session
from models.user import User
from models.purchase import Purchase
from models.bonus import Bonus

import logging

logging.basicConfig(level=logging.WARNING)


# Tier configuration (hardcoded for display)
TIERS = [
    {"threshold": Decimal("1000"), "percentage": Decimal("5")},
    {"threshold": Decimal("5000"), "percentage": Decimal("10")},
    {"threshold": Decimal("10000"), "percentage": Decimal("15")},
    {"threshold": Decimal("20000"), "percentage": Decimal("20")},
]


def get_current_tier(total_invested):
    """Get current tier for total invested amount."""
    current_tier = None
    for tier in TIERS:
        if total_invested >= tier["threshold"]:
            current_tier = tier
        else:
            break
    return current_tier


def get_next_tier(total_invested):
    """Get next tier to reach."""
    for tier in TIERS:
        if total_invested < tier["threshold"]:
            return tier
    return None


def main():
    """Check investment bonuses."""
    parser = argparse.ArgumentParser(description='Check investment bonuses for user')
    parser.add_argument('--user-id', type=int, required=True,
                        help='Telegram ID of user')
    args = parser.parse_args()

    Config.initialize_from_env()
    session = get_session()

    try:
        # Find user
        user = session.query(User).filter_by(telegramID=args.user_id).first()
        if not user:
            print(f"❌ User with telegram ID {args.user_id} not found")
            return

        print("\n" + "=" * 80)
        print("INVESTMENT BONUS CHECK")
        print("=" * 80)
        print(f"\nUser: {user.firstname} (ID: {user.telegramID})")
        print(f"Email: {user.email}")
        print(f"Rank: {user.rank}")
        print(f"Balance: ${user.balanceActive}")

        # Get all purchases
        purchases = session.query(Purchase).filter_by(
            userID=user.userID
        ).order_by(Purchase.createdAt).all()

        total_invested = sum(p.packPrice for p in purchases)

        print(f"\nPurchases: {len(purchases)}")
        print(f"Total invested: ${total_invested}")

        # Current tier
        current_tier = get_current_tier(total_invested)
        if current_tier:
            print(f"Current tier: ${current_tier['threshold']} ({current_tier['percentage']}%)")
        else:
            print("Current tier: None (< $1000)")

        # Next tier
        next_tier = get_next_tier(total_invested)
        if next_tier:
            remaining = next_tier['threshold'] - total_invested
            print(f"Next tier: ${next_tier['threshold']} ({next_tier['percentage']}%)")
            print(f"Remaining to next tier: ${remaining}")
        else:
            print("Next tier: MAX TIER REACHED!")

        # Get investment bonuses
        bonuses = session.query(Bonus).filter_by(
            userID=user.userID,
            commissionType='investment_package'
        ).order_by(Bonus.createdAt).all()

        total_bonuses = sum(b.bonusAmount for b in bonuses)

        print(f"\nInvestment bonuses: {len(bonuses)}")
        print(f"Total bonuses granted: ${total_bonuses}")

        if current_tier:
            expected_total = total_invested * (current_tier['percentage'] / 100)
            difference = abs(expected_total - total_bonuses)
            print(f"Expected total bonus: ${expected_total} ({current_tier['percentage']}% of ${total_invested})")
            print(f"Difference: ${difference}")

            if difference < Decimal("1"):
                print("✅ Bonus calculation correct!")
            else:
                print("⚠️  Warning: Bonus mismatch!")

        # Purchase history
        print("\n" + "=" * 80)
        print("PURCHASE HISTORY")
        print("=" * 80 + "\n")

        running_total = Decimal("0")
        for i, purchase in enumerate(purchases, 1):
            running_total += purchase.packPrice

            # Find bonus for this purchase (if any)
            bonus = session.query(Bonus).filter_by(
                userID=user.userID,
                purchaseID=purchase.purchaseID,
                commissionType='investment_package'
            ).first()

            bonus_str = f"→ Bonus: ${bonus.bonusAmount}" if bonus else "→ No bonus"
            tier = get_current_tier(running_total)
            tier_str = f"[{tier['percentage']}% tier]" if tier else "[No tier]"

            print(
                f"{i}. ${purchase.packPrice:7.2f} "
                f"(total: ${running_total:8.2f}) {tier_str} {bonus_str}"
            )

        # Bonus details
        if bonuses:
            print("\n" + "=" * 80)
            print("BONUS DETAILS")
            print("=" * 80 + "\n")

            for bonus in bonuses:
                print(f"Bonus ID: {bonus.bonusID}")
                print(f"  Amount: ${bonus.bonusAmount}")
                print(f"  Rate: {bonus.bonusRate*100:.1f}%")
                print(f"  Date: {bonus.createdAt}")
                print(f"  Notes: {bonus.notes}")
                print()

        print("=" * 80 + "\n")

    finally:
        session.close()


if __name__ == "__main__":
    main()
