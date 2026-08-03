"""
Base model classes and mixins.

Provides the foundational SQLAlchemy declarative base, UUID primary keys,
audit timestamps, soft-delete, metadata and tagging support used by every
entity in the Nova AI platform.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import DateTime, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, declared_attr


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """Generate a snake_case table name from the class name."""
        name: str = cls.__name__
        s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()


class UUIDMixin:
    """Mixin providing a UUID primary key."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        index=True,
    )


class TimestampMixin:
    """Mixin providing created_at / updated_at audit timestamps."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class SoftDeleteMixin:
    """Mixin providing soft-delete support."""

    is_deleted: Mapped[bool] = mapped_column(
        default=False, nullable=False, index=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def soft_delete(self) -> None:
        """Mark the record as deleted."""
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def restore(self) -> None:
        """Restore a soft-deleted record."""
        self.is_deleted = False
        self.deleted_at = None


class MetadataModel:
    """Mixin providing a JSONB metadata column."""

    metadata_: Mapped[dict] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )


class TaggedModel:
    """Mixin providing a JSONB tags column."""

    tags: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class BaseModel(Base, UUIDMixin, TimestampMixin, SoftDeleteMixin):
    """Default base model with UUID PK, timestamps and soft-delete."""

    __abstract__ = True

    def to_dict(self, exclude: Optional[set] = None) -> Dict[str, Any]:
        """Serialize the model into a dictionary."""
        exclude = exclude or set()
        result: Dict[str, Any] = {}
        for column in self.__table__.columns:
            if column.name in exclude:
                continue
            value = getattr(self, column.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, uuid.UUID):
                value = str(value)
            result[column.name] = value
        return result


# Backwards-compatible aliases used by legacy modules
SoftDeletableModel = BaseModel
