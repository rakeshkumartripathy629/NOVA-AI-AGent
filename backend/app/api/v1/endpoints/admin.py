"""
Platform admin endpoints (superuser only).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user, get_current_superuser
from app.db.session import get_db
from app.models.audit_log import AuditLog
from app.models.billing import Invoice, Subscription
from app.models.file import File as FileModel
from app.models.organization import Organization
from app.models.user import User

router = APIRouter()


class StatsResponse(BaseModel):
    """Platform statistics response model."""
    total_users: int = 0
    total_organizations: int = 0
    total_files: int = 0
    total_files_size: int = 0
    total_subscriptions: int = 0
    active_subscriptions: int = 0
    total_invoices: int = 0
    revenue: int = 0


class AdminUserResponse(BaseModel):
    """Admin user response model."""
    id: UUID
    email: str
    username: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class AdminOrgResponse(BaseModel):
    """Admin organization response model."""
    id: UUID
    name: str
    slug: str
    plan: str = "free"
    status: str
    owner_id: Optional[UUID] = None
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("/stats", response_model=StatsResponse, summary="Platform statistics")
async def platform_stats(
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """Return high-level platform statistics."""
    return StatsResponse(
        total_users=await db.scalar(select(func.count()).select_from(User)) or 0,
        total_organizations=await db.scalar(select(func.count()).select_from(Organization)) or 0,
        total_files=await db.scalar(
            select(func.count()).select_from(FileModel).where(FileModel.is_deleted.is_(False))
        )
        or 0,
        total_files_size=await db.scalar(
            select(func.coalesce(func.sum(FileModel.file_size), 0)).where(FileModel.is_deleted.is_(False))
        )
        or 0,
        total_subscriptions=await db.scalar(select(func.count()).select_from(Subscription)) or 0,
        active_subscriptions=await db.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(Subscription.status.in_(["active", "trialing"]))
        )
        or 0,
        total_invoices=await db.scalar(select(func.count()).select_from(Invoice)) or 0,
        revenue=await db.scalar(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(Invoice.status == "paid")
        )
        or 0,
    )


@router.get("/users", response_model=List[AdminUserResponse], summary="List all users")
async def list_all_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """List all platform users."""
    query = select(User)
    if search:
        query = query.where(
            User.email.ilike(f"%{search}%") | User.username.ilike(f"%{search}%")
        )
    query = query.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size)
    users = (await db.execute(query)).scalars().all()
    return [AdminUserResponse.model_validate(u) for u in users]


@router.get("/organizations", response_model=List[AdminOrgResponse], summary="List all organizations")
async def list_all_organizations(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """List all platform organizations."""
    query = select(Organization)
    if search:
        query = query.where(Organization.name.ilike(f"%{search}%"))
    query = query.order_by(desc(Organization.created_at)).offset((page - 1) * page_size).limit(page_size)
    orgs = (await db.execute(query)).scalars().all()
    return [AdminOrgResponse.model_validate(o) for o in orgs]


@router.get("/audit-logs", summary="List platform audit logs")
async def list_platform_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    current_user: User = Depends(get_current_superuser),
    db: AsyncSession = Depends(get_db),
):
    """List audit log entries across all organizations."""
    query = select(AuditLog).order_by(desc(AuditLog.created_at))
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.offset((page - 1) * page_size).limit(page_size)
    logs = (await db.execute(query)).scalars().all()

    return {
        "logs": [
            {
                "id": str(log.id),
                "action": log.action.value if hasattr(log.action, "value") else str(log.action),
                "resource_type": log.resource_type,
                "organization_id": str(log.organization_id) if log.organization_id else None,
                "user_id": str(log.user_id) if log.user_id else None,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
        "total_pages": ((total or 0) + page_size - 1) // page_size,
    }
