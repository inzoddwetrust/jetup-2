# models/volume_queue.py
"""
Queue for volume recalculation tasks.
Will be replaced with Redis in microservices architecture.
"""
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timezone
from models.base import Base


class VolumeUpdateTask(Base):
    """Volume update task queue."""
    __tablename__ = 'volume_update_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, nullable=False, index=True)
    priority = Column(Integer, default=0, index=True)
    status = Column(String(20), default='pending', index=True)
    createdAt = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    startedAt = Column(DateTime, nullable=True)
    completedAt = Column(DateTime, nullable=True)
    attempts = Column(Integer, default=0)
    lastError = Column(String, nullable=True)

    def __repr__(self):
        return f"<VolumeUpdateTask(userId={self.userId}, status={self.status})>"