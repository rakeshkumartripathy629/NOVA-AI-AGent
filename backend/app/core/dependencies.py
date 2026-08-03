"""
Shared FastAPI dependencies.

Provides organization scoping, pagination, current-organization resolution
and request-context helpers used across endpoints.
"""
from __future__ import annotations

import re
from typing import Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.models.user import User


class PaginationParams:
    """Query params for paginated list endpoints."""

    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        sort_by: Optional[str] = Query(None),
        sort_order: str = Query("desc"),
    ) -> None:
        self.page = page
        self.page_size = page_size
        self.sort_by = sort_by
        self.sort_order = sort_order
        self.offset = (page - 1) * page_size

    @property
    def total_pages(self, total: int) -> int:
        return (total + self.page_size - 1) // self.page_size


async def resolve_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Resolve an organization and verify the user is an active member."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    result = await db.execute(
        select(Organization).where(
            Organization.id == organization_id,
            Organization.is_deleted.is_(False),
        )
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return org


async def require_org_admin(
    organization: Organization = Depends(resolve_organization),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Require owner/admin role within the organization."""
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == current_user.id,
            OrganizationMember.status == "active",
        )
    )
    member = result.scalar_one_or_none()
    if not member or member.role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires organization admin access",
        )
    return organization


async def get_current_organization(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> Organization:
    """Resolve the acting organization.

    Uses the ``X-Organization-ID`` header when present, otherwise falls back
    to the user's first active organization.
    """
    header_org_id = request.headers.get("X-Organization-ID")
    org_id = UUID(header_org_id) if header_org_id else None

    memberships = (
        await db.execute(
            select(OrganizationMember).where(
                OrganizationMember.user_id == current_user.id,
                OrganizationMember.status == "active",
            )
        )
    ).scalars().all()
    if not memberships:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to any organization",
        )

    active_ids = {m.organization_id for m in memberships}
    if org_id and org_id not in active_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this organization",
        )

    target_id = org_id or memberships[0].organization_id
    result = await db.execute(
        select(Organization).where(
            Organization.id == target_id,
            Organization.is_deleted.is_(False),
        )
    )
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )
    return org


def generate_slug(name: str) -> str:
    """Convert a name into a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "untitled"


def get_request_id(request: Request) -> str:
    """Return or generate a request correlation id."""
    request_id = request.headers.get("X-Request-ID")
    if request_id:
        return request_id
    import uuid as _uuid
    return str(_uuid.uuid4())
