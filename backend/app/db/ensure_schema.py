"""
Best-effort schema upgrades for the long-term memory feature.

``init_db`` only runs ``create_all`` when the schema is brand-new; existing
databases skip it, so new columns/enum values/tables must be added here.
All statements use ``IF NOT EXISTS`` so they are idempotent across restarts.
"""
from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("db.ensure_schema")

_NEW_MEMORY_CATEGORIES = (
    "PROFILE",
    "SKILLS",
    "EDUCATION",
    "WORK_EXPERIENCE",
    "GOALS",
    "INTERESTS",
    "TECHNICAL_PREFERENCE",
    "PAST_EVENT",
)

_CONVERSATION_SUMMARIES_DDL = """
CREATE TABLE IF NOT EXISTS conversation_summaries (
    id               UUID PRIMARY KEY,
    conversation_id  UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    user_id          UUID NOT NULL,
    organization_id  UUID,
    summary          TEXT NOT NULL,
    message_count    INTEGER NOT NULL DEFAULT 0,
    message_end_id   UUID,
    token_estimate   INTEGER NOT NULL DEFAULT 0,
    embedding        JSONB,
    created_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    updated_at       TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
    is_deleted       BOOLEAN NOT NULL DEFAULT false,
    deleted_at       TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_conversation_summaries_conversation UNIQUE (conversation_id)
);
CREATE INDEX IF NOT EXISTS ix_conversation_summaries_conversation_id
    ON conversation_summaries (conversation_id);
CREATE INDEX IF NOT EXISTS ix_conversation_summaries_user_id
    ON conversation_summaries (user_id);
CREATE INDEX IF NOT EXISTS ix_conversation_summaries_user_updated
    ON conversation_summaries (user_id, updated_at);
"""


async def ensure_memory_schema() -> None:
    """Add missing memory columns, enum values and tables (idempotent)."""
    try:
        import asyncpg

        dsn = settings.DATABASE_URL_SYNC
        conn = await asyncpg.connect(dsn, timeout=10)
        try:
            for value in _NEW_MEMORY_CATEGORIES:
                await conn.execute(
                    f"ALTER TYPE memorycategory ADD VALUE IF NOT EXISTS '{value}'"
                )
            await conn.execute(
                "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS embedding JSONB"
            )
            await conn.execute(
                "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS "
                "confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8"
            )
            await conn.execute(
                "ALTER TABLE memory_items ADD COLUMN IF NOT EXISTS "
                "superseded_by_id UUID"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS ix_memory_items_superseded_by "
                "ON memory_items (superseded_by_id) WHERE superseded_by_id IS NOT NULL"
            )
            await conn.execute(_CONVERSATION_SUMMARIES_DDL)
            logger.info("Memory schema ensured (columns, enum, summaries table)")
        finally:
            await conn.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory schema ensure failed (continuing): %s", exc)
