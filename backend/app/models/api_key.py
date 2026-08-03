"""
API key models for the developer platform.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class APIKeyStatus(str, enum.Enum):
    """API key lifecycle status."""
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class APIKey(BaseModel):
    """Hashed API key for programmatic access."""

    __tablename__ = "api_keys"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    key_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    status: Mapped[APIKeyStatus] = mapped_column(default=APIKeyStatus.ACTIVE, nullable=False, index=True)
    scopes: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    rate_limit: Mapped[Optional[int]] = mapped_column(nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_used_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    usage_count: Mapped[int] = mapped_column(default=0, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    user: Mapped["User"] = relationship("User", back_populates="api_keys", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="api_keys", lazy="selectin")

    __table_args__ = (
        Index("ix_api_keys_org_status", "organization_id", "status"),
        Index("ix_api_keys_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<APIKey(id={self.id}, name={self.name})>"
