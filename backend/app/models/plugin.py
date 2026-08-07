"""
Plugin and marketplace models for the plugin system.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class PluginStatus(str, enum.Enum):
    """Plugin lifecycle status."""
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class PluginCategory(str, enum.Enum):
    """Plugin category for marketplace discovery."""
    INTEGRATION = "integration"
    TOOL = "tool"
    AGENT = "agent"
    WORKFLOW = "workflow"
    DATA_SOURCE = "data_source"
    UI = "ui"
    OTHER = "other"


class Plugin(BaseModel):
    """A distributable plugin listed in the marketplace."""

    __tablename__ = "plugins"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    icon_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    category: Mapped[PluginCategory] = mapped_column(default=PluginCategory.TOOL, nullable=False, index=True)
    status: Mapped[PluginStatus] = mapped_column(default=PluginStatus.DRAFT, nullable=False, index=True)
    manifest: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    entrypoint: Mapped[str] = mapped_column(String(500), nullable=False)
    config_schema: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    permissions: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_public: Mapped[bool] = mapped_column(default=False, nullable=False)
    install_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rating: Mapped[float] = mapped_column(default=0.0, nullable=False)
    review_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    repository_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    documentation_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    tags: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)

    publisher_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    publisher: Mapped["User"] = relationship("User", lazy="selectin")
    installations: Mapped[List["PluginInstallation"]] = relationship("PluginInstallation", back_populates="plugin", lazy="select")

    __table_args__ = (Index("ix_plugins_category_status", "category", "status"),)

    def __repr__(self) -> str:
        return f"<Plugin(id={self.id}, name={self.name})>"


class PluginInstallation(BaseModel):
    """A plugin installed into an organization."""

    __tablename__ = "plugin_installations"

    plugin_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("plugins.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installed_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    installed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    version: Mapped[str] = mapped_column(String(50), default="1.0.0", nullable=False)

    plugin: Mapped["Plugin"] = relationship("Plugin", back_populates="installations", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    installer: Mapped["User"] = relationship("User", foreign_keys=[installed_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("plugin_id", "organization_id", name="uq_plugin_installation"),
        Index("ix_plugin_installations_org", "organization_id", "enabled"),
    )

    def __repr__(self) -> str:
        return f"<PluginInstallation(plugin={self.plugin_id}, org={self.organization_id})>"
