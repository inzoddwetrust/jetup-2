#!/usr/bin/env python3
"""
Display MLM structure tree.

Shows the complete user hierarchy with status indicators.

Usage:
    python scripts/show_tree.py [--root-id TELEGRAM_ID] [--max-depth DEPTH]
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from core.db import get_session
from models.user import User
from mlm_system.utils.chain_walker import ChainWalker

import logging

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def print_tree(root_user, max_depth=None):
    """Print ASCII tree of the structure."""
    session = get_session()
    try:
        walker = ChainWalker(session)

        def print_user(user, prefix="", is_last=True, depth=0):
            if max_depth and depth > max_depth:
                return

            connector = "└─ " if is_last else "├─ "
            rank_display = f"[{user.rank}]" if user.rank != "start" else ""
            balance_display = f"${user.balanceActive}" if user.balanceActive > 0 else ""
            root_marker = "👑 " if walker.is_system_root(user) else ""
            real_marker = "⭐️ " if user.telegramID >= 1000000 else ""
            active_marker = "✅" if user.isActive else "❌"

            # Pioneer status
            pioneer_marker = ""
            if user.mlmStatus and user.mlmStatus.get("hasPioneerBonus"):
                pioneer_marker = "🏆 "

            # Grace day status
            grace_marker = ""
            if user.mlmStatus and user.mlmStatus.get("graceDay", {}).get("active"):
                grace_marker = "⏰ "

            print(
                f"{prefix}{connector}{root_marker}{real_marker}{pioneer_marker}{grace_marker}"
                f"{user.firstname} (ID:{user.telegramID}) {active_marker} {rank_display} {balance_display}"
            )

            children = session.query(User).filter(User.upline == user.telegramID).all()
            children = [c for c in children if not walker.is_system_root(c)]

            for i, child in enumerate(children):
                is_last_child = (i == len(children) - 1)
                new_prefix = prefix + ("    " if is_last else "│   ")
                print_user(child, new_prefix, is_last_child, depth + 1)

        print("\n" + "=" * 80)
        print("MLM STRUCTURE TREE")
        print("=" * 80)
        print("\nLegend:")
        print("  👑 = System Root (DEFAULT_REFERRER)")
        print("  ⭐️ = Real user (Telegram ID >= 1,000,000)")
        print("  🏆 = Pioneer (has pioneer bonus)")
        print("  ⏰ = Grace period active")
        print("  ✅ = Active user")
        print("  ❌ = Inactive user")
        print("  [rank] = User rank (if not 'start')")
        print("  $amount = Active balance")
        print("\n" + "=" * 80 + "\n")
        print_user(root_user)
        print("\n" + "=" * 80 + "\n")

    finally:
        session.close()


def print_statistics():
    """Print database statistics."""
    session = get_session()
    try:
        total_users = session.query(User).count()
        active_users = session.query(User).filter_by(isActive=True).count()

        # Count by rank
        ranks = session.query(User.rank, session.query(User).filter(
            User.rank == User.rank
        ).count()).group_by(User.rank).all()

        print("\n" + "=" * 80)
        print("DATABASE STATISTICS")
        print("=" * 80 + "\n")

        print(f"Total users:   {total_users}")
        print(f"Active users:  {active_users} ({active_users/total_users*100:.1f}%)")
        print(f"Inactive users: {total_users - active_users} ({(total_users - active_users)/total_users*100:.1f}%)")

        print("\nUsers by rank:")
        from sqlalchemy import func
        rank_counts = session.query(
            User.rank,
            func.count(User.userID)
        ).group_by(User.rank).all()

        for rank, count in rank_counts:
            print(f"  {rank:12} {count:3} ({count/total_users*100:.1f}%)")

        # Real vs dummy users
        real_users = session.query(User).filter(User.telegramID >= 1000000).count()
        dummy_users = total_users - real_users
        print(f"\nReal users:  {real_users}")
        print(f"Dummy users: {dummy_users}")

        # Pioneer count
        pioneers = session.query(User).filter(
            User.mlmStatus.op('->>')('hasPioneerBonus') == 'true'
        ).count()
        print(f"Pioneers:    {pioneers}")

        # Grace period users
        grace_users = session.query(User).filter(
            User.mlmStatus.op('->>')('graceDay').op('->>')('active') == 'true'
        ).count()
        print(f"Grace period: {grace_users}")

        print("\n" + "=" * 80 + "\n")

    finally:
        session.close()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Display MLM structure tree')
    parser.add_argument('--root-id', type=int,
                        help='Telegram ID of root user (default: DEFAULT_REFERRER)')
    parser.add_argument('--max-depth', type=int,
                        help='Maximum depth to display')
    parser.add_argument('--stats', action='store_true',
                        help='Show statistics only')
    args = parser.parse_args()

    # Initialize config
    Config.initialize_from_env()

    if args.stats:
        print_statistics()
        return

    session = get_session()
    try:
        # Find root user
        if args.root_id:
            root = session.query(User).filter_by(telegramID=args.root_id).first()
            if not root:
                print(f"❌ User with telegram ID {args.root_id} not found!")
                return
        else:
            # Use DEFAULT_REFERRER
            default_ref_id = int(Config.get(Config.DEFAULT_REFERRER_ID))
            root = session.query(User).filter_by(telegramID=default_ref_id).first()
            if not root:
                print(f"❌ DEFAULT_REFERRER (ID: {default_ref_id}) not found!")
                return

        print_tree(root, args.max_depth)
        print_statistics()

    finally:
        session.close()


if __name__ == "__main__":
    main()
