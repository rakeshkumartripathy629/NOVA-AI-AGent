"""
User session models for refresh-token rotation and session tracking.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class SessionStatus(str, enum.Enum):
    """Session lifecycle status."""
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"


class UserSession(BaseModel):
    """A user login session for refresh token rotation."""

    __tablename__ = "user_sessions"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    refresh_token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    device: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False, index=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    status: Mapped[SessionStatus] = mapped_column(default=SessionStatus.ACTIVE, nullable=False, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="sessions", lazy="selectin")

    __table_args__ = (Index("ix_user_sessions_user_status", "user_id", "status"),)

    def __repr__(self) -> str:
        return f"<UserSession(id={self.id}, user={self.user_id})>"


class OAuthAccount(BaseModel):
    """Linked third-party OAuth account for a user."""

    __tablename__ = "oauth_accounts"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    access_token: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    refresh_token: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="oauth_accounts", lazy="selectin")

    __table_args__ = (
        # unique constraint for (provider, provider_user_id)
        Index("ix_oauth_accounts_provider", "provider", "provider_user_id", unique=True),
    )

    def __repr__(self) -> str:
        return f"<OAuthAccount(user={self.user_id}, provider={self.provider})>"
