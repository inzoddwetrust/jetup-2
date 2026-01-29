# tests/conftest.py
"""
Pytest configuration and shared fixtures for balance listeners tests.

Run:
    pytest tests/test_balance_listeners.py -v
    pytest tests/test_balance_listeners.py -v --full-reconciliation
"""
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from config import Config
from models import User, ActiveBalance, PassiveBalance
from models.option import Option
from models.listeners import register_all_listeners

# =============================================================================
# INITIALIZE CONFIG
# =============================================================================

Config.initialize_from_env()

# =============================================================================
# CONSTANTS
# =============================================================================

USER_IDS = {
    'primary': 33,
    'sender': 48,
    'recipient': 132,
    'buyer': 283
}

TEST_OPTION = {
    'optionID': 25,
    'projectID': 2
}


# =============================================================================
# PYTEST OPTIONS
# =============================================================================

def pytest_addoption(parser):
    """Add custom CLI options for tests."""
    parser.addoption(
        "--full-reconciliation",
        action="store_true",
        default=False,
        help="Check ALL users for balance discrepancies, not just test users"
    )


# =============================================================================
# DATABASE FIXTURES
# =============================================================================

@pytest.fixture(scope="session")
def engine():
    """Create database engine for test session."""
    database_url = Config.get(Config.DATABASE_URL)
    return create_engine(database_url)


@pytest.fixture(scope="session", autouse=True)
def setup_listeners():
    """Register listeners once at test session start."""
    register_all_listeners()


@pytest.fixture
def session(engine):
    """Create database session for each test."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# =============================================================================
# USER FIXTURES
# =============================================================================

@pytest.fixture
def primary_user(session):
    """Primary test user (userID=33)."""
    user = session.query(User).filter_by(userID=USER_IDS['primary']).first()
    assert user is not None, f"User {USER_IDS['primary']} not found in test DB"
    return user


@pytest.fixture
def sender(session):
    """Sender for transfer tests (userID=48)."""
    user = session.query(User).filter_by(userID=USER_IDS['sender']).first()
    assert user is not None, f"User {USER_IDS['sender']} not found in test DB"
    return user


@pytest.fixture
def recipient(session):
    """Recipient for transfer tests (userID=132)."""
    user = session.query(User).filter_by(userID=USER_IDS['recipient']).first()
    assert user is not None, f"User {USER_IDS['recipient']} not found in test DB"
    return user


@pytest.fixture
def buyer(session):
    """Buyer for purchase tests (userID=283)."""
    user = session.query(User).filter_by(userID=USER_IDS['buyer']).first()
    assert user is not None, f"User {USER_IDS['buyer']} not found in test DB"
    return user


# =============================================================================
# OPTION FIXTURE
# =============================================================================

@pytest.fixture
def test_option(session):
    """Test option for purchase tests (optionID=25)."""
    option = session.query(Option).filter_by(optionID=TEST_OPTION['optionID']).first()
    assert option is not None, f"Option {TEST_OPTION['optionID']} not found in test DB"
    return option


# =============================================================================
# HELPER FIXTURES
# =============================================================================

@pytest.fixture
def unique_reason():
    """Generate unique reason string for test records."""

    def _generate(prefix="test"):
        return f"{prefix}_{uuid.uuid4().hex[:8]}"

    return _generate


@pytest.fixture
def calc_journal_sum(session):
    """
    Calculator for real journal sum.

    Returns dict with 'active' and 'passive' functions.
    Each function takes userID and returns SUM(amount) WHERE status='done'.
    """

    def _calc_active(user_id: int) -> Decimal:
        result = session.query(
            func.coalesce(func.sum(ActiveBalance.amount), 0)
        ).filter(
            ActiveBalance.userID == user_id,
            ActiveBalance.status == 'done'
        ).scalar()
        return Decimal(str(result))

    def _calc_passive(user_id: int) -> Decimal:
        result = session.query(
            func.coalesce(func.sum(PassiveBalance.amount), 0)
        ).filter(
            PassiveBalance.userID == user_id,
            PassiveBalance.status == 'done'
        ).scalar()
        return Decimal(str(result))

    return {'active': _calc_active, 'passive': _calc_passive}


@pytest.fixture
def reconciliation_user_ids(request):
    """
    Returns user IDs for reconciliation scope.

    Default: test users only [33, 48, 132, 283]
    With --full-reconciliation: None (scan all users)
    """
    if request.config.getoption("--full-reconciliation"):
        return None
    return list(USER_IDS.values())