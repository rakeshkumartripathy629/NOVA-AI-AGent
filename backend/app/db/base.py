"""
Database base configuration.

This module re-exports the shared engine / session factory and provides the
synchronous engine used by Alembic. All runtime session management lives in
:mod:`app.db.session`.
"""
from app.core.config import settings
from app.db.session import (
    Base,
    async_session_maker,
    close_db,
    engine,
    get_db,
    get_db_context,
    get_engine,
    get_session_factory,
    init_db,
)

__all__ = [
    "Base",
    "async_session_maker",
    "close_db",
    "engine",
    "get_db",
    "get_db_context",
    "get_engine",
    "get_session_factory",
    "init_db",
]


def get_sync_engine():
    """Return a synchronous engine for Alembic migrations."""
    from sqlalchemy import create_engine

    return create_engine(
        settings.DATABASE_URL_SYNC,
        echo=settings.DB_ECHO,
        pool_pre_ping=True,
    )


def get_sync_session():
    """Return a synchronous session for Alembic / scripts."""
    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(
        bind=get_sync_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return SessionLocal()


