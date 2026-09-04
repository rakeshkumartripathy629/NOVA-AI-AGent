"""
Persona endpoints — create, list, update, delete custom AI personalities.
"""
from __future__ import annotations

import re
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.session import get_db
from app.core.logging import get_logger
from app.models.persona import Persona
from app.models.user import User

logger = get_logger("api.personas")

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────

class PersonaCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    avatar_emoji: str = Field(default="🤖", max_length=10)
    system_prompt: str = Field(..., min_length=10, max_length=10000)
    category: str = Field(default="general", max_length=50)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=100, le=128000)


class PersonaUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    avatar_emoji: Optional[str] = Field(default=None, max_length=10)
    system_prompt: Optional[str] = Field(default=None, min_length=10, max_length=10000)
    category: Optional[str] = Field(default=None, max_length=50)
    temperature: Optional[float] = Field(default=None, ge=0, le=2)
    max_tokens: Optional[int] = Field(default=None, ge=100, le=128000)
    is_active: Optional[bool] = None


class PersonaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: str
    name: str
    slug: str
    description: str
    avatar_emoji: str
    system_prompt: str
    category: str
    is_builtin: bool
    is_active: bool
    temperature: Optional[float]
    max_tokens: Optional[int]

    @classmethod
    def from_persona(cls, p: "Persona") -> "PersonaResponse":
        return cls(
            id=str(p.id),
            name=p.name,
            slug=p.slug,
            description=p.description or "",
            avatar_emoji=p.avatar_emoji or "🤖",
            system_prompt=p.system_prompt or "",
            category=p.category or "general",
            is_builtin=p.is_builtin,
            is_active=p.is_active,
            temperature=p.temperature,
            max_tokens=p.max_tokens,
        )


# ── Helpers ──────────────────────────────────────────────────────────

def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:80]


# ── Routes ───────────────────────────────────────────────────────────

@router.get("/", response_model=list[PersonaResponse], summary="List all personas")
async def list_personas(
    category: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """List all active personas, optionally filtered by category."""
    q = select(Persona).where(Persona.is_active == True)  # noqa: E712
    if category:
        q = q.where(Persona.category == category)
    q = q.order_by(Persona.sort_order, Persona.name)
    result = await db.execute(q)
    return [PersonaResponse.from_persona(p) for p in result.scalars().all()]


@router.get("/categories", summary="List persona categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Return distinct persona categories."""
    result = await db.execute(
        select(Persona.category, func.count(Persona.id))
        .where(Persona.is_active == True)  # noqa: E712
        .group_by(Persona.category)
        .order_by(func.count(Persona.id).desc())
    )
    return [{"category": row[0], "count": row[1]} for row in result.all()]


@router.get("/{persona_id}", response_model=PersonaResponse, summary="Get persona")
async def get_persona(persona_id: str, db: AsyncSession = Depends(get_db)):
    """Get a specific persona by ID or slug."""
    result = await db.execute(
        select(Persona).where((Persona.id == persona_id) | (Persona.slug == persona_id))
    )
    persona = result.scalar_one_or_none()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return PersonaResponse.from_persona(persona)


@router.post("/", response_model=PersonaResponse, status_code=201, summary="Create persona")
async def create_persona(
    data: PersonaCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Create a new custom persona."""
    slug = _slugify(data.name)

    # Check uniqueness
    existing = await db.execute(select(Persona).where(Persona.slug == slug))
    if existing.scalar_one_or_none():
        # Append number
        count = await db.scalar(select(func.count(Persona.id)).where(Persona.slug.startswith(slug)))
        slug = f"{slug}-{count + 1}"

    persona = Persona(
        name=data.name,
        slug=slug,
        description=data.description,
        avatar_emoji=data.avatar_emoji,
        system_prompt=data.system_prompt,
        category=data.category,
        created_by=str(user.id),
        temperature=data.temperature,
        max_tokens=data.max_tokens,
    )
    db.add(persona)
    await db.commit()
    await db.refresh(persona)
    logger.info("Persona created: %s (by %s)", persona.slug, user.id)
    return PersonaResponse.from_persona(persona)


@router.put("/{persona_id}", response_model=PersonaResponse, summary="Update persona")
async def update_persona(
    persona_id: str,
    data: PersonaUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update a persona. Users can only update their own personas."""
    result = await db.execute(select(Persona).where(Persona.id == persona_id))
    persona = result.scalar_one_or_none()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    if persona.created_by and persona.created_by != str(user.id) and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(persona, field, value)
    if "name" in update_data:
        persona.slug = _slugify(update_data["name"])

    await db.commit()
    await db.refresh(persona)
    return PersonaResponse.from_persona(persona)


@router.delete("/{persona_id}", status_code=204, summary="Delete persona")
async def delete_persona(
    persona_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a persona. Cannot delete built-in personas."""
    result = await db.execute(select(Persona).where(Persona.id == persona_id))
    persona = result.scalar_one_or_none()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    if persona.is_builtin:
        raise HTTPException(status_code=400, detail="Cannot delete built-in persona")
    if persona.created_by and persona.created_by != str(user.id) and not user.is_superuser:
        raise HTTPException(status_code=403, detail="Not authorized")

    await db.delete(persona)
    await db.commit()
    logger.info("Persona deleted: %s", persona.slug)
