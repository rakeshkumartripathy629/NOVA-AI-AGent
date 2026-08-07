"""
API key management endpoints for the developer platform.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_organization
from app.core.security import get_current_active_user, generate_api_key, hash_token
from app.db.session import get_db
from app.models.api_key import APIKey, APIKeyStatus
from app.models.organization import Organization
from app.models.user import User

router = APIRouter()


class APIKeyCreate(BaseModel):
    """API key create model."""
    name: str = Field(..., min_length=1, max_length=255)
    scopes: List[str] = Field(default_factory=lambda: ["chat"])
    expires_at: Optional[datetime] = None


class APIKeyUpdate(BaseModel):
    """API key update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    scopes: Optional[List[str]] = None
    expires_at: Optional[datetime] = None


class APIKeyResponse(BaseModel):
    """API key response model (never includes the raw key)."""
    id: UUID
    name: str
    prefix: str
    status: str
    scopes: List[str] = []
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    usage_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class APIKeyCreatedResponse(APIKeyResponse):
    """Response after creation, includes the full key shown once."""
    key: str


class APIKeyListResponse(BaseModel):
    """Paginated API key list."""
    api_keys: List[APIKeyResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


async def _get_owned_key(db: AsyncSession, key_id: UUID, user: User) -> APIKey:
    result = await db.execute(
        select(APIKey).where(APIKey.id == key_id, APIKey.user_id == user.id)
    )
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return key


@router.get("", response_model=APIKeyListResponse, summary="List API keys")
async def list_api_keys(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[APIKeyStatus] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List API keys for the current organization."""
    query = select(APIKey).where(
        APIKey.organization_id == organization.id,
        APIKey.user_id == current_user.id,
    )
    if status_filter:
        query = query.where(APIKey.status == status_filter)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(APIKey.created_at)).offset((page - 1) * page_size).limit(page_size)
    keys = (await db.execute(query)).scalars().all()

    return APIKeyListResponse(
        api_keys=[APIKeyResponse.model_validate(k) for k in keys],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("", response_model=APIKeyCreatedResponse, status_code=status.HTTP_201_CREATED, summary="Create API key")
async def create_api_key(
    key_data: APIKeyCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Create a new API key. The full key is returned only once."""
    raw_key, key_hash = generate_api_key()

    api_key = APIKey(
        name=key_data.name,
        prefix=raw_key[:12],
        key_hash=key_hash,
        status=APIKeyStatus.ACTIVE,
        scopes=key_data.scopes,
        expires_at=key_data.expires_at,
        user_id=current_user.id,
        organization_id=organization.id,
        metadata_={},
    )
    db.add(api_key)
    await db.commit()
    await db.refresh(api_key)

    response = APIKeyCreatedResponse(
        **APIKeyResponse.model_validate(api_key).model_dump(),
        key=raw_key,
    )
    return response


@router.get("/{key_id}", response_model=APIKeyResponse, summary="Get API key")
async def get_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single API key."""
    key = await _get_owned_key(db, key_id, current_user)
    return APIKeyResponse.model_validate(key)


@router.patch("/{key_id}", response_model=APIKeyResponse, summary="Update API key")
async def update_api_key(
    key_id: UUID,
    key_data: APIKeyUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an API key's name, scopes or expiry."""
    key = await _get_owned_key(db, key_id, current_user)
    for field, value in key_data.model_dump(exclude_unset=True).items():
        setattr(key, field, value)
    await db.commit()
    await db.refresh(key)
    return APIKeyResponse.model_validate(key)


@router.post("/{key_id}/revoke", response_model=APIKeyResponse, summary="Revoke API key")
async def revoke_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Revoke an API key immediately."""
    key = await _get_owned_key(db, key_id, current_user)
    key.status = APIKeyStatus.REVOKED
    await db.commit()
    await db.refresh(key)
    return APIKeyResponse.model_validate(key)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete API key")
async def delete_api_key(
    key_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete an API key."""
    key = await _get_owned_key(db, key_id, current_user)
    await db.delete(key)
    await db.commit()
