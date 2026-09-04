"""
Persona model — custom AI personalities that users can select.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import String, Text, Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel


class Persona(BaseModel):
    """A custom AI persona with its own personality, tone, and expertise."""

    __tablename__ = "personas"

    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    avatar_emoji: Mapped[str] = mapped_column(String(10), nullable=False, default="🤖")
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default="general")
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(nullable=True, default=None)
    max_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)

    def __repr__(self) -> str:
        return f"<Persona(name={self.name}, slug={self.slug})>"
