# mlm_system/utils/investment_helpers.py
"""
Helper functions for investment bonus calculations.
"""
from decimal import Decimal
from typing import Dict, List
import logging

from config import Config

logger = logging.getLogger(__name__)


def get_bonus_tiers() -> Dict[Decimal, Decimal]:
    """
    Get investment bonus tiers from config.

    Returns:
        Dict with tier amounts and percentages
    """
    tiers = Config.get(Config.INVESTMENT_BONUS_TIERS, {})

    if not tiers:
        logger.warning("No investment bonus tiers configured")
        return {}

    return tiers


def get_sorted_tiers() -> List[Decimal]:
    """
    Get sorted list of tier thresholds.

    Returns:
        Sorted list of tier amounts (ascending)
    """
    tiers = get_bonus_tiers()
    return sorted(tiers.keys())


def get_tier_percentage(total_amount: Decimal) -> Decimal:
    """
    Get bonus percentage for given total amount.
    Returns the highest tier percentage that applies.

    Args:
        total_amount: Total amount purchased

    Returns:
        Bonus percentage (e.g., 0.05 for 5%)

    Example:
        get_tier_percentage(Decimal("500")) -> Decimal("0")
        get_tier_percentage(Decimal("1500")) -> Decimal("0.05")
        get_tier_percentage(Decimal("6000")) -> Decimal("0.10")
    """
    tiers = get_bonus_tiers()
    sorted_tiers = get_sorted_tiers()

    applicable_percentage = Decimal("0")

    for tier_amount in sorted_tiers:
        if total_amount >= tier_amount:
            applicable_percentage = tiers[tier_amount]
        else:
            break

    return applicable_percentage


def calculate_expected_bonus(total_amount: Decimal) -> Decimal:
    """
    Calculate total expected bonus for given amount.

    Args:
        total_amount: Total amount purchased

    Returns:
        Total bonus amount expected

    Example:
        calculate_expected_bonus(Decimal("1000")) -> Decimal("50")
        calculate_expected_bonus(Decimal("5000")) -> Decimal("500")
    """
    percentage = get_tier_percentage(total_amount)
    return total_amount * percentage


def get_tier_info(total_amount: Decimal) -> Dict:
    """
    Get detailed tier information for given amount.
    Useful for UI display.

    Args:
        total_amount: Total amount purchased

    Returns:
        Dict with current tier info and next tier info

    Example:
        {
            "current_tier": {
                "total_purchased": 1500.0,
                "bonus_percentage": 5.0,
                "total_bonus": 75.0
            },
            "next_tier": {
                "threshold": 5000.0,
                "bonus_percentage": 10.0,
                "amount_needed": 3500.0
            }
        }
    """
    tiers = get_bonus_tiers()
    sorted_tiers = get_sorted_tiers()

    current_percentage = get_tier_percentage(total_amount)
    current_bonus = calculate_expected_bonus(total_amount)

    # Find next tier
    next_tier = None
    next_percentage = None
    for tier_amount in sorted_tiers:
        if total_amount < tier_amount:
            next_tier = tier_amount
            next_percentage = tiers[tier_amount]
            break

    result = {
        "current_tier": {
            "total_purchased": float(total_amount),
            "bonus_percentage": float(current_percentage * 100),  # Convert to percent
            "total_bonus": float(current_bonus)
        }
    }

    if next_tier:
        result["next_tier"] = {
            "threshold": float(next_tier),
            "bonus_percentage": float(next_percentage * 100),
            "amount_needed": float(next_tier - total_amount)
        }
    else:
        result["next_tier"] = None

    return result