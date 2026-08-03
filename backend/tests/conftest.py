"""Shared pytest fixtures for the Nova AI backend.

Env vars are set before any application import so the cached settings object
picks up the test configuration.
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/nova_ai_test")
os.environ.setdefault("TESTING", "true")
os.environ.setdefault("ENVIRONMENT", "testing")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("FIRST_SUPERUSER_PASSWORD", "test-superuser-pass")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/1")

from pathlib import Path  # noqa: E402

import asyncpg  # noqa: E402
import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config as AlembicConfig  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
TEST_DB_NAME = "nova_ai_test"


async def _ensure_test_db() -> None:
    conn = await asyncpg.connect("postgresql://postgres:postgres@127.0.0.1:5432/postgres")
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME)
        if not exists:
            await conn.execute(f"CREATE DATABASE {TEST_DB_NAME}")
    finally:
        await conn.close()


@pytest.fixture(scope="session", autouse=True)
def prepare_test_db() -> None:
    """Create the test database and bring it to head with Alembic."""
    import asyncio

    asyncio.run(_ensure_test_db())

    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])
    command.upgrade(cfg, "head")


@pytest.fixture
async def db_session():
    """Yield an async database session for the test database."""
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        yield db


@pytest.fixture
async def api_client():
    """Yield an ASGI test client that does not run app lifespan."""
    import httpx

    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def superuser(db_session):
    """Create and return a superuser for tests that need one."""
    from uuid import uuid4

    from app.core.security import get_password_hash
    from app.models import AuthProvider, User, UserRole, UserStatus

    async def _create(email: str | None = None) -> User:
        user = User(
            email=email or f"user-{uuid4().hex[:12]}@test.dev",
            username=f"tester-{uuid4().hex[:10]}",
            full_name="Test User",
            hashed_password=get_password_hash("test-password"),
            role=UserRole.USER,
            status=UserStatus.ACTIVE,
            auth_provider=AuthProvider.LOCAL,
            email_verified=True,
            is_active=True,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _create
