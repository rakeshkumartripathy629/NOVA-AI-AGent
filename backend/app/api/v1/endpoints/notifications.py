"""
Notification endpoints for in-app delivery and preferences.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.notification import Notification, NotificationPreference, NotificationStatus
from app.models.user import User

router = APIRouter()


class NotificationResponse(BaseModel):
    """Notification response model."""
    id: UUID
    type: str
    title: str
    message: str
    channels: List[str] = []
    status: str
    priority: int = 0
    reference_type: Optional[str] = None
    reference_id: Optional[UUID] = None
    action_url: Optional[str] = None
    action_label: Optional[str] = None
    read_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    """Paginated notification list."""
    notifications: List[NotificationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class PreferenceResponse(BaseModel):
    """Notification preference response model."""
    email_enabled: bool = True
    push_enabled: bool = True
    in_app_enabled: bool = True
    sms_enabled: bool = False
    marketing_enabled: bool = False
    security_enabled: bool = True
    billing_enabled: bool = True
    product_enabled: bool = True
    mention_enabled: bool = True
    assignment_enabled: bool = True
    share_enabled: bool = True
    invitation_enabled: bool = True
    digest_frequency: str = "daily"
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    timezone: str = "UTC"

    class Config:
        from_attributes = True


class PreferenceUpdate(BaseModel):
    """Notification preference update model."""
    email_enabled: Optional[bool] = None
    push_enabled: Optional[bool] = None
    in_app_enabled: Optional[bool] = None
    sms_enabled: Optional[bool] = None
    marketing_enabled: Optional[bool] = None
    security_enabled: Optional[bool] = None
    billing_enabled: Optional[bool] = None
    product_enabled: Optional[bool] = None
    mention_enabled: Optional[bool] = None
    assignment_enabled: Optional[bool] = None
    share_enabled: Optional[bool] = None
    invitation_enabled: Optional[bool] = None
    digest_frequency: Optional[str] = Field(None, max_length=20)
    quiet_hours_start: Optional[str] = Field(None, max_length=5)
    quiet_hours_end: Optional[str] = Field(None, max_length=5)
    timezone: Optional[str] = Field(None, max_length=50)


async def _get_notification(db: AsyncSession, notification_id: UUID, user: User) -> Notification:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.user_id == user.id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification


@router.get("", response_model=NotificationListResponse, summary="List notifications")
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[NotificationStatus] = Query(None, alias="status"),
    unread_only: bool = Query(False),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List notifications for the current user."""
    query = select(Notification).where(Notification.user_id == current_user.id)

    if status_filter:
        query = query.where(Notification.status == status_filter)
    elif unread_only:
        query = query.where(Notification.status != NotificationStatus.READ)

    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(Notification.created_at)).offset((page - 1) * page_size).limit(page_size)
    notifications = (await db.execute(query)).scalars().all()

    return NotificationListResponse(
        notifications=[NotificationResponse.model_validate(n) for n in notifications],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.get("/unread-count", summary="Unread notification count")
async def unread_count(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the number of unread notifications for the current user."""
    query = select(func.count()).where(
        Notification.user_id == current_user.id,
        Notification.status != NotificationStatus.READ,
    )
    return {"count": await db.scalar(query) or 0}


@router.get("/preferences", response_model=PreferenceResponse, summary="Get notification preferences")
async def get_preferences(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get notification preferences for the current user."""
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        pref = NotificationPreference(user_id=current_user.id)
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return PreferenceResponse.model_validate(pref)


@router.put("/preferences", response_model=PreferenceResponse, summary="Update notification preferences")
async def update_preferences(
    update: PreferenceUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update notification preferences for the current user."""
    result = await db.execute(
        select(NotificationPreference).where(NotificationPreference.user_id == current_user.id)
    )
    pref = result.scalar_one_or_none()
    if not pref:
        pref = NotificationPreference(user_id=current_user.id)
        db.add(pref)

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(pref, field, value)

    await db.commit()
    await db.refresh(pref)
    return PreferenceResponse.model_validate(pref)


@router.patch("/{notification_id}/read", response_model=NotificationResponse, summary="Mark notification as read")
async def mark_read(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark a notification as read."""
    from datetime import datetime

    notification = await _get_notification(db, notification_id, current_user)
    if notification.status != NotificationStatus.READ:
        notification.status = NotificationStatus.READ
        notification.read_at = datetime.utcnow()
        await db.commit()
        await db.refresh(notification)
    return NotificationResponse.model_validate(notification)


@router.post("/read-all", summary="Mark all notifications as read")
async def mark_all_read(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark all of the current user's notifications as read."""
    from datetime import datetime

    from sqlalchemy import update

    result = await db.execute(
        update(Notification)
        .where(
            Notification.user_id == current_user.id,
            Notification.status != NotificationStatus.READ,
        )
        .values(status=NotificationStatus.READ, read_at=datetime.utcnow())
    )
    await db.commit()
    return {"updated": result.rowcount}


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete notification")
async def delete_notification(
    notification_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a notification."""
    notification = await _get_notification(db, notification_id, current_user)
    await db.delete(notification)
    await db.commit()
