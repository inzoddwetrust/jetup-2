# utils/wallet_validator.py
"""
Wallet address validation utilities.
Supports TRC20 (TRON) addresses for withdrawal functionality.
"""
import re
import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class WalletValidationCode(Enum):
    """Validation result codes for wallet addresses."""
    VALID = "valid"
    INVALID_PREFIX = "invalid_prefix"  # Doesn't start with expected prefix
    INVALID_LENGTH = "invalid_length"  # Wrong number of characters
    INVALID_CHARS = "invalid_chars"  # Contains invalid characters
    EMPTY = "empty"  # Empty or None input


@dataclass
class WalletValidationResult:
    """Result of wallet address validation."""
    code: WalletValidationCode
    details: str = None

    @property
    def is_valid(self) -> bool:
        """Check if validation passed."""
        return self.code == WalletValidationCode.VALID


# =============================================================================
# TRC20 (TRON) VALIDATION
# =============================================================================

# Base58 alphabet (excludes 0, O, I, l to avoid confusion)
BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# TRC20 address pattern: T + 33 Base58 characters = 34 total
TRC20_PATTERN = re.compile(f"^T[{BASE58_ALPHABET}]{{33}}$")


def validate_trc20_address(address: str) -> WalletValidationResult:
    """
    Validate TRC20 (TRON) wallet address.

    TRC20 address rules:
    - Starts with 'T'
    - Exactly 34 characters total
    - Only Base58 characters (no 0, O, I, l)

    Args:
        address: Wallet address to validate

    Returns:
        WalletValidationResult with code and optional details

    Examples:
        >>> validate_trc20_address("TJYeasTPa6gpBZEgKso8R79RNEQ5GRgvz3")
        WalletValidationResult(code=VALID)

        >>> validate_trc20_address("0x123...")
        WalletValidationResult(code=INVALID_PREFIX, details="...")
    """
    # Handle empty input
    if not address:
        return WalletValidationResult(
            WalletValidationCode.EMPTY,
            "Address is empty"
        )

    # Strip whitespace
    address = address.strip()

    # Check empty after strip
    if not address:
        return WalletValidationResult(
            WalletValidationCode.EMPTY,
            "Address is empty"
        )

    # Check prefix
    if not address.startswith('T'):
        return WalletValidationResult(
            WalletValidationCode.INVALID_PREFIX,
            "TRC20 address must start with 'T'"
        )

    # Check length
    if len(address) != 34:
        return WalletValidationResult(
            WalletValidationCode.INVALID_LENGTH,
            f"TRC20 address must be 34 characters, got {len(address)}"
        )

    # Check characters (full regex match)
    if not TRC20_PATTERN.match(address):
        # Find invalid characters for better error message
        invalid_chars = []
        for i, char in enumerate(address[1:], start=1):  # Skip 'T' prefix
            if char not in BASE58_ALPHABET:
                invalid_chars.append(f"'{char}' at position {i + 1}")

        if invalid_chars:
            details = f"Invalid characters: {', '.join(invalid_chars[:3])}"
            if len(invalid_chars) > 3:
                details += f" and {len(invalid_chars) - 3} more"
        else:
            details = "Address contains invalid characters"

        return WalletValidationResult(
            WalletValidationCode.INVALID_CHARS,
            details
        )

    logger.debug(f"TRC20 address validated: {address[:8]}...{address[-4:]}")
    return WalletValidationResult(WalletValidationCode.VALID)


# =============================================================================
# GENERIC VALIDATION (for future expansion)
# =============================================================================

def validate_wallet_address(address: str, network: str) -> WalletValidationResult:
    """
    Validate wallet address for specified network.

    Currently supported networks:
    - TRC20 / TRON / USDT-TRC20

    Args:
        address: Wallet address to validate
        network: Network name (case-insensitive)

    Returns:
        WalletValidationResult

    Raises:
        ValueError: If network is not supported
    """
    network_upper = network.upper().strip()

    # TRC20 variants
    if network_upper in ('TRC20', 'TRON', 'USDT-TRC20', 'TRX'):
        return validate_trc20_address(address)

    # Future: Add ERC20, BEP20, etc.
    # if network_upper in ('ERC20', 'ETH', 'USDT-ERC20'):
    #     return validate_erc20_address(address)

    raise ValueError(f"Unsupported network: {network}")


__all__ = [
    'WalletValidationCode',
    'WalletValidationResult',
    'validate_trc20_address',
    'validate_wallet_address',
]