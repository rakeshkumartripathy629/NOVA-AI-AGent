"""
Agent and agent execution models.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class AgentType(str, enum.Enum):
    """Agent classification."""
    CHAT = "chat"
    RESEARCH = "research"
    CODING = "coding"
    ANALYSIS = "analysis"
    WRITING = "writing"
    EMAIL = "email"
    BROWSER = "browser"
    CUSTOM = "custom"


class AgentStatus(str, enum.Enum):
    """Agent lifecycle status."""
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


class Agent(BaseModel):
    """Reusable AI agent configuration."""

    __tablename__ = "agents"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False)
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tools: Mapped[List[dict]] = mapped_column(JSONB, default=list, nullable=False)
    tool_choice: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    knowledge_base_ids: Mapped[List[UUID]] = mapped_column(JSONB, default=list, nullable=False)
    workflow: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    type: Mapped[AgentType] = mapped_column(default=AgentType.CHAT, nullable=False, index=True)
    status: Mapped[AgentStatus] = mapped_column(default=AgentStatus.DRAFT, nullable=False, index=True)
    version: Mapped[int] = mapped_column(default=1, nullable=False)
    is_template: Mapped[bool] = mapped_column(default=False, nullable=False)
    template_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )

    project_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    execution_count: Mapped[int] = mapped_column(default=0, nullable=False)
    success_count: Mapped[int] = mapped_column(default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    total_cost: Mapped[float] = mapped_column(default=0.0, nullable=False)
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="agents", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    owner: Mapped["User"] = relationship("User", back_populates="agents", foreign_keys=[owner_id], lazy="selectin")
    executions: Mapped[List["AgentExecution"]] = relationship("AgentExecution", back_populates="agent", lazy="select")
    template: Mapped[Optional["Agent"]] = relationship(
        "Agent", remote_side="Agent.id", back_populates="versions", foreign_keys=[template_id], lazy="selectin"
    )
    versions: Mapped[List["Agent"]] = relationship(
        "Agent", back_populates="template", foreign_keys=[template_id], lazy="select"
    )

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_agent_org_slug"),
        Index("ix_agents_org_type_status", "organization_id", "type", "status"),
    )

    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name={self.name})>"


class AgentExecution(BaseModel):
    """Record of a single agent run."""

    __tablename__ = "agent_executions"

    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    input_files: Mapped[List[UUID]] = mapped_column(JSONB, default=list, nullable=False)
    output: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_files: Mapped[List[UUID]] = mapped_column(JSONB, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    steps: Mapped[List[dict]] = mapped_column(JSONB, default=list, nullable=False)
    current_step: Mapped[int] = mapped_column(default=0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    cost: Mapped[float] = mapped_column(default=0.0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    agent_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_version: Mapped[int] = mapped_column(default=1, nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    agent: Mapped["Agent"] = relationship("Agent", back_populates="executions", lazy="selectin")
    user: Mapped["User"] = relationship("User", back_populates="agent_executions", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    conversation: Mapped[Optional["Conversation"]] = relationship("Conversation", lazy="selectin")

    __table_args__ = (
        Index("ix_agent_executions_agent_status", "agent_id", "status"),
        Index("ix_agent_executions_user_created", "user_id", "created_at"),
        Index("ix_agent_executions_org_created", "organization_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<AgentExecution(id={self.id}, status={self.status})>"
