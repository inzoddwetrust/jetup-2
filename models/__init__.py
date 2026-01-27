"""
Database models for Jetup bot.
Import all models here for backwards compatibility and easy access.
"""

# Base and mixins
from models.base import Base, AuditMixin

# Core models
from models.user import User
from models.purchase import Purchase
from models.payment import Payment
from models.bonus import Bonus
from models.transfer import Transfer
from models.active_balance import ActiveBalance
from models.passive_balance import PassiveBalance
from models.project import Project
from models.option import Option
from models.notification import Notification, NotificationDelivery
from models.legacy_migration import LegacyMigrationV1, LegacyMigrationV2

# MLM models
from models.mlm.rank_history import RankHistory
from models.mlm.monthly_stats import MonthlyStats
from models.mlm.global_pool import GlobalPool
from models.mlm.system_time import SystemTime

# Event listeners
from models.listeners import register_all_listeners

# For backwards compatibility - export all at module level
__all__ = [
    # Base
    'Base',
    'AuditMixin',

    # Core
    'User',
    'Purchase',
    'Payment',
    'Bonus',
    'Transfer',
    'ActiveBalance',
    'PassiveBalance',
    'Project',
    'Option',
    'Notification',
    'NotificationDelivery',
    'LegacyMigrationV1',
    'LegacyMigrationV2',

    # MLM
    'RankHistory',
    'MonthlyStats',
    'GlobalPool',
    'SystemTime',

    # Listeners
    'register_all_listeners',
]