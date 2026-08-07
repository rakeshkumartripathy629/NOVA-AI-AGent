"""
Webhook models for outbound event delivery.
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


class WebhookEvent(str, enum.Enum):
    """Events that can be delivered to webhooks."""
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_UPDATED = "conversation.updated"
    MESSAGE_CREATED = "message.created"
    MESSAGE_COMPLETED = "message.completed"
    AGENT_EXECUTED = "agent.executed"
    AGENT_EXECUTION_COMPLETED = "agent.execution.completed"
    FILE_PROCESSED = "file.processed"
    KNOWLEDGE_BASE_INDEXED = "knowledge_base.indexed"
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    ORGANIZATION_UPDATED = "organization.updated"
    SUBSCRIPTION_UPDATED = "subscription.updated"
    INVOICE_PAID = "invoice.paid"
    WORKFLOW_COMPLETED = "workflow.completed"


class Webhook(BaseModel):
    """Webhook endpoint subscribed to platform events."""

    __tablename__ = "webhooks"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    secret: Mapped[str] = mapped_column(String(255), nullable=False)
    events: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    last_triggered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_failure_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    failure_count: Mapped[int] = mapped_column(default=0, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(default=0, nullable=False)
    disabled_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    headers: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="webhooks", lazy="selectin")
    deliveries: Mapped[List["WebhookDelivery"]] = relationship("WebhookDelivery", back_populates="webhook", lazy="select")

    __table_args__ = (Index("ix_webhooks_org_active", "organization_id", "is_active"),)

    def __repr__(self) -> str:
        return f"<Webhook(id={self.id}, name={self.name})>"


class WebhookDelivery(BaseModel):
    """Record of a single webhook delivery attempt."""

    __tablename__ = "webhook_deliveries"

    webhook_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response_headers: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    attempt: Mapped[int] = mapped_column(default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(default=0, nullable=False)
    delivered_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    webhook: Mapped["Webhook"] = relationship("Webhook", back_populates="deliveries", lazy="selectin")

    __table_args__ = (
        Index("ix_webhook_deliveries_webhook_status", "webhook_id", "status"),
        Index("ix_webhook_deliveries_event", "event"),
    )

    def __repr__(self) -> str:
        return f"<WebhookDelivery(id={self.id}, event={self.event}, status={self.status})>"
