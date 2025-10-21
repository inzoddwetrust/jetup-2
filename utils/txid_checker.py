"""
TXID validation and blockchain transaction verification.
"""
import re
import aiohttp
import logging
import json
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple

from config import Config

logger = logging.getLogger(__name__)


class TxidValidationCode(Enum):
    """TXID validation result codes."""
    VALID_TRANSACTION = "valid"
    INVALID_PREFIX = "invalid_prefix"
    INVALID_LENGTH = "invalid_length"
    INVALID_CHARS = "invalid_chars"
    UNSUPPORTED_METHOD = "unsupported_method"
    TRANSACTION_NOT_FOUND = "tx_not_found"
    WRONG_RECIPIENT = "wrong_recipient"
    WRONG_NETWORK = "wrong_network"
    API_ERROR = "api_error"
    TXID_ALREADY_USED = "already_used"
    NEEDS_CONFIRMATION = "needs_confirm"


# Template mapping for TXID validation errors
TXID_TEMPLATE_MAPPING = {
    TxidValidationCode.VALID_TRANSACTION: 'txid_success',
    TxidValidationCode.INVALID_PREFIX: 'txid_invalid_format',
    TxidValidationCode.INVALID_LENGTH: 'txid_invalid_format',
    TxidValidationCode.INVALID_CHARS: 'txid_invalid_format',
    TxidValidationCode.UNSUPPORTED_METHOD: 'txid_unsupported_method',
    TxidValidationCode.TRANSACTION_NOT_FOUND: 'txid_not_found',
    TxidValidationCode.WRONG_RECIPIENT: 'txid_wrong_recipient',
    TxidValidationCode.WRONG_NETWORK: 'txid_wrong_network',
    TxidValidationCode.API_ERROR: 'txid_api_error',
    TxidValidationCode.TXID_ALREADY_USED: 'txid_already_used',
    TxidValidationCode.NEEDS_CONFIRMATION: 'txid_needs_confirmation'
}


@dataclass
class ValidationResult:
    """Result of TXID validation."""
    code: TxidValidationCode
    details: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None


def validate_txid(txid: str, method: str) -> ValidationResult:
    """
    Validates TXID format based on payment method.

    Args:
        txid: Transaction ID
        method: Payment method (ETH, BNB, USDT-TRC20, etc.)

    Returns:
        ValidationResult with code and optional details
    """
    txid = txid.lower().strip()

    if method in ["ETH", "BNB", "USDT-ERC20", "USDT-BSC20"]:
        if not txid.startswith("0x"):
            return ValidationResult(TxidValidationCode.INVALID_PREFIX)
        if len(txid) != 66:
            return ValidationResult(TxidValidationCode.INVALID_LENGTH)
        if not re.match(r"^0x[0-9a-f]{64}$", txid):
            return ValidationResult(TxidValidationCode.INVALID_CHARS)

    elif method in ["TRX", "USDT-TRC20"]:
        if len(txid) != 64:
            return ValidationResult(TxidValidationCode.INVALID_LENGTH)
        if not re.match(r"^[0-9a-f]{64}$", txid):
            return ValidationResult(TxidValidationCode.INVALID_CHARS)

    else:
        return ValidationResult(TxidValidationCode.UNSUPPORTED_METHOD)

    return ValidationResult(TxidValidationCode.VALID_TRANSACTION)


async def verify_transaction(txid: str, method: str, expected_address: str) -> ValidationResult:
    """
    Verifies transaction details using blockchain APIs.
    Uses Etherscan API V2 for all EVM chains.

    Args:
        txid: Transaction ID
        method: Payment method
        expected_address: Expected recipient address (our wallet)

    Returns:
        ValidationResult with transaction details
    """
    try:
        logger.info(f"Starting verification for txid: {txid}, method: {method}")
        logger.info(f"Expected recipient address: {expected_address}")

        # Route to appropriate verifier based on method
        if method == "ETH":
            result = await _verify_native_evm_transaction(txid, chain_id=1)
        elif method == "BNB":
            result = await _verify_native_evm_transaction(txid, chain_id=56)
        elif method == "USDT-ERC20":
            result = await _verify_erc20_token_transaction(txid, chain_id=1)
        elif method == "USDT-BSC20":
            result = await _verify_erc20_token_transaction(txid, chain_id=56)
        elif method in ["TRX", "USDT-TRC20"]:
            result = await _verify_tron_transaction(txid)
        else:
            return ValidationResult(TxidValidationCode.UNSUPPORTED_METHOD)

        logger.info(f"Verification result: {result}")

        if result is None:
            return ValidationResult(TxidValidationCode.TRANSACTION_NOT_FOUND)

        from_addr, to_addr = result

        # Check recipient address
        if to_addr.lower() != expected_address.lower():
            logger.warning(f"Wrong recipient! Expected: {expected_address}, Got: {to_addr}")
            return ValidationResult(
                TxidValidationCode.WRONG_RECIPIENT,
                from_address=from_addr,
                to_address=to_addr
            )

        return ValidationResult(
            TxidValidationCode.VALID_TRANSACTION,
            from_address=from_addr,
            to_address=to_addr
        )

    except Exception as e:
        logger.error(f"Error verifying transaction {txid}: {e}", exc_info=True)
        return ValidationResult(TxidValidationCode.API_ERROR, details=str(e))


async def _verify_native_evm_transaction(txid: str, chain_id: int) -> Optional[Tuple[str, str]]:
    """
    Verifies native coin transactions (ETH, BNB) using Etherscan API V2.
    For native coins, we check the 'to' field directly.

    Args:
        txid: Transaction ID
        chain_id: Chain ID (1 for Ethereum, 56 for BSC)

    Returns:
        Tuple of (from_address, to_address) or None if not found
    """
    url = "https://api.etherscan.io/v2/api"

    params = {
        "chainid": chain_id,
        "module": "proxy",
        "action": "eth_getTransactionByHash",
        "txhash": txid,
        "apikey": Config.get(Config.ETHERSCAN_API_KEY)
    }

    logger.info(f"V2 API request for native coin - Chain: {chain_id}, TXID: {txid}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                try:
                    data = await response.json()

                    if data.get("status") == "0":
                        logger.error(f"V2 API error: {data.get('message')}")
                        return None

                    result = data.get("result")

                    if result and isinstance(result, dict):
                        from_address = result.get("from")
                        to_address = result.get("to")

                        logger.info(f"Native transaction - from: {from_address}, to: {to_address}")

                        if from_address and to_address:
                            return from_address, to_address

                except Exception as e:
                    logger.error(f"Error parsing V2 API response: {e}", exc_info=True)

    return None


async def _verify_erc20_token_transaction(txid: str, chain_id: int) -> Optional[Tuple[str, str]]:
    """
    Verifies ERC20/BEP20 token transactions (USDT) using Etherscan API V2.
    For tokens, we need to decode the input data or use transaction receipt logs.

    Args:
        txid: Transaction ID
        chain_id: Chain ID (1 for Ethereum, 56 for BSC)

    Returns:
        Tuple of (from_address, to_address) or None if not found
    """
    url = "https://api.etherscan.io/v2/api"

    # First, get transaction receipt to access logs
    params = {
        "chainid": chain_id,
        "module": "proxy",
        "action": "eth_getTransactionReceipt",
        "txhash": txid,
        "apikey": Config.get(Config.ETHERSCAN_API_KEY)
    }

    logger.info(f"V2 API request for token transfer - Chain: {chain_id}, TXID: {txid}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                try:
                    data = await response.json()

                    if data.get("status") == "0":
                        logger.error(f"V2 API error: {data.get('message')}")
                        return None

                    result = data.get("result")

                    if result and isinstance(result, dict):
                        from_address = result.get("from")
                        logs = result.get("logs", [])

                        # Look for Transfer event in logs
                        # Transfer event signature: 0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef
                        transfer_topic = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

                        for log in logs:
                            topics = log.get("topics", [])
                            if len(topics) >= 3 and topics[0] == transfer_topic:
                                # topics[1] = from (padded to 32 bytes)
                                # topics[2] = to (padded to 32 bytes)
                                # Extract addresses from topics (remove 0x prefix and padding)
                                to_address = "0x" + topics[2][-40:]  # Last 40 chars are the address

                                logger.info(f"Token transfer - from: {from_address}, to: {to_address}")
                                return from_address, to_address

                        # Alternative: Try to decode input data
                        # Get the transaction details
                        tx_params = {
                            "chainid": chain_id,
                            "module": "proxy",
                            "action": "eth_getTransactionByHash",
                            "txhash": txid,
                            "apikey": Config.get(Config.ETHERSCAN_API_KEY)
                        }

                        async with session.get(url, params=tx_params) as tx_response:
                            if tx_response.status == 200:
                                tx_data = await tx_response.json()
                                tx_result = tx_data.get("result", {})

                                if tx_result and isinstance(tx_result, dict):
                                    input_data = tx_result.get("input", "")

                                    # Check if it's a transfer function (0xa9059cbb)
                                    if input_data.startswith("0xa9059cbb"):
                                        # Extract recipient address from input data
                                        # Format: 0xa9059cbb + 32 bytes address + 32 bytes amount
                                        if len(input_data) >= 138:  # 10 + 64 + 64
                                            # Extract recipient (skip method id and padding)
                                            to_address = "0x" + input_data[34:74]

                                            logger.info(
                                                f"Token transfer from input - from: {from_address}, to: {to_address}")
                                            return from_address, to_address

                except Exception as e:
                    logger.error(f"Error parsing token transaction: {e}", exc_info=True)

    return None


async def _verify_tron_transaction(txid: str) -> Optional[Tuple[str, str]]:
    """
    Verifies TRON transaction.
    TRON is not EVM, so we keep using their native API.

    Args:
        txid: Transaction ID

    Returns:
        Tuple of (from_address, to_address) or None if not found
    """
    url = "https://apilist.tronscan.org/api/transaction-info"
    params = {"hash": txid}

    logger.info(f"TRON API request for txid: {txid}")

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                try:
                    text = await response.text()
                    logger.info(f"TRON API raw response: {text[:500]}")

                    data = json.loads(text)

                    if isinstance(data, dict):
                        # TRX transfer
                        if data.get("contractType") == 1:
                            from_addr = data.get("ownerAddress")
                            to_addr = data.get("toAddress")
                            if from_addr and to_addr:
                                return from_addr, to_addr

                        # TRC20 transfer
                        elif data.get("contractType") == 31:
                            if data.get("trc20TransferInfo"):
                                transfers = data["trc20TransferInfo"]
                                if transfers and isinstance(transfers, list):
                                    transfer = transfers[0]
                                    from_addr = transfer.get("from_address")
                                    to_addr = transfer.get("to_address")
                                    if from_addr and to_addr:
                                        return from_addr, to_addr

                except Exception as e:
                    logger.error(f"Error parsing TRON response: {e}", exc_info=True)

    return None