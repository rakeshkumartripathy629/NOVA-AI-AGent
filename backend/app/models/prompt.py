"""
Prompt library and prompt version models.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class PromptType(str, enum.Enum):
    """Classification of a prompt."""
    SYSTEM = "system"
    USER = "user"
    AGENT = "agent"
    WORKFLOW = "workflow"
    TEMPLATE = "template"


class PromptVisibility(str, enum.Enum):
    """Visibility scope of a prompt."""
    PRIVATE = "private"
    ORG = "org"
    PUBLIC = "public"


class Prompt(BaseModel):
    """A versioned, reusable prompt template."""

    __tablename__ = "prompts"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    type: Mapped[PromptType] = mapped_column(default=PromptType.TEMPLATE, nullable=False, index=True)
    visibility: Mapped[PromptVisibility] = mapped_column(default=PromptVisibility.PRIVATE, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    usage_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tags: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)

    organization_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    owner: Mapped["User"] = relationship("User", lazy="selectin")
    organization: Mapped[Optional["Organization"]] = relationship("Organization", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_prompt_org_slug"),
        Index("ix_prompts_org_visibility", "organization_id", "visibility"),
        Index("ix_prompts_owner_type", "owner_id", "type"),
    )

    def __repr__(self) -> str:
        return f"<Prompt(id={self.id}, name={self.name})>"
