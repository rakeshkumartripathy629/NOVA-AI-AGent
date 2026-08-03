"""
Project and folder models for organizing the workspace.
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


class ProjectRole(str, enum.Enum):
    """Role of a member within a project."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ProjectType(str, enum.Enum):
    """Project classification for UI/behaviour defaults."""
    CHAT = "chat"
    RESEARCH = "research"
    CODING = "coding"
    WRITING = "writing"
    ANALYSIS = "analysis"
    CUSTOM = "custom"


class Project(BaseModel):
    """Logical grouping of conversations, files, agents and knowledge bases."""

    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    type: Mapped[ProjectType] = mapped_column(default=ProjectType.CHAT, nullable=False, index=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    is_archived: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    is_template: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_public: Mapped[bool] = mapped_column(default=False, nullable=False)
    conversation_count: Mapped[int] = mapped_column(default=0, nullable=False)
    message_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_activity_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    organization: Mapped["Organization"] = relationship("Organization", back_populates="projects", lazy="selectin")
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id], lazy="selectin")
    members: Mapped[List["ProjectMember"]] = relationship("ProjectMember", back_populates="project", lazy="selectin")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="project", lazy="selectin")
    folders: Mapped[List["Folder"]] = relationship("Folder", back_populates="project", lazy="selectin")
    knowledge_bases: Mapped[List["KnowledgeBase"]] = relationship("KnowledgeBase", back_populates="project", lazy="selectin")
    agents: Mapped[List["Agent"]] = relationship("Agent", back_populates="project", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_project_org_slug"),
        Index("ix_projects_org_owner", "organization_id", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<Project(id={self.id}, name={self.name})>"


class ProjectMember(BaseModel):
    """Join table between users and projects."""

    __tablename__ = "project_members"

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ProjectRole] = mapped_column(default=ProjectRole.MEMBER, nullable=False)
    invited_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    project: Mapped["Project"] = relationship("Project", back_populates="members", lazy="selectin")
    user: Mapped["User"] = relationship("User", back_populates="projects", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("project_id", "user_id", name="uq_project_member"),
        Index("ix_project_members_project_role", "project_id", "role"),
    )

    def __repr__(self) -> str:
        return f"<ProjectMember(project={self.project_id}, user={self.user_id})>"


class Folder(BaseModel):
    """Hierarchical folder for organizing conversations inside a project."""

    __tablename__ = "folders"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    conversation_count: Mapped[int] = mapped_column(default=0, nullable=False)

    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("folders.id", ondelete="CASCADE"), nullable=True, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    project: Mapped["Project"] = relationship("Project", back_populates="folders", lazy="selectin")
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id], lazy="selectin")
    parent: Mapped[Optional["Folder"]] = relationship("Folder", remote_side="Folder.id", back_populates="children", lazy="selectin")
    children: Mapped[List["Folder"]] = relationship("Folder", back_populates="parent", lazy="selectin")
    conversations: Mapped[List["Conversation"]] = relationship("Conversation", back_populates="folder", lazy="selectin")

    __table_args__ = (Index("ix_folders_project_parent", "project_id", "parent_id"),)

    def __repr__(self) -> str:
        return f"<Folder(id={self.id}, name={self.name})>"
