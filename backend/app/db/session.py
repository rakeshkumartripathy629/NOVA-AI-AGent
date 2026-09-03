"""
Database session management and lifecycle.

The async engine and session factory are created once and reused. In
development/testing a connection-less pool is used so SQLite / ephemeral
backends don't leak connections.
"""
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.logging import get_logger


logger = get_logger("db.session")


class Base(DeclarativeBase):
    """Base class for ORM models (SQLAlchemy 2 style)."""


def _build_engine() -> AsyncEngine:
    kwargs: dict = {
        "echo": settings.DB_ECHO,
        "pool_pre_ping": True,
        "pool_recycle": settings.DB_POOL_RECYCLE,
    }
    # Always use connection pooling for speed (even in dev)
    kwargs.update(
        {
            "pool_size": settings.DB_POOL_SIZE if settings.is_production else 5,
            "max_overflow": settings.DB_MAX_OVERFLOW if settings.is_production else 10,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
        }
    )
    return create_async_engine(settings.DATABASE_URL, **kwargs)


# Global engine and session factory
engine: Optional[AsyncEngine] = None
async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None


def get_engine() -> AsyncEngine:
    """Return the shared engine, creating it on first use."""
    global engine
    if engine is None:
        engine = _build_engine()
    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the shared async session factory."""
    global async_session_maker
    if async_session_maker is None:
        async_session_maker = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )
    return async_session_maker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding a database session."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """Context manager yielding a session outside of FastAPI (workers, tests)."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Create all tables if they don't exist and run first-run seeding."""
    from app.db.seed import seed_all

    engine = get_engine()
    # Import models to register metadata
    from app.models import Base as ModelBase  # noqa: F401

    # Step 1: Create all tables (works on fresh DB and existing DB)
    async with engine.begin() as conn:
        try:
            await conn.run_sync(ModelBase.metadata.create_all)
            logger.info("Database tables created/verified via create_all")
        except ProgrammingError as exc:
            if "already exists" in str(exc):
                logger.info("Database tables already exist, skipping create_all")
            else:
                # Some other error — log but don't crash, try to continue
                logger.warning("create_all error (non-fatal): %s", exc)
        except Exception as exc:
            logger.warning("create_all unexpected error: %s", exc)

    # Step 2: Verify tables exist by checking a critical table
    async with engine.begin() as conn:
        try:
            from sqlalchemy import text
            result = await conn.execute(text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"))
            tables_exist = result.scalar()
            if tables_exist:
                logger.info("Verified: users table exists")
            else:
                logger.error("CRITICAL: users table does NOT exist after create_all!")
        except Exception as exc:
            logger.warning("Table verification failed: %s", exc)

    # Step 3: Memory feature additions
    try:
        from app.db.ensure_schema import ensure_memory_schema
        await ensure_memory_schema()
    except Exception:  # noqa: BLE001
        logger.warning("Memory schema ensure failed (non-fatal): %s")

    # Step 4: Seed (only if tables exist)
    try:
        await seed_all()
    except Exception as exc:
        logger.warning("Seed failed (non-fatal, tables may already be seeded): %s", exc)


async def close_db() -> None:
    """Dispose of the shared engine."""
    global engine, async_session_maker
    if engine is not None:
        await engine.dispose()
        engine = None
        async_session_maker = None


async def check_db_connection() -> bool:
    """Return True if the database is reachable."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
