"""Database connection management.

This module provides database connection management using SQLAlchemy,
including connection pooling, session management, and configuration
from environment variables.
"""

import os
from contextlib import contextmanager
from typing import Generator, Optional

import structlog
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

logger = structlog.get_logger()

# Global engine and session factory
_engine: Optional[Engine] = None
_SessionFactory: Optional[sessionmaker] = None


def get_database_url() -> str:
    """Get database URL from environment variables.

    Returns:
        PostgreSQL connection URL.

    Raises:
        ValueError: If database URL is not configured.
    """
    # First try DATABASE_URL
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Build from individual components
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "opendoor")
    password = os.getenv("POSTGRES_PASSWORD", "")
    database = os.getenv("POSTGRES_DB", "opendoor_data")

    if not password:
        raise ValueError(
            "Database password not configured. Set DATABASE_URL or POSTGRES_PASSWORD."
        )

    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def get_engine(
    database_url: Optional[str] = None,
    pool_size: int = 10,
    max_overflow: int = 20,
    pool_recycle: int = 3600,
    echo: bool = False,
) -> Engine:
    """Get or create the SQLAlchemy engine.

    Args:
        database_url: Database connection URL (uses env vars if not provided).
        pool_size: Number of connections to keep in pool.
        max_overflow: Maximum overflow connections beyond pool_size.
        pool_recycle: Seconds before recycling connections.
        echo: Whether to log all SQL statements.

    Returns:
        SQLAlchemy Engine instance.
    """
    global _engine

    if _engine is not None:
        return _engine

    if database_url is None:
        database_url = get_database_url()

    # Get pool settings from environment
    pool_size = int(os.getenv("DATABASE_POOL_SIZE", pool_size))
    max_overflow = int(os.getenv("DATABASE_MAX_OVERFLOW", max_overflow))

    logger.info(
        "creating_database_engine",
        pool_size=pool_size,
        max_overflow=max_overflow,
    )

    _engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_recycle=pool_recycle,
        pool_pre_ping=True,  # Verify connections before use
        echo=echo,
    )

    # Log connection events
    @event.listens_for(_engine, "connect")
    def on_connect(dbapi_conn, connection_record):
        logger.debug("database_connection_established")

    @event.listens_for(_engine, "checkout")
    def on_checkout(dbapi_conn, connection_record, connection_proxy):
        logger.debug("database_connection_checkout")

    return _engine


def get_session_factory() -> sessionmaker:
    """Get or create the session factory.

    Returns:
        SQLAlchemy sessionmaker instance.
    """
    global _SessionFactory

    if _SessionFactory is not None:
        return _SessionFactory

    engine = get_engine()
    _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)

    return _SessionFactory


def get_session() -> Session:
    """Create a new database session.

    Returns:
        SQLAlchemy Session instance.
    """
    factory = get_session_factory()
    return factory()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Provide a transactional scope around a series of operations.

    Yields:
        SQLAlchemy Session instance.

    Example:
        >>> with session_scope() as session:
        ...     session.execute(text("SELECT 1"))
        ...     session.commit()
    """
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_connection() -> bool:
    """Check if database connection is working.

    Returns:
        True if connection successful, False otherwise.
    """
    try:
        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("database_connection_check_passed")
        return True
    except Exception as e:
        logger.error("database_connection_check_failed", error=str(e))
        return False


def close_engine():
    """Close the database engine and clean up connections."""
    global _engine, _SessionFactory

    if _engine is not None:
        _engine.dispose()
        _engine = None
        _SessionFactory = None
        logger.info("database_engine_closed")


def reset_engine():
    """Reset the engine (useful for testing)."""
    close_engine()
