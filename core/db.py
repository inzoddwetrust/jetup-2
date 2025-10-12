# jetup/core/db.py
"""
Database management for Jetup bot.
Simplified version from helpbot - single database.
"""
import logging
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from config import Config
from models.base import Base

logger = logging.getLogger(__name__)

# Database engines
_engine = None
_SessionFactory = None


def get_engine():
    """Get or create database engine."""
    global _engine
    if _engine is None:
        database_url = Config.get(Config.DATABASE_URL, "sqlite:///jetup.db")
        _engine = create_engine(
            database_url,
            echo=False,
            pool_pre_ping=True
        )
        logger.info(f"Database engine created: {database_url}")
    return _engine


def get_session_factory():
    """Get or create session factory."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_engine()
        _SessionFactory = sessionmaker(bind=engine)
        logger.info("Session factory created")
    return _SessionFactory


def get_session() -> Session:
    """
    Get a new database session.

    Returns:
        Session instance
    """
    factory = get_session_factory()
    return factory()


@contextmanager
def get_db_session_ctx():
    """
    Context manager for database sessions.

    Usage:
        with get_db_session_ctx() as session:
            user = session.query(User).first()
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Database error: {e}")
        raise
    finally:
        session.close()


def setup_database():
    """Initialize database - create all tables."""
    logger.info("Setting up database...")
    engine = get_engine()
    Base.metadata.create_all(engine)
    logger.info("Database setup completed")


def drop_all_tables():
    """Drop all tables - USE WITH CAUTION!"""
    logger.warning("Dropping all tables...")
    engine = get_engine()
    Base.metadata.drop_all(engine)
    logger.info("All tables dropped")