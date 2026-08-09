"""
Conversation summary model.

Long conversations are summarized so the assistant can recall "what we
discussed" from an old conversation without shipping the full history to the
LLM. Summaries are embedded and searched alongside long-term memories.
"""
from __future__ import annotations

from typing import Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class ConversationSummary(BaseModel):
    """A rolling summary of a conversation, scoped to its owner."""

    __tablename__ = "conversation_summaries"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    organization_id: Mapped[Optional[UUID]] = mapped_column(
        index=True, nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    message_end_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    token_estimate: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    embedding: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "conversation_id", name="uq_conversation_summaries_conversation"
        ),
        Index("ix_conversation_summaries_user_updated", "user_id", "updated_at"),
    )
