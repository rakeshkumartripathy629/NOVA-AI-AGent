"""
Usage tracking models for metering, analytics and billing.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class UsageType(str, enum.Enum):
    """Kind of metered usage."""
    MESSAGE = "message"
    TOKEN = "token"
    AGENT_EXECUTION = "agent_execution"
    WORKFLOW_EXECUTION = "workflow_execution"
    FILE_STORAGE = "file_storage"
    FILE_PROCESSING = "file_processing"
    EMBEDDING = "embedding"
    API_CALL = "api_call"
    WEB_SEARCH = "web_search"
    VOICE = "voice"
    VISION = "vision"


class UsageRecord(BaseModel):
    """A single metered usage event."""

    __tablename__ = "usage_records"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[UsageType] = mapped_column(nullable=False, index=True)
    quantity: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="count", nullable=False)
    cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reference_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    user: Mapped[Optional["User"]] = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("ix_usage_records_org_type_created", "organization_id", "type", "created_at"),
        Index("ix_usage_records_user_created", "user_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<UsageRecord(id={self.id}, type={self.type})>"


class UsageAggregate(BaseModel):
    """Rolled-up usage totals per organization / period."""

    __tablename__ = "usage_aggregates"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)  # YYYY-MM
    type: Mapped[UsageType] = mapped_column(nullable=False, index=True)
    total_quantity: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    __table_args__ = (
        # unique per org / period / type
        Index("ix_usage_aggregates_org_period_type", "organization_id", "period", "type", unique=True),
    )

    def __repr__(self) -> str:
        return f"<UsageAggregate(org={self.organization_id}, period={self.period})>"
