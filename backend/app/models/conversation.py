"""
Conversation models including participants, branches and sharing.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class ConversationRole(str, enum.Enum):
    """Role of a member within a conversation."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class ConversationStatus(str, enum.Enum):
    """Conversation lifecycle status."""
    ACTIVE = "active"
    ARCHIVED = "archived"
    PINNED = "pinned"
    DELETED = "deleted"


class Conversation(BaseModel):
    """A chat session with persistent history and configuration."""

    __tablename__ = "conversations"

    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    temperature: Mapped[float] = mapped_column(default=0.7, nullable=False)
    max_tokens: Mapped[Optional[int]] = mapped_column(nullable=True)
    tools: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)

    status: Mapped[ConversationStatus] = mapped_column(
        default=ConversationStatus.ACTIVE, nullable=False, index=True
    )
    is_private: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_archived: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    is_pinned: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_shared: Mapped[bool] = mapped_column(default=False, nullable=False)
    share_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True, index=True)

    message_count: Mapped[int] = mapped_column(default=0, nullable=False)
    token_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_cost: Mapped[float] = mapped_column(default=0.0, nullable=False)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(nullable=True, index=True)

    project_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    folder_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="conversations", lazy="selectin")
    folder: Mapped[Optional["Folder"]] = relationship("Folder", back_populates="conversations", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    owner: Mapped["User"] = relationship("User", foreign_keys=[owner_id], lazy="selectin")
    members: Mapped[List["ConversationMember"]] = relationship("ConversationMember", back_populates="conversation", lazy="select")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="conversation", lazy="select", order_by="Message.created_at")
    files: Mapped[List["File"]] = relationship("File", back_populates="conversation", lazy="select")
    branches: Mapped[List["ConversationBranch"]] = relationship("ConversationBranch", back_populates="conversation", lazy="select")

    __table_args__ = (
        Index("ix_conversations_org_archived", "organization_id", "status"),
        Index("ix_conversations_org_pinned", "organization_id", "is_pinned"),
        Index("ix_conversations_owner", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<Conversation(id={self.id}, title={self.title})>"


class ConversationMember(BaseModel):
    """Join table between users and conversations."""

    __tablename__ = "conversation_members"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ConversationRole] = mapped_column(default=ConversationRole.MEMBER, nullable=False)
    notify: Mapped[bool] = mapped_column(default=True, nullable=False)
    last_read_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    invited_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="members", lazy="selectin")
    user: Mapped["User"] = relationship("User", back_populates="conversations", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("conversation_id", "user_id", name="uq_conversation_member"),
        Index("ix_conversation_members_conv_role", "conversation_id", "role"),
    )

    def __repr__(self) -> str:
        return f"<ConversationMember(conv={self.conversation_id}, user={self.user_id})>"


class ConversationBranch(BaseModel):
    """A branch in a conversation starting from a parent message."""

    __tablename__ = "conversation_branches"

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    message_count: Mapped[int] = mapped_column(default=0, nullable=False)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="branches", lazy="selectin")
    parent_message: Mapped["Message"] = relationship("Message", foreign_keys=[parent_message_id], lazy="selectin")
    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id], lazy="selectin")
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="branch", foreign_keys="Message.branch_id", lazy="select")

    def __repr__(self) -> str:
        return f"<ConversationBranch(conv={self.conversation_id}, parent={self.parent_message_id})>"
