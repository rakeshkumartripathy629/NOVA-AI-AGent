"""
Message model and related enums.
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


class MessageRole(str, enum.Enum):
    """Role of a message in the conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    FUNCTION = "function"


class MessageType(str, enum.Enum):
    """Content type of a message."""
    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    AUDIO = "audio"
    VIDEO = "video"
    CODE = "code"
    MARKDOWN = "markdown"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ERROR = "error"


class MessageStatus(str, enum.Enum):
    """Processing lifecycle of a message."""
    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Message(BaseModel):
    """A single message within a conversation."""

    __tablename__ = "messages"

    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[MessageRole] = mapped_column(nullable=False, index=True)
    type: Mapped[MessageType] = mapped_column(default=MessageType.TEXT, nullable=False)
    status: Mapped[MessageStatus] = mapped_column(
        default=MessageStatus.COMPLETED, nullable=False, index=True
    )

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    branch_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversation_branches.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )

    model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    model_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    finish_reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    prompt_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    cost: Mapped[float] = mapped_column(default=0.0, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    tool_calls: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    attachments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    citations: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    is_edited: Mapped[bool] = mapped_column(default=False, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feedback: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages", lazy="selectin")
    branch: Mapped[Optional["ConversationBranch"]] = relationship("ConversationBranch", back_populates="messages", foreign_keys=[branch_id], lazy="selectin")
    user: Mapped[Optional["User"]] = relationship("User", back_populates="messages", lazy="selectin")
    parent: Mapped[Optional["Message"]] = relationship("Message", remote_side="Message.id", back_populates="children", lazy="selectin")
    children: Mapped[List["Message"]] = relationship("Message", back_populates="parent", lazy="select")
    files: Mapped[List["File"]] = relationship("File", back_populates="message", lazy="select")

    __table_args__ = (
        Index("ix_messages_conversation_created", "conversation_id", "created_at"),
        Index("ix_messages_user_created", "user_id", "created_at"),
        Index("ix_messages_parent", "parent_id"),
        Index("ix_messages_branch_created", "branch_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, status={self.status})>"
