"""
Workflow models for multi-step automation and agent workflows.
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


class WorkflowStatus(str, enum.Enum):
    """Workflow lifecycle status."""
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class WorkflowTriggerType(str, enum.Enum):
    """How a workflow is started."""
    MANUAL = "manual"
    SCHEDULE = "schedule"
    EVENT = "event"
    WEBHOOK = "webhook"


class Workflow(BaseModel):
    """A directed graph of steps executed by the workflow engine."""

    __tablename__ = "workflows"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)  # nodes + edges
    trigger_type: Mapped[WorkflowTriggerType] = mapped_column(default=WorkflowTriggerType.MANUAL, nullable=False)
    trigger_config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[WorkflowStatus] = mapped_column(default=WorkflowStatus.DRAFT, nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_template: Mapped[bool] = mapped_column(default=False, nullable=False)
    execution_count: Mapped[int] = mapped_column(default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    owner: Mapped["User"] = relationship("User", lazy="selectin")
    executions: Mapped[List["WorkflowExecution"]] = relationship("WorkflowExecution", back_populates="workflow", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_workflow_org_slug"),
        Index("ix_workflows_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Workflow(id={self.id}, name={self.name})>"


class WorkflowExecution(BaseModel):
    """A single run of a workflow."""

    __tablename__ = "workflow_executions"

    workflow_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    input: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    output: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    steps: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    current_step: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cost: Mapped[float] = mapped_column(default=0.0, nullable=False)

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="executions", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    user: Mapped[Optional["User"]] = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("ix_workflow_executions_workflow_status", "workflow_id", "status"),
        Index("ix_workflow_executions_org_created", "organization_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<WorkflowExecution(id={self.id}, status={self.status})>"
