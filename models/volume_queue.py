# models/volume_queue.py
"""
Queue for volume recalculation tasks.
Will be replaced with Redis in microservices architecture.
"""
from sqlalchemy import Column, Integer, String, DateTime
from models.base import Base, _get_current_time


class VolumeUpdateTask(Base):
    """Volume update task queue."""
    __tablename__ = 'volume_update_queue'

    id = Column(Integer, primary_key=True, autoincrement=True)
    userId = Column(Integer, nullable=False, index=True)
    priority = Column(Integer, default=0, index=True)
    status = Column(String(20), default='pending', index=True)
    createdAt = Column(DateTime, default=_get_current_time, index=True)
    startedAt = Column(DateTime, nullable=True)
    completedAt = Column(DateTime, nullable=True)
    attempts = Column(Integer, default=0)
    lastError = Column(String, nullable=True)

    def __repr__(self):
        return f"<VolumeUpdateTask(userId={self.userId}, status={self.status})>"