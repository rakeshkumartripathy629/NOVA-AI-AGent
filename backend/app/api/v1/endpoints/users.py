"""
User management endpoints.
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_active_user, get_current_superuser, require_permission
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.models.organization import OrganizationMember
from app.models.conversation import Conversation
from app.models.message import Message


router = APIRouter()


# Request/Response Models
class UserUpdate(BaseModel):
    """User update model."""
    full_name: Optional[str] = Field(None, max_length=100)
    avatar_url: Optional[str] = None
    bio: Optional[str] = Field(None, max_length=500)
    timezone: Optional[str] = Field(None, max_length=50)
    locale: Optional[str] = Field(None, max_length=10)
    settings: Optional[dict] = None
    preferences: Optional[dict] = None


class UserResponse(BaseModel):
    """User response model."""
    id: UUID
    email: str
    username: str
    full_name: Optional[str]
    avatar_url: Optional[str]
    bio: Optional[str]
    timezone: Optional[str]
    locale: Optional[str]
    role: str
    status: str
    email_verified: bool
    is_active: bool
    is_superuser: bool
    last_login_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    preferences: Optional[dict] = None
    
    class Config:
        from_attributes = True


class UserListResponse(BaseModel):
    """User list response model."""
    users: List[UserResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class UserRoleUpdate(BaseModel):
    """User role update model."""
    role: UserRole


class UserStatusUpdate(BaseModel):
    """User status update model."""
    status: UserStatus


# Endpoints
@router.get("", response_model=UserListResponse, summary="List users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    role: Optional[UserRole] = Query(None),
    status: Optional[UserStatus] = Query(None),
    current_user: User = Depends(require_permission("user:read")),
    db: AsyncSession = Depends(get_db),
):
    """List users with pagination and filters."""
    query = select(User)
    
    # Apply filters
    if search:
        query = query.where(
            or_(
                User.email.ilike(f"%{search}%"),
                User.username.ilike(f"%{search}%"),
                User.full_name.ilike(f"%{search}%"),
            )
        )
    
    if role:
        query = query.where(User.role == role)
    
    if status:
        query = query.where(User.status == status)
    
    # Non-superusers can only see users in their organization
    if current_user.role != UserRole.SUPER_ADMIN:
        # Get user's organization IDs
        org_result = await db.execute(
            select(OrganizationMember.organization_id).where(
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.status == "active",
            )
        )
        org_ids = org_result.scalars().all()
        
        if org_ids:
            # Get users in these organizations
            member_result = await db.execute(
                select(OrganizationMember.user_id).where(
                    OrganizationMember.organization_id.in_(org_ids),
                    OrganizationMember.status == "active",
                )
            )
            user_ids = member_result.scalars().all()
            query = query.where(User.id.in_(user_ids))
        else:
            query = query.where(User.id == current_user.id)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(User.created_at.desc())
    
    result = await db.execute(query)
    users = result.scalars().all()
    
    return UserListResponse(
        users=[UserResponse.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/me", response_model=UserResponse, summary="Get current user profile")
async def get_my_profile(
    current_user: User = Depends(get_current_active_user),
):
    """Get current user's profile."""
    return UserResponse.model_validate(current_user)


@router.patch("/me", response_model=UserResponse, summary="Update current user profile")
async def update_my_profile(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's profile."""
    update_data = user_data.model_dump(exclude_unset=True)

    if "preferences" in update_data and update_data["preferences"]:
        merged = dict(current_user.preferences or {})
        merged.update(update_data["preferences"])
        update_data["preferences"] = merged
    
    result = await db.execute(
        select(User).where(User.id == current_user.id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.model_validate(user)


@router.post("/me/export", summary="Export my data (GDPR)")
async def export_my_data(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Export all personal data as JSON for the current user."""
    org_result = await db.execute(
        select(OrganizationMember)
        .where(OrganizationMember.user_id == current_user.id)
        .options(selectinload(OrganizationMember.organization))
    )
    organizations = [
        {
            "id": str(m.organization_id),
            "name": m.organization.name,
            "slug": m.organization.slug,
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
        }
        for m in org_result.scalars().all()
    ]

    conversations = (
        (await db.execute(select(Conversation).where(Conversation.owner_id == current_user.id)))
        .scalars()
        .all()
    )
    conversation_list = [
        {
            "id": str(c.id),
            "title": c.title,
            "model": c.model,
            "system_prompt": c.system_prompt,
            "message_count": c.message_count,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
        }
        for c in conversations
    ]

    messages = (
        (await db.execute(select(Message).where(Message.user_id == current_user.id)))
        .scalars()
        .all()
    )
    message_list = [
        {
            "id": str(m.id),
            "conversation_id": str(m.conversation_id),
            "role": m.role.value if hasattr(m.role, "value") else str(m.role),
            "content": m.content,
            "model": m.model,
            "created_at": m.created_at.isoformat() if m.created_at else None,
        }
        for m in messages
    ]

    return {
        "exported_at": datetime.utcnow().isoformat(),
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "username": current_user.username,
            "full_name": current_user.full_name,
            "role": current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
        },
        "organizations": organizations,
        "conversations": conversation_list,
        "messages": message_list,
    }


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT, summary="Delete my account (GDPR)")
async def delete_my_account(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the current user's account and anonymize personal data."""
    result = await db.execute(
        select(User).where(User.id == current_user.id)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.is_active = False
    user.status = UserStatus.DELETED
    user.is_deleted = True
    user.deleted_at = datetime.utcnow()
    user.email = f"deleted-{user.id.hex[:12]}@nova-ai.invalid"
    user.username = f"deleted_user_{user.id.hex[:12]}"
    user.full_name = None
    user.avatar_url = None
    user.bio = None
    user.hashed_password = None
    user.preferences = {}
    user.two_factor_secret = None
    await db.commit()


@router.get("/{user_id}", response_model=UserResponse, summary="Get user by ID")
async def get_user(
    user_id: UUID,
    current_user: User = Depends(require_permission("user:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get user by ID."""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Check permission
    if current_user.role != UserRole.SUPER_ADMIN and current_user.id != user_id:
        # Check if in same organization
        org_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.organization_id.in_(
                    select(OrganizationMember.organization_id).where(
                        OrganizationMember.user_id == user_id,
                        OrganizationMember.status == "active",
                    )
                ),
                OrganizationMember.status == "active",
            )
        )
        if not org_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to view this user",
            )
    
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse, summary="Update user")
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    current_user: User = Depends(require_permission("user:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update user by ID (admin only)."""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Check permission
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this user",
        )
    
    update_data = user_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.model_validate(user)


@router.patch("/{user_id}/role", response_model=UserResponse, summary="Update user role")
async def update_user_role(
    user_id: UUID,
    role_data: UserRoleUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """Update user role (super admin only)."""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    user.role = role_data.role
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.model_validate(user)


@router.patch("/{user_id}/status", response_model=UserResponse, summary="Update user status")
async def update_user_status(
    user_id: UUID,
    status_data: UserStatusUpdate,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """Update user status (super admin only)."""
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    user.status = status_data.status
    user.is_active = status_data.status == UserStatus.ACTIVE
    await db.commit()
    await db.refresh(user)
    
    return UserResponse.model_validate(user)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete user")
async def delete_user(
    user_id: UUID,
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """Delete user (super admin only)."""
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )
    
    result = await db.execute(
        select(User).where(User.id == user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Soft delete
    user.is_deleted = True
    user.deleted_at = datetime.utcnow()
    await db.commit()


@router.get("/{user_id}/organizations", summary="Get user's organizations")
async def get_user_organizations(
    user_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get organizations user belongs to."""
    # Check permission
    if current_user.role != UserRole.SUPER_ADMIN and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized",
        )
    
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        ).options(selectinload(OrganizationMember.organization))
    )
    members = result.scalars().all()
    
    return [
        {
            "id": m.organization.id,
            "name": m.organization.name,
            "slug": m.organization.slug,
            "role": m.role,
            "status": m.status,
        }
        for m in members
    ]
