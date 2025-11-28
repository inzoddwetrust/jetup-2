# models/mlm/system_time.py
"""
SystemTime model - virtual time for testing + scheduler state persistence.
"""
from sqlalchemy import Column, Integer, String, DateTime, Boolean, JSON
from datetime import datetime, timezone
from models.base import Base


class SystemTime(Base):
    __tablename__ = 'system_time'

    timeID = Column(Integer, primary_key=True, autoincrement=True)

    # Time settings
    realTime = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    virtualTime = Column(DateTime, nullable=True)
    isTestMode = Column(Boolean, default=False)

    # Metadata
    createdBy = Column(Integer, nullable=True)  # Admin userID
    notes = Column(String, nullable=True)  # "Testing Grace Day", etc.

    # Scheduler state persistence (survives bot restarts)
    schedulerState = Column(JSON, nullable=True)
    # Structure:
    # {
    #   "2024-12": {"day1": true, "day2": true, "day3": true, "day5": true},
    #   "2025-01": {"day1": false, "day2": false, "day3": false, "day5": false}
    # }

    def __repr__(self):
        return f"<SystemTime(test={self.isTestMode}, virtual={self.virtualTime})>"