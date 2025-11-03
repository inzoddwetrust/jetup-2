# jetup-2/utils/crypto_rates.py
"""
Crypto rates fetcher for Jetup bot.
Fetches BNB, ETH, TRX rates from Binance and CoinGecko APIs.

Usage:
    rates = await get_crypto_rates()
    if rates:
        bnb_price = rates['BNB']
"""
import logging
import aiohttp
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# API endpoints
API_ENDPOINTS = {
    "binance": "https://api.binance.com/api/v3/ticker/price",
    "coingecko": "https://api.coingecko.com/api/v3/simple/price?ids=binancecoin,ethereum,tron&vs_currencies=usd"
}

# Request timeout
TIMEOUT = aiohttp.ClientTimeout(total=10)


async def fetch_from_binance() -> Optional[Dict[str, float]]:
    """
    Fetch crypto rates from Binance API.

    Returns:
        Dictionary with rates: {'BNB': 245.67, 'ETH': 2345.89, 'TRX': 0.12}
        or None if API unavailable
    """
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(API_ENDPOINTS["binance"]) as response:
                if response.status != 200:
                    logger.warning(f"Binance API returned status {response.status}")
                    return None

                data = await response.json()

                # Parse response - Binance returns list of all trading pairs
                prices = {item["symbol"]: float(item["price"]) for item in data}

                # Extract rates for our currencies
                rates = {
                    "BNB": prices.get("BNBUSDT"),
                    "ETH": prices.get("ETHUSDT"),
                    "TRX": prices.get("TRXUSDT")
                }

                # Validate all rates are present
                if not all(rates.values()):
                    logger.error(f"Missing rates from Binance: {rates}")
                    return None

                logger.info(
                    f"✓ Fetched crypto rates from Binance: BNB={rates['BNB']:.2f}, ETH={rates['ETH']:.2f}, TRX={rates['TRX']:.4f}")
                return rates

    except aiohttp.ClientError as e:
        logger.warning(f"Binance API client error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching from Binance: {e}", exc_info=True)
        return None


async def fetch_from_coingecko() -> Optional[Dict[str, float]]:
    """
    Fetch crypto rates from CoinGecko API (fallback).

    Returns:
        Dictionary with rates: {'BNB': 245.67, 'ETH': 2345.89, 'TRX': 0.12}
        or None if API unavailable
    """
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(API_ENDPOINTS["coingecko"]) as response:
                if response.status != 200:
                    logger.warning(f"CoinGecko API returned status {response.status}")
                    return None

                data = await response.json()

                # Parse response - CoinGecko returns nested structure
                rates = {
                    "BNB": data.get("binancecoin", {}).get("usd"),
                    "ETH": data.get("ethereum", {}).get("usd"),
                    "TRX": data.get("tron", {}).get("usd")
                }

                # Validate all rates are present
                if not all(rates.values()):
                    logger.error(f"Missing rates from CoinGecko: {rates}")
                    return None

                logger.info(
                    f"✓ Fetched crypto rates from CoinGecko: BNB={rates['BNB']:.2f}, ETH={rates['ETH']:.2f}, TRX={rates['TRX']:.4f}")
                return rates

    except aiohttp.ClientError as e:
        logger.warning(f"CoinGecko API client error: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error fetching from CoinGecko: {e}", exc_info=True)
        return None


async def get_crypto_rates() -> Optional[Dict[str, float]]:
    """
    Get crypto rates with smart fallback logic.

    Tries Binance first (faster), falls back to CoinGecko if unavailable.

    Returns:
        Dictionary with rates: {'BNB': 245.67, 'ETH': 2345.89, 'TRX': 0.12}
        or None if both APIs are unavailable

    Usage:
        rates = await get_crypto_rates()
        if rates:
            bnb_usd = rates['BNB']
        else:
            # Handle error - both APIs unavailable
            pass
    """
    # Try Binance first (primary source)
    rates = await fetch_from_binance()
    if rates:
        return rates

    logger.warning("Binance API unavailable, falling back to CoinGecko")

    # Try CoinGecko as fallback
    rates = await fetch_from_coingecko()
    if rates:
        return rates

    # Both APIs failed
    logger.error("❌ All crypto rate APIs unavailable (Binance + CoinGecko)")
    return None


# Export
__all__ = ['get_crypto_rates', 'fetch_from_binance', 'fetch_from_coingecko']