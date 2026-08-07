"""
Organization, membership and invitation models.
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


class OrganizationRole(str, enum.Enum):
    """Role of a member within an organization."""
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class OrganizationStatus(str, enum.Enum):
    """Organization lifecycle status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"


class Organization(BaseModel):
    """Tenant entity for the multi-tenant workspace."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[OrganizationStatus] = mapped_column(
        default=OrganizationStatus.ACTIVE, nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    owner: Mapped["User"] = relationship("User", back_populates="owned_organizations", foreign_keys=[owner_id], lazy="selectin")
    members: Mapped[List["OrganizationMember"]] = relationship(
        "OrganizationMember", back_populates="organization", lazy="select"
    )
    projects: Mapped[List["Project"]] = relationship("Project", back_populates="organization", lazy="select")
    subscriptions: Mapped[List["Subscription"]] = relationship("Subscription", back_populates="organization", lazy="select")
    invoices: Mapped[List["Invoice"]] = relationship("Invoice", back_populates="organization", lazy="select")
    payment_methods: Mapped[List["PaymentMethod"]] = relationship("PaymentMethod", back_populates="organization", lazy="select")
    api_keys: Mapped[List["APIKey"]] = relationship("APIKey", back_populates="organization", lazy="select")
    webhooks: Mapped[List["Webhook"]] = relationship("Webhook", back_populates="organization", lazy="select")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="organization", lazy="select")

    __table_args__ = (Index("ix_organizations_owner_status", "owner_id", "status"),)

    def __repr__(self) -> str:
        return f"<Organization(id={self.id}, name={self.name})>"


class OrganizationMember(BaseModel):
    """Join table between users and organizations."""

    __tablename__ = "organization_members"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[OrganizationRole] = mapped_column(
        default=OrganizationRole.MEMBER, nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    invited_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", back_populates="members", lazy="selectin")
    user: Mapped["User"] = relationship("User", back_populates="organizations", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "user_id", name="uq_organization_member"),
        Index("ix_organization_members_org_role", "organization_id", "role"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationMember(org={self.organization_id}, user={self.user_id}, role={self.role})>"


class OrganizationInvitation(BaseModel):
    """Pending invitation for a user to join an organization."""

    __tablename__ = "organization_invitations"

    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    role: Mapped[OrganizationRole] = mapped_column(default=OrganizationRole.MEMBER, nullable=False)
    token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    invited_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    accepted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    declined_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    inviter: Mapped["User"] = relationship("User", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_org_invitation_email"),
        Index("ix_org_invitations_org_status", "organization_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<OrganizationInvitation(org={self.organization_id}, email={self.email})>"
