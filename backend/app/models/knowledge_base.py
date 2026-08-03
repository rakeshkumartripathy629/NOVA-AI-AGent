"""
Knowledge base models for RAG document management.
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


class KnowledgeBaseRole(str, enum.Enum):
    """Role of a member within a knowledge base."""
    OWNER = "owner"
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class KnowledgeBase(BaseModel):
    """A collection of documents that can be searched with RAG."""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    icon: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    color: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(100), default="text-embedding-3-small", nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=200, nullable=False)

    is_public: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_indexed: Mapped[bool] = mapped_column(default=False, nullable=False)
    document_count: Mapped[int] = mapped_column(default=0, nullable=False)
    total_chunks: Mapped[int] = mapped_column(default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    project_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    project: Mapped[Optional["Project"]] = relationship("Project", back_populates="knowledge_bases", lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")
    owner: Mapped["User"] = relationship("User", back_populates="owned_knowledge_bases", foreign_keys=[owner_id], lazy="selectin")
    members: Mapped[List["KnowledgeBaseMember"]] = relationship("KnowledgeBaseMember", back_populates="knowledge_base", lazy="selectin")
    documents: Mapped[List["KnowledgeBaseDocument"]] = relationship("KnowledgeBaseDocument", back_populates="knowledge_base", lazy="selectin")
    files: Mapped[List["File"]] = relationship("File", back_populates="knowledge_base", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("organization_id", "slug", name="uq_kb_org_slug"),
        Index("ix_knowledge_bases_org_owner", "organization_id", "owner_id"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBase(id={self.id}, name={self.name})>"


class KnowledgeBaseDocument(BaseModel):
    """A single indexed document inside a knowledge base."""

    __tablename__ = "knowledge_base_documents"

    title: Mapped[str] = mapped_column(String(500), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(default=0, nullable=False)
    token_count: Mapped[int] = mapped_column(default=0, nullable=False)
    chunk_ids: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)

    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase", back_populates="documents", lazy="selectin")
    uploaded_by_user: Mapped["User"] = relationship("User", foreign_keys=[uploaded_by], lazy="selectin")
    files: Mapped[List["File"]] = relationship("File", back_populates="knowledge_base_document", lazy="selectin")

    __table_args__ = (Index("ix_kb_docs_kb_status", "knowledge_base_id", "status"),)

    def __repr__(self) -> str:
        return f"<KnowledgeBaseDocument(id={self.id}, title={self.title})>"


class KnowledgeBaseMember(BaseModel):
    """Join table between users and knowledge bases."""

    __tablename__ = "knowledge_base_members"

    knowledge_base_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[KnowledgeBaseRole] = mapped_column(default=KnowledgeBaseRole.VIEWER, nullable=False)
    invited_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    joined_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    knowledge_base: Mapped["KnowledgeBase"] = relationship("KnowledgeBase", back_populates="members", lazy="selectin")
    user: Mapped["User"] = relationship("User", back_populates="knowledge_bases", foreign_keys=[user_id], lazy="selectin")
    inviter: Mapped[Optional["User"]] = relationship("User", foreign_keys=[invited_by], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "user_id", name="uq_kb_member"),
        Index("ix_kb_members_kb_role", "knowledge_base_id", "role"),
    )

    def __repr__(self) -> str:
        return f"<KnowledgeBaseMember(kb={self.knowledge_base_id}, user={self.user_id})>"
