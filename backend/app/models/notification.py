"""
Notification models.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class NotificationType(str, enum.Enum):
    """Categorisation of notifications."""
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    MENTION = "mention"
    ASSIGNMENT = "assignment"
    COMMENT = "comment"
    SHARE = "share"
    INVITATION = "invitation"
    SYSTEM = "system"
    BILLING = "billing"
    SECURITY = "security"
    AGENT = "agent"
    WORKFLOW = "workflow"


class NotificationChannel(str, enum.Enum):
    """Delivery channels for a notification."""
    IN_APP = "in_app"
    EMAIL = "email"
    PUSH = "push"
    SMS = "sms"
    WEBHOOK = "webhook"


class NotificationStatus(str, enum.Enum):
    """Delivery lifecycle of a notification."""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    READ = "read"
    ARCHIVED = "archived"
    FAILED = "failed"


class Notification(BaseModel):
    """In-app / cross-channel notification for a user."""

    __tablename__ = "notifications"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    type: Mapped[NotificationType] = mapped_column(default=NotificationType.INFO, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    channels: Mapped[List[NotificationChannel]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        default=NotificationStatus.PENDING, nullable=False, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reference_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reference_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    action_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    action_label: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    user: Mapped["User"] = relationship("User", back_populates="notifications", lazy="selectin")
    organization: Mapped[Optional["Organization"]] = relationship("Organization", lazy="selectin")

    __table_args__ = (
        Index("ix_notifications_user_status", "user_id", "status"),
        Index("ix_notifications_user_type", "user_id", "type"),
        Index("ix_notifications_reference", "reference_type", "reference_id"),
    )

    def __repr__(self) -> str:
        return f"<Notification(id={self.id}, type={self.type})>"


class NotificationPreference(BaseModel):
    """Per-user notification preferences."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    email_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    push_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    in_app_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    sms_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    marketing_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    security_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    billing_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    product_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    mention_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    assignment_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    share_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    invitation_enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    digest_frequency: Mapped[str] = mapped_column(String(20), default="daily", nullable=False)
    quiet_hours_start: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    quiet_hours_end: Mapped[Optional[str]] = mapped_column(String(5), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)

    user: Mapped["User"] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return f"<NotificationPreference(user={self.user_id})>"
