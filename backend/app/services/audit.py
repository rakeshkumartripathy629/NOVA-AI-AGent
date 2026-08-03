"""
Audit logging service: records auditable actions for security and compliance.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.logging import get_logger
from app.models.audit_log import AuditAction, AuditLog

logger = get_logger("services.audit")


async def record_audit_event(
    *,
    action: AuditAction,
    resource_type: str,
    resource_id: Optional[UUID] = None,
    resource_name: Optional[str] = None,
    user_id: Optional[UUID] = None,
    organization_id: Optional[UUID] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    request_id: Optional[str] = None,
    endpoint: Optional[str] = None,
    method: Optional[str] = None,
    status_code: Optional[int] = None,
    duration_ms: int = 0,
    old_values: Optional[Dict[str, Any]] = None,
    new_values: Optional[Dict[str, Any]] = None,
    changed_fields: Optional[List[str]] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> AuditLog:
    """Insert an immutable audit log entry."""
    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    entry = AuditLog(
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_name=resource_name,
        user_id=user_id,
        organization_id=organization_id,
        ip_address=ip_address,
        user_agent=user_agent,
        request_id=request_id,
        endpoint=endpoint,
        method=method,
        status_code=status_code,
        duration_ms=duration_ms,
        old_values=old_values,
        new_values=new_values,
        changed_fields=changed_fields or [],
        error=error,
        metadata_=metadata or {},
    )
    async with session_factory() as db:
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
    return entry
