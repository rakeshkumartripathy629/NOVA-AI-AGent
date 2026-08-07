"""
User model and related enums.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class UserRole(str, enum.Enum):
    """Platform-level user roles."""
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    USER = "user"
    VIEWER = "viewer"
    GUEST = "guest"


class UserStatus(str, enum.Enum):
    """User account statuses."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class AuthProvider(str, enum.Enum):
    """Supported authentication providers."""
    LOCAL = "local"
    GOOGLE = "google"
    GITHUB = "github"
    OAUTH = "oauth"


class User(BaseModel):
    """Core user account entity."""

    __tablename__ = "users"

    # Authentication
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    auth_provider: Mapped[AuthProvider] = mapped_column(
        default=AuthProvider.LOCAL, nullable=False, index=True
    )

    # Profile
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="UTC", nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en", nullable=False)

    # Role & status
    role: Mapped[UserRole] = mapped_column(default=UserRole.USER, nullable=False, index=True)
    status: Mapped[UserStatus] = mapped_column(default=UserStatus.ACTIVE, nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)
    is_superuser: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Email verification
    email_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    verification_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)

    # Password reset
    reset_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    reset_token_expires: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Email change
    pending_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_change_token: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email_change_expires: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Two-factor authentication
    two_factor_enabled: Mapped[bool] = mapped_column(default=False, nullable=False)
    two_factor_secret: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Last login tracking
    last_login_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_login_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # Preferences
    preferences: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    # Relationships
    organizations: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="user", foreign_keys="OrganizationMember.user_id", lazy="select"
    )
    owned_organizations: Mapped[List["Organization"]] = relationship(
        "Organization", back_populates="owner", foreign_keys="Organization.owner_id", lazy="select"
    )
    projects: Mapped[List["ProjectMember"]] = relationship(
        "ProjectMember", back_populates="user", foreign_keys="ProjectMember.user_id", lazy="select"
    )
    conversations: Mapped[List["ConversationMember"]] = relationship(
        "ConversationMember", back_populates="user", foreign_keys="ConversationMember.user_id", lazy="select"
    )
    owned_conversations: Mapped[List["Conversation"]] = relationship(
        "Conversation", back_populates="owner", foreign_keys="Conversation.owner_id", lazy="select"
    )
    messages: Mapped[List["Message"]] = relationship(
        "Message", back_populates="user", lazy="select"
    )
    files: Mapped[List["File"]] = relationship(
        "File", back_populates="uploaded_by_user", foreign_keys="File.uploaded_by", lazy="select"
    )
    knowledge_bases: Mapped[List["KnowledgeBaseMember"]] = relationship(
        "KnowledgeBaseMember", back_populates="user", foreign_keys="KnowledgeBaseMember.user_id", lazy="select"
    )
    owned_knowledge_bases: Mapped[List["KnowledgeBase"]] = relationship(
        "KnowledgeBase", back_populates="owner", foreign_keys="KnowledgeBase.owner_id", lazy="select"
    )
    agents: Mapped[List["Agent"]] = relationship(
        "Agent", back_populates="owner", foreign_keys="Agent.owner_id", lazy="select"
    )
    agent_executions: Mapped[List["AgentExecution"]] = relationship(
        "AgentExecution", back_populates="user", lazy="select"
    )
    api_keys: Mapped[List["APIKey"]] = relationship(
        "APIKey", back_populates="user", lazy="select"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        "Notification", back_populates="user", lazy="select"
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog", back_populates="user", lazy="select"
    )
    sessions: Mapped[List["UserSession"]] = relationship(
        "UserSession", back_populates="user", lazy="select"
    )
    oauth_accounts: Mapped[List["OAuthAccount"]] = relationship(
        "OAuthAccount", back_populates="user", lazy="select"
    )

    __table_args__ = (
        Index("ix_users_email_status", "email", "status"),
        Index("ix_users_username_status", "username", "status"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"
