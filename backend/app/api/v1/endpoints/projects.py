"""
Project management endpoints.
"""
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_active_user, require_permission
from app.core.dependencies import generate_slug
from app.db.session import get_db
from app.models.user import User
from app.models.project import Project, ProjectMember, ProjectRole
from app.models.organization import OrganizationMember


router = APIRouter()


# Request/Response Models
class ProjectCreate(BaseModel):
    """Project create model."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    organization_id: UUID
    settings: Optional[dict] = None


class ProjectUpdate(BaseModel):
    """Project update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    settings: Optional[dict] = None
    is_archived: Optional[bool] = None


class ProjectResponse(BaseModel):
    """Project response model."""
    id: UUID
    name: str
    description: Optional[str]
    organization_id: UUID
    owner_id: UUID
    settings: dict
    is_archived: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Project list response model."""
    projects: List[ProjectResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ProjectMemberInvite(BaseModel):
    """Project member invite model."""
    user_id: UUID
    role: ProjectRole = ProjectRole.MEMBER


class ProjectMemberUpdate(BaseModel):
    """Project member update model."""
    role: ProjectRole


class ProjectMemberResponse(BaseModel):
    """Project member response model."""
    id: UUID
    project_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    user: Optional[dict] = None
    
    class Config:
        from_attributes = True


class ProjectMemberListResponse(BaseModel):
    """Project member list response model."""
    members: List[ProjectMemberResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# Endpoints
@router.get("", response_model=ProjectListResponse, summary="List projects")
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    organization_id: Optional[UUID] = Query(None),
    is_archived: Optional[bool] = Query(False),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List projects user has access to."""
    # Get user's organization IDs
    org_result = await db.execute(
        select(OrganizationMember.organization_id).where(
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    org_ids = org_result.scalars().all()
    
    if not org_ids:
        return ProjectListResponse(
            projects=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
        )
    
    # If organization_id specified, verify access
    if organization_id and organization_id not in org_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    # Get project IDs user has access to
    member_result = await db.execute(
        select(ProjectMember.project_id).where(
            ProjectMember.user_id == current_user.id,
        )
    )
    project_ids = member_result.scalars().all()
    
    query = select(Project).where(
        Project.organization_id.in_(org_ids),
        Project.id.in_(project_ids) if project_ids else False,
    )
    
    if organization_id:
        query = query.where(Project.organization_id == organization_id)
    
    if is_archived is not None:
        query = query.where(Project.is_archived == is_archived)
    
    if search:
        query = query.where(
            or_(
                Project.name.ilike(f"%{search}%"),
                Project.description.ilike(f"%{search}%"),
            )
        )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(Project.updated_at.desc())
    
    result = await db.execute(query)
    projects = result.scalars().all()
    
    return ProjectListResponse(
        projects=[ProjectResponse.model_validate(p) for p in projects],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED, summary="Create project")
async def create_project(
    project_data: ProjectCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    # Verify user is member of organization
    org_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == project_data.organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    if not org_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )
    
    base_slug = generate_slug(project_data.name)
    slug = base_slug
    counter = 1
    while (
        await db.execute(
            select(Project.id).where(
                Project.slug == slug,
                Project.organization_id == project_data.organization_id,
            )
        )
    ).scalar_one_or_none():
        counter += 1
        slug = f"{base_slug}-{counter}"

    # Create project
    project = Project(
        name=project_data.name,
        slug=slug,
        description=project_data.description,
        organization_id=project_data.organization_id,
        owner_id=current_user.id,
        settings=project_data.settings or {},
    )
    db.add(project)
    await db.flush()
    
    # Add creator as owner
    member = ProjectMember(
        project_id=project.id,
        user_id=current_user.id,
        role=ProjectRole.OWNER,
    )
    db.add(member)
    
    await db.commit()
    await db.refresh(project)
    
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse, summary="Get project")
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project by ID."""
    # Check membership
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this project",
        )
    
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse, summary="Update project")
async def update_project(
    project_id: UUID,
    project_data: ProjectUpdate,
    current_user: User = Depends(require_permission("project:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update project."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Check permission
    member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    member = member_result.scalar_one_or_none()
    
    if not member or member.role not in [ProjectRole.OWNER, ProjectRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this project",
        )
    
    update_data = project_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(project, field, value)
    
    await db.commit()
    await db.refresh(project)
    
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete project")
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(require_permission("project:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete project (owner only)."""
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Only owner can delete
    if project.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can delete the project",
        )
    
    # Soft delete
    project.is_deleted = True
    project.deleted_at = datetime.utcnow()
    await db.commit()


# Member endpoints
@router.get("/{project_id}/members", response_model=ProjectMemberListResponse, summary="List project members")
async def list_project_members(
    project_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[ProjectRole] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List project members."""
    # Check membership
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this project",
        )
    
    query = select(ProjectMember).where(
        ProjectMember.project_id == project_id
    ).options(selectinload(ProjectMember.user))
    
    if role:
        query = query.where(ProjectMember.role == role)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(ProjectMember.created_at.desc())
    
    result = await db.execute(query)
    members = result.scalars().all()
    
    return ProjectMemberListResponse(
        members=[
            ProjectMemberResponse(
                id=m.id,
                project_id=m.project_id,
                user_id=m.user_id,
                role=m.role,
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


@router.post("/{project_id}/members", response_model=ProjectMemberResponse, status_code=status.HTTP_201_CREATED, summary="Add project member")
async def add_project_member(
    project_id: UUID,
    member_data: ProjectMemberInvite,
    current_user: User = Depends(require_permission("project:member:add")),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to the project."""
    # Check if user exists
    result = await db.execute(
        select(User).where(User.id == member_data.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Check if already a member
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == member_data.user_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member",
        )
    
    # Verify user is in same organization
    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one_or_none()
    
    org_result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == project.organization_id,
            OrganizationMember.user_id == member_data.user_id,
            OrganizationMember.status == "active",
        )
    )
    if not org_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User must be a member of the project's organization",
        )
    
    # Create member
    member = ProjectMember(
        project_id=project_id,
        user_id=member_data.user_id,
        role=member_data.role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    return ProjectMemberResponse.model_validate(member)


@router.patch("/{project_id}/members/{member_id}", response_model=ProjectMemberResponse, summary="Update project member")
async def update_project_member(
    project_id: UUID,
    member_id: UUID,
    member_data: ProjectMemberUpdate,
    current_user: User = Depends(require_permission("project:member:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update project member role."""
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    
    # Cannot change owner role
    if member.role == ProjectRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change owner role",
        )
    
    # Only owner can change admin roles
    if member_data.role == ProjectRole.ADMIN or member.role == ProjectRole.ADMIN:
        current_member_result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        current_member = current_member_result.scalar_one_or_none()
        if not current_member or current_member.role != ProjectRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner can manage admin roles",
            )
    
    member.role = member_data.role
    await db.commit()
    await db.refresh(member)
    
    return ProjectMemberResponse.model_validate(member)


@router.delete("/{project_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove project member")
async def remove_project_member(
    project_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_permission("project:member:remove")),
    db: AsyncSession = Depends(get_db),
):
    """Remove member from project."""
    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.id == member_id,
            ProjectMember.project_id == project_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    
    # Cannot remove owner
    if member.role == ProjectRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove owner",
        )
    
    # Users can remove themselves, admins can remove others
    current_member_result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == current_user.id,
        )
    )
    current_member = current_member_result.scalar_one_or_none()
    
    if member.user_id != current_user.id and current_member.role not in [ProjectRole.OWNER, ProjectRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to remove this member",
        )
    
    await db.delete(member)
    await db.commit()


# Import datetime at the end
from datetime import datetime