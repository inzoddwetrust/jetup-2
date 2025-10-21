# models/volume_queue.py
"""
Queue for volume recalculation tasks.
Will be replaced with Redis in microservices architecture.
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime, timezone
from init import Base


class VolumeUpdateTask(Base):
    """Volume update task queue."""
    __tablename__ = 'volume_update_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, nullable=False, index=True)
    priority = Column(Integer, default=0, index=True)  # Higher = first
    status = Column(String(20), default='pending', index=True)  # pending, processing, completed, failed
    createdAt = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    startedAt = Column(DateTime, nullable=True)
    completedAt = Column(DateTime, nullable=True)
    attempts = Column(Integer, default=0)
    lastError = Column(String, nullable=True)

    def __repr__(self):
        return f"<VolumeUpdateTask(userId={self.userId}, status={self.status})>"