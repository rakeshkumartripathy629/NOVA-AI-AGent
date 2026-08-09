"""memory_system: memory items schema, categories, conversation summaries

Revision ID: a1b2c3d4e5f6
Revises: 5fd86d8e7958
Create Date: 2026-08-09

Adds the long-term memory tables/enum/columns:
  * memorycategory enum (all categories incl. new ones)
  * memory_items (embedding, confidence, superseded_by_id)
  * conversation_summaries
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a1b2c3d4e5f6"
down_revision = "5fd86d8e7958"
branch_labels = None
depends_on = None


MEMORY_CATEGORIES = (
    "PROFILE",
    "SKILLS",
    "EDUCATION",
    "WORK_EXPERIENCE",
    "PROJECT",
    "GOALS",
    "INTERESTS",
    "PREFERENCE",
    "TECHNICAL_PREFERENCE",
    "PAST_EVENT",
    "FACT",
    "TOPIC",
)


def upgrade() -> None:
    memorycategory = postgresql.ENUM(
        *MEMORY_CATEGORIES, name="memorycategory", create_type=False
    )
    memorycategory.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "memory_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True), nullable=False, index=True
        ),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True), nullable=True, index=True
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "category",
            memorycategory,
            nullable=False,
            server_default="FACT",
            index=True,
        ),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "confidence",
            sa.Float(),
            nullable=False,
            server_default="0.8",
        ),
        sa.Column("embedding", postgresql.JSONB(), nullable=True),
        sa.Column(
            "source_conversation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            index=True,
        ),
        sa.Column("source_message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "superseded_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
            index=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_memory_items_user_content", "memory_items", ["user_id", "content"]
    )

    op.create_table(
        "conversation_summaries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "organization_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message_end_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("token_estimate", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("embedding", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("conversation_id", name="uq_conversation_summaries_conversation"),
    )
    op.create_index(
        "ix_conversation_summaries_conversation_id",
        "conversation_summaries",
        ["conversation_id"],
    )
    op.create_index(
        "ix_conversation_summaries_user_id", "conversation_summaries", ["user_id"]
    )
    op.create_index(
        "ix_conversation_summaries_user_updated",
        "conversation_summaries",
        ["user_id", "updated_at"],
    )


def downgrade() -> None:
    op.drop_table("conversation_summaries")
    op.drop_table("memory_items")
    op.execute("DROP TYPE IF EXISTS memorycategory")
