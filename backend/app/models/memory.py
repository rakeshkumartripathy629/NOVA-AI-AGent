"""
Long-term chat memory model.

Stores durable facts and preferences that the assistant remembers across
conversations (like ChatGPT's memory). Items are extracted automatically from
conversations and can also be added or removed by the user.

Each item stores its embedding vector (JSONB) for semantic retrieval and a
confidence score. When a newer, explicit fact supersedes an older one, the
outdated item is linked via ``superseded_by_id`` so it no longer surfaces.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Float, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class MemoryCategory(str, enum.Enum):
    """Categories of remembered information."""
    PROFILE = "profile"
    SKILLS = "skills"
    EDUCATION = "education"
    WORK_EXPERIENCE = "work_experience"
    PROJECT = "project"
    GOALS = "goals"
    INTERESTS = "interests"
    PREFERENCE = "preference"
    TECHNICAL_PREFERENCE = "technical_preference"
    PAST_EVENT = "past_event"
    FACT = "fact"
    TOPIC = "topic"


class MemoryItem(BaseModel):
    """A single durable fact remembered for a user."""

    __tablename__ = "memory_items"

    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    organization_id: Mapped[Optional[UUID]] = mapped_column(index=True, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[MemoryCategory] = mapped_column(
        default=MemoryCategory.FACT, nullable=False, index=True
    )
    importance: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    confidence: Mapped[float] = mapped_column(
        Float, default=0.8, nullable=False
    )
    embedding: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    source_conversation_id: Mapped[Optional[UUID]] = mapped_column(
        index=True, nullable=True
    )
    source_message_id: Mapped[Optional[UUID]] = mapped_column(nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    superseded_by_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), nullable=True, index=True
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )

    __table_args__ = (Index("ix_memory_items_user_content", "user_id", "content"),)
