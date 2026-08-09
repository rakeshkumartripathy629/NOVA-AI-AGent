"""
Long-term memory endpoints: view, add, search, update and delete memory items.

Memory is private per-user: every query is scoped to the authenticated user id
from the JWT (never from the request body). The router is mounted under both
``/memory`` and ``/memories`` so either path works.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.memory import MemoryCategory, MemoryItem
from app.models.user import User
from app.services import memory_service

router = APIRouter()


class MemoryCreate(BaseModel):
    """Memory create model."""
    content: str = Field(..., min_length=1, max_length=2000)
    category: MemoryCategory = MemoryCategory.FACT


class MemoryUpdate(BaseModel):
    """Memory update model."""
    content: Optional[str] = Field(None, min_length=1, max_length=2000)
    category: Optional[MemoryCategory] = None
    importance: Optional[int] = Field(None, ge=1, le=5)


class MemorySearchRequest(BaseModel):
    """Semantic memory search request."""
    query: str = Field(..., min_length=1, max_length=500)
    limit: int = Field(20, ge=1, le=100)


class MemoryResponse(BaseModel):
    """Memory response model."""
    id: UUID
    content: str
    category: str
    importance: int
    confidence: float = 0.8
    use_count: int
    last_used_at: Optional[datetime] = None
    source_conversation_id: Optional[UUID] = None
    auto: bool = False
    created_at: datetime
    updated_at: datetime


class MemoryListResponse(BaseModel):
    """Paginated memory list."""
    memories: List[MemoryResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MemorySearchResponse(BaseModel):
    """Semantic memory search results."""
    memories: List[MemoryResponse]
    total: int


def _memory_dict(memory: MemoryItem) -> dict:
    return {
        "id": memory.id,
        "content": memory.content,
        "category": memory.category.value,
        "importance": memory.importance,
        "confidence": memory.confidence,
        "use_count": memory.use_count,
        "last_used_at": memory.last_used_at,
        "source_conversation_id": memory.source_conversation_id,
        "auto": bool((memory.metadata_ or {}).get("auto")),
        "created_at": memory.created_at,
        "updated_at": memory.updated_at,
    }


async def _get_owned_or_404(
    db: AsyncSession, memory_id: UUID, user_id: UUID
) -> MemoryItem:
    memory = await memory_service.get_memory(db, user_id, memory_id)
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return memory


@router.get("", response_model=MemoryListResponse, summary="List memories")
async def list_memories(
    search: Optional[str] = Query(None, max_length=200),
    category: Optional[MemoryCategory] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List the current user's memories (optionally filtered)."""
    data = await memory_service.list_memories(
        db, current_user.id, search=search, category=category, page=page, page_size=page_size
    )
    items = data["items"]
    total = data["total"]
    return MemoryListResponse(
        memories=[MemoryResponse(**_memory_dict(m)) for m in items],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED, summary="Add memory")
async def create_memory(
    memory_data: MemoryCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually add a memory item for the current user."""
    memory = await memory_service.create_memory(
        db,
        current_user.id,
        None,
        memory_data.content,
        memory_data.category,
    )
    return MemoryResponse(**_memory_dict(memory))


@router.post("/search", response_model=MemorySearchResponse, summary="Search memories semantically")
async def search_memories(
    body: MemorySearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search over the current user's memories."""
    items = await memory_service.search_memories(db, current_user.id, body.query, body.limit)
    return MemorySearchResponse(
        memories=[MemoryResponse(**_memory_dict(m)) for m in items],
        total=len(items),
    )


@router.get("/{memory_id}", response_model=MemoryResponse, summary="Get memory")
async def get_memory(
    memory_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single memory item by id."""
    memory = await _get_owned_or_404(db, memory_id, current_user.id)
    return MemoryResponse(**_memory_dict(memory))


@router.patch("/{memory_id}", response_model=MemoryResponse, summary="Update memory")
async def update_memory(
    memory_id: UUID,
    memory_data: MemoryUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a memory item's content, category or importance."""
    updates = memory_data.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update")
    memory = await memory_service.update_memory(db, current_user.id, memory_id, updates)
    if not memory:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return MemoryResponse(**_memory_dict(memory))


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete memory")
async def delete_memory(
    memory_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a memory item and remove its vector."""
    deleted = await memory_service.delete_memory(db, current_user.id, memory_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, summary="Clear all memories")
async def clear_memories(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete every memory belonging to the current user."""
    await memory_service.clear_memories(db, current_user.id)
