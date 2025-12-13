# bot/config/base.py
"""
Base model and mixins for all database tables.
"""
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, BigInteger, String, DateTime

Base = declarative_base()

def _get_current_time():
    """Lazy import to avoid circular dependency."""
    from mlm_system.utils.time_machine import timeMachine
    return timeMachine.now

class AuditMixin:
    ownerTelegramID = Column(BigInteger, nullable=True, index=True)
    ownerEmail = Column(String, nullable=True, index=True)

    createdAt = Column(DateTime, default=_get_current_time)
    updatedAt = Column(DateTime, default=_get_current_time, onupdate=_get_current_time)