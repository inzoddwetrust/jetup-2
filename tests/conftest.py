# tests/conftest.py
"""
Pytest configuration and shared fixtures.
"""
import pytest

# Initialize Config from .env BEFORE any tests run
from config import Config
Config.initialize_from_env()


def pytest_addoption(parser):
    """Add custom CLI options for tests."""
    parser.addoption(
        "--full-reconciliation",
        action="store_true",
        default=False,
        help="Check ALL users for balance discrepancies, not just test users"
    )