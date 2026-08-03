"""
File model and related enums.
"""
from __future__ import annotations

import enum
from typing import List, Optional
from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import BaseModel


class FileType(str, enum.Enum):
    """High level file classification."""
    IMAGE = "image"
    DOCUMENT = "document"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    AUDIO = "audio"
    VIDEO = "video"
    ARCHIVE = "archive"
    CODE = "code"
    TEXT = "text"
    PDF = "pdf"
    OTHER = "other"


class FileStatus(str, enum.Enum):
    """Processing lifecycle of a file."""
    UPLOADING = "uploading"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    DELETED = "deleted"


class File(BaseModel):
    """Stored file object with extraction and embedding metadata."""

    __tablename__ = "files"

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_type: Mapped[FileType] = mapped_column(nullable=False, index=True)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(100), nullable=False)
    storage_region: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    cdn_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    status: Mapped[FileStatus] = mapped_column(default=FileStatus.UPLOADING, nullable=False, index=True)
    processing_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[float]] = mapped_column(nullable=True)
    pages: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    embedding_ids: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)

    conversation_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    message_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    knowledge_base_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True, index=True
    )
    knowledge_base_document_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("knowledge_base_documents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    uploaded_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    tags: Mapped[List[str]] = mapped_column(JSONB, default=list, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    conversation: Mapped[Optional["Conversation"]] = relationship("Conversation", back_populates="files", lazy="selectin")
    message: Mapped[Optional["Message"]] = relationship("Message", back_populates="files", lazy="selectin")
    knowledge_base: Mapped[Optional["KnowledgeBase"]] = relationship("KnowledgeBase", back_populates="files", lazy="selectin")
    knowledge_base_document: Mapped[Optional["KnowledgeBaseDocument"]] = relationship(
        "KnowledgeBaseDocument", back_populates="files", lazy="selectin"
    )
    uploaded_by_user: Mapped["User"] = relationship("User", back_populates="files", foreign_keys=[uploaded_by], lazy="selectin")
    organization: Mapped["Organization"] = relationship("Organization", lazy="selectin")

    __table_args__ = (
        Index("ix_files_org_status", "organization_id", "status"),
        Index("ix_files_org_type", "organization_id", "file_type"),
        Index("ix_files_conversation", "conversation_id"),
        Index("ix_files_kb", "knowledge_base_id"),
        Index("ix_files_uploaded_by", "uploaded_by"),
    )

    def __repr__(self) -> str:
        return f"<File(id={self.id}, filename={self.filename})>"
    conversation: Mapped[Optional["Conversation"]] = relationship(
        "Conversation", back_populates="files", lazy="selectin"
    )
    message: Mapped[Optional["Message"]] = relationship(
        "Message", back_populates="files", lazy="selectin"
    )
    knowledge_base: Mapped[Optional["KnowledgeBase"]] = relationship(
        "KnowledgeBase", back_populates="files", lazy="selectin"
    )
    knowledge_base_document: Mapped[Optional["KnowledgeBaseDocument"]] = relationship(
        "KnowledgeBaseDocument",
        back_populates="files",
        lazy="selectin",
    )
    uploaded_by_user: Mapped["User"] = relationship(
        "User",
        back_populates="files",
        foreign_keys=[uploaded_by],
        lazy="selectin",
    )
    organization: Mapped["Organization"] = relationship(
        "Organization",
        lazy="selectin",
    )

    __table_args__ = (
        Index("ix_files_org_status", "organization_id", "status"),
        Index("ix_files_org_type", "organization_id", "file_type"),
        Index("ix_files_conversation", "conversation_id"),
        Index("ix_files_kb", "knowledge_base_id"),
    )

    def __repr__(self) -> str:
        return f"<File(id={self.id}, filename={self.filename})>"