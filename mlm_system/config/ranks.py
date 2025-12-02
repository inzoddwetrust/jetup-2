"""
MLM ranks configuration and constants.
Loads from Google Sheets via Config module.
"""
from enum import Enum
from decimal import Decimal
from typing import Dict, Any
import logging

logger = logging.getLogger(__name__)


class Rank(Enum):
    """MLM rank enumeration."""
    START = "start"
    BUILDER = "builder"
    GROWTH = "growth"
    LEADERSHIP = "leadership"
    DIRECTOR = "director"


def get_rank_config() -> Dict[Rank, Dict[str, Any]]:
    """
    Get rank configuration from Config module.

    Returns:
        Dictionary mapping Rank enum to configuration dict

    Raises:
        ValueError: If RANK_CONFIG not loaded
    """
    from config import Config

    raw_config = Config.get(Config.RANK_CONFIG)

    if not raw_config:
        logger.error("RANK_CONFIG not loaded from Google Sheets!")
        raise ValueError("RANK_CONFIG must be loaded from Google Sheets before use")

    # Convert string keys to Rank enum and values to Decimal
    rank_config = {}

    for rank_key, rank_data in raw_config.items():
        try:
            rank_enum = Rank(rank_key)

            # Convert numeric values to Decimal
            rank_config[rank_enum] = {
                "percentage": Decimal(str(rank_data["percentage"])) / 100,  # Convert % to decimal
                "personalVolumeRequired": Decimal(str(rank_data.get("personalVolumeRequired", "0"))),  # ✅ NEW: Added PV requirement
                "teamVolumeRequired": Decimal(str(rank_data["teamVolumeRequired"])),
                "activePartnersRequired": int(rank_data["activePartnersRequired"]),
                "displayName": rank_data["displayName"]
            }

        except (ValueError, KeyError) as e:
            logger.error(f"Invalid rank configuration for '{rank_key}': {e}")
            continue

    return rank_config


# Lazy-loaded configuration cache
_RANK_CONFIG_CACHE: Dict[Rank, Dict[str, Any]] = {}


def get_rank_config_cached() -> Dict[Rank, Dict[str, Any]]:
    """
    Get rank configuration with caching.
    Loads from Config on first access, then returns cached version.

    Returns:
        Rank configuration dictionary
    """
    global _RANK_CONFIG_CACHE

    if not _RANK_CONFIG_CACHE:
        _RANK_CONFIG_CACHE = get_rank_config()
        logger.info(f"Loaded RANK_CONFIG: {len(_RANK_CONFIG_CACHE)} ranks")

    return _RANK_CONFIG_CACHE


# Public accessor - use this everywhere instead of RANK_CONFIG constant
def RANK_CONFIG():
    """Get current rank configuration."""
    return get_rank_config_cached()


# Constants (these can stay hardcoded as they don't change)
MINIMUM_PV = Decimal("200")
PIONEER_BONUS_PERCENTAGE = Decimal("0.04")
REFERRAL_BONUS_PERCENTAGE = Decimal("0.01")
GLOBAL_POOL_PERCENTAGE = Decimal("0.02")
TRANSFER_BONUS_PERCENTAGE = Decimal("0.02")
PIONEER_MAX_COUNT = 50
REFERRAL_BONUS_MIN_AMOUNT = Decimal("5000")