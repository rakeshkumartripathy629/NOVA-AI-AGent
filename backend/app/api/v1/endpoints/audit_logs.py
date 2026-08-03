"""
Audit log endpoints (organization admin / platform audit).
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_organization
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.audit_log import AuditAction, AuditLog
from app.models.organization import Organization, OrganizationMember
from app.models.user import User

router = APIRouter()


class AuditLogResponse(BaseModel):
    """Audit log response model."""
    id: UUID
    action: str
    resource_type: str
    resource_id: Optional[UUID] = None
    resource_name: Optional[str] = None
    user_id: Optional[UUID] = None
    ip_address: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: int = 0
    changed_fields: List[str] = []
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated audit log list."""
    logs: List[AuditLogResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


async def _require_org_admin(db: AsyncSession, organization: Organization, user: User) -> None:
    result = await db.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization.id,
            OrganizationMember.user_id == user.id,
        )
    )
    member = result.scalar_one_or_none()
    is_owner = organization.owner_id == user.id
    if not is_owner and (not member or member.role.value not in ("owner", "admin")):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization admin access required")


@router.get("", response_model=AuditLogListResponse, summary="List audit logs")
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    action: Optional[AuditAction] = Query(None),
    resource_type: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List audit log entries for the organization."""
    await _require_org_admin(db, organization, current_user)

    query = select(AuditLog).where(AuditLog.organization_id == organization.id)

    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if from_date:
        query = query.where(AuditLog.created_at >= from_date)
    if to_date:
        query = query.where(AuditLog.created_at <= to_date)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(AuditLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    logs = (await db.execute(query)).scalars().all()

    return AuditLogListResponse(
        logs=[AuditLogResponse.model_validate(log) for log in logs],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.get("/{log_id}", response_model=AuditLogResponse, summary="Get audit log entry")
async def get_audit_log(
    log_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get a single audit log entry with full context."""
    await _require_org_admin(db, organization, current_user)

    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.id == log_id, AuditLog.organization_id == organization.id)
        .options(selectinload(AuditLog.user))
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log entry not found")

    data = AuditLogResponse.model_validate(log)
    return {
        **data.model_dump(),
        "user_email": log.user.email if log.user else None,
        "request_id": log.request_id,
        "old_values": log.old_values,
        "new_values": log.new_values,
        "error": log.error,
    }
