"""
Organization management endpoints.
"""
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.organization import Organization, OrganizationMember, OrganizationRole


router = APIRouter()


def require_org_permission(*permissions: str):
    """Require the caller to be an active OWNER or ADMIN of the organization.

    Authorization is based on the caller's role *within* the organization,
    not the global `user.role` (which has no org context). Super admins bypass.
    """
    async def permission_checker(
        org_id: UUID,
        current_user: User = Depends(get_current_active_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        if current_user.role == UserRole.SUPER_ADMIN:
            return current_user

        result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.status == "active",
            )
        )
        member = result.scalar_one_or_none()
        if not member or member.role not in (
            OrganizationRole.OWNER,
            OrganizationRole.ADMIN,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permissions[0] if permissions else 'organization:member'}",
            )
        return current_user

    return permission_checker


# Request/Response Models
class OrganizationCreate(BaseModel):
    """Organization create model."""
    name: str = Field(..., min_length=1, max_length=100)
    slug: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    description: Optional[str] = Field(None, max_length=500)
    logo_url: Optional[str] = None
    settings: Optional[dict] = None


class OrganizationUpdate(BaseModel):
    """Organization update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    logo_url: Optional[str] = None
    settings: Optional[dict] = None


class OrganizationResponse(BaseModel):
    """Organization response model."""
    id: UUID
    name: str
    slug: str
    description: Optional[str]
    logo_url: Optional[str]
    owner_id: UUID
    settings: dict
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class OrganizationListResponse(BaseModel):
    """Organization list response model."""
    organizations: List[OrganizationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MemberInvite(BaseModel):
    """Member invite model."""
    email: str
    role: OrganizationRole = OrganizationRole.MEMBER


class MemberUpdate(BaseModel):
    """Member update model."""
    role: OrganizationRole


class MemberResponse(BaseModel):
    """Member response model."""
    id: UUID
    user_id: UUID
    organization_id: UUID
    role: str
    status: str
    invited_by: Optional[UUID]
    joined_at: Optional[datetime]
    created_at: datetime
    user: Optional[dict] = None
    
    class Config:
        from_attributes = True


class MemberListResponse(BaseModel):
    """Member list response model."""
    members: List[MemberResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


def _member_response(member: OrganizationMember, user: Optional[User] = None) -> MemberResponse:
    """Build a MemberResponse, converting the user relationship to a dict.

    MemberResponse.user is `Optional[dict]`, so a raw ORM `model_validate`
    fails when the `user` relationship is loaded as a User object.
    """
    member_user = user or getattr(member, "user", None)
    return MemberResponse(
        id=member.id,
        user_id=member.user_id,
        organization_id=member.organization_id,
        role=member.role,
        status=member.status,
        invited_by=member.invited_by,
        joined_at=member.joined_at.isoformat() if member.joined_at else None,
        created_at=member.created_at.isoformat(),
        user={
            "id": member_user.id,
            "email": member_user.email,
            "username": member_user.username,
            "full_name": member_user.full_name,
            "avatar_url": member_user.avatar_url,
        } if member_user else None,
    )


# Endpoints
@router.get("", response_model=OrganizationListResponse, summary="List organizations")
async def list_organizations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List organizations user belongs to."""
    # Get user's organization IDs
    org_result = await db.execute(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    org_ids = org_result.scalars().all()
    
    if not org_ids:
        return OrganizationListResponse(
            organizations=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
        )
    
    query = select(Organization).where(Organization.id.in_(org_ids))
    
    if search:
        query = query.where(
            or_(
                Organization.name.ilike(f"%{search}%"),
                Organization.slug.ilike(f"%{search}%"),
            )
        )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(Organization.created_at.desc())
    
    result = await db.execute(query)
    organizations = result.scalars().all()
    
    return OrganizationListResponse(
        organizations=[OrganizationResponse.model_validate(o) for o in organizations],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED, summary="Create organization")
async def create_organization(
    org_data: OrganizationCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new organization."""
    # Check if slug is taken
    result = await db.execute(
        select(Organization).where(Organization.slug == org_data.slug)
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Slug already taken",
        )
    
    # Create organization
    org = Organization(
        name=org_data.name,
        slug=org_data.slug,
        description=org_data.description,
        logo_url=org_data.logo_url,
        owner_id=current_user.id,
        settings=org_data.settings or {},
    )
    db.add(org)
    await db.flush()
    
    # Add creator as owner
    member = OrganizationMember(
        organization_id=org.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
        status="active",
    )
    db.add(member)
    
    await db.commit()
    await db.refresh(org)
    
    return OrganizationResponse.model_validate(org)


@router.get("/{org_id}", response_model=OrganizationResponse, summary="Get organization")
async def get_organization(
    org_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get organization by ID."""
    # Check membership
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    return OrganizationResponse.model_validate(org)


@router.patch("/{org_id}", response_model=OrganizationResponse, summary="Update organization")
async def update_organization(
    org_id: UUID,
    org_data: OrganizationUpdate,
    current_user: User = Depends(require_org_permission("organization:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update organization."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Check permission - only owner or admin can update
    member_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == current_user.id,
        )
    )
    member = member_result.scalar_one_or_none()
    
    if not member or member.role not in [OrganizationRole.OWNER, OrganizationRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this organization",
        )
    
    update_data = org_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(org, field, value)
    
    await db.commit()
    await db.refresh(org)
    
    return OrganizationResponse.model_validate(org)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete organization")
async def delete_organization(
    org_id: UUID,
    current_user: User = Depends(require_org_permission("organization:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete organization (owner only)."""
    result = await db.execute(
        select(Organization).where(Organization.id == org_id)
    )
    org = result.scalar_one_or_none()
    
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    
    # Only owner can delete
    if org.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can delete the organization",
        )
    
    # Soft delete
    org.is_deleted = True
    org.deleted_at = datetime.utcnow()
    await db.commit()


# Member endpoints
@router.get("/{org_id}/members", response_model=MemberListResponse, summary="List organization members")
async def list_members(
    org_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[OrganizationRole] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List organization members."""
    # Check membership
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    query = select(OrganizationMember).where(
        OrganizationMember.organization_id == org_id
    ).options(selectinload(OrganizationMember.user))
    
    if role:
        query = query.where(OrganizationMember.role == role)
    
    if status_filter:
        query = query.where(OrganizationMember.status == status_filter)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(OrganizationMember.created_at.desc())
    
    result = await db.execute(query)
    members = result.scalars().all()
    
    return MemberListResponse(
        members=[
            MemberResponse(
                id=m.id,
                user_id=m.user_id,
                organization_id=m.organization_id,
                role=m.role,
                status=m.status,
                invited_by=m.invited_by,
                joined_at=m.joined_at.isoformat() if m.joined_at else None,
                created_at=m.created_at.isoformat(),
                user={
                    "id": m.user.id,
                    "email": m.user.email,
                    "username": m.user.username,
                    "full_name": m.user.full_name,
                    "avatar_url": m.user.avatar_url,
                } if m.user else None,
            )
            for m in members
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/{org_id}/members/invite", response_model=MemberResponse, status_code=status.HTTP_201_CREATED, summary="Invite member")
async def invite_member(
    org_id: UUID,
    invite: MemberInvite,
    current_user: User = Depends(require_org_permission("organization:member:invite")),
    db: AsyncSession = Depends(get_db),
):
    """Invite a member to the organization."""
    # Check if user exists
    result = await db.execute(
        select(User).where(User.email == invite.email)
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email is not registered",
        )

    # Check if already a member
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == user.id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member",
        )

    # Create invitation
    member = OrganizationMember(
        organization_id=org_id,
        user_id=user.id,
        role=invite.role,
        status="active",
        invited_by=current_user.id,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    # TODO: Send invitation email
    
    return _member_response(member, user=user)


@router.patch("/{org_id}/members/{member_id}", response_model=MemberResponse, summary="Update member")
async def update_member(
    org_id: UUID,
    member_id: UUID,
    member_data: MemberUpdate,
    current_user: User = Depends(require_org_permission("organization:member:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update member role."""
    result = await db.execute(
        select(OrganizationMember)
        .options(selectinload(OrganizationMember.user))
        .where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    
    # Cannot change owner role
    if member.role == OrganizationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change owner role",
        )
    
    # Only owner can change admin roles
    if member_data.role == OrganizationRole.ADMIN or member.role == OrganizationRole.ADMIN:
        current_member_result = await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.organization_id == org_id,
                OrganizationMember.user_id == current_user.id,
            )
        )
        current_member = current_member_result.scalar_one_or_none()
        if not current_member or current_member.role != OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner can manage admin roles",
            )
    
    member.role = member_data.role
    await db.commit()
    await db.refresh(member)
    
    return _member_response(member)


@router.delete("/{org_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove member")
async def remove_member(
    org_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_org_permission("organization:member:remove")),
    db: AsyncSession = Depends(get_db),
):
    """Remove member from organization."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    
    # Cannot remove owner
    if member.role == OrganizationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove owner",
        )
    
    # Users can remove themselves, admins can remove others
    current_member_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == org_id,
            OrganizationMember.user_id == current_user.id,
        )
    )
    current_member = current_member_result.scalar_one_or_none()
    
    if member.user_id != current_user.id and current_member.role not in [OrganizationRole.OWNER, OrganizationRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to remove this member",
        )
    
    await db.delete(member)
    await db.commit()


@router.post("/{org_id}/members/{member_id}/resend-invite", summary="Resend invitation")
async def resend_invite(
    org_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_org_permission("organization:member:invite")),
    db: AsyncSession = Depends(get_db),
):
    """Resend invitation to pending member."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.id == member_id,
            OrganizationMember.organization_id == org_id,
            OrganizationMember.status == "pending",
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pending invitation not found",
        )
    
    # TODO: Resend invitation email
    
    return {"message": "Invitation resent"}


# Singular-path aliases for client compatibility
# (some clients call /organization instead of /organizations)
alias_router = APIRouter()
alias_router.add_api_route(
    "/",
    list_organizations,
    methods=["GET"],
    response_model=OrganizationListResponse,
    summary="List organizations (singular alias)",
)
alias_router.add_api_route(
    "/",
    create_organization,
    methods=["POST"],
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create organization (singular alias)",
)
alias_router.add_api_route(
    "/{org_id}",
    get_organization,
    methods=["GET"],
    response_model=OrganizationResponse,
    summary="Get organization (singular alias)",
)
alias_router.add_api_route(
    "/{org_id}",
    update_organization,
    methods=["PATCH"],
    response_model=OrganizationResponse,
    summary="Update organization (singular alias)",
)
alias_router.add_api_route(
    "/{org_id}",
    delete_organization,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete organization (singular alias)",
)


# Import datetime at the end
from datetime import datetime