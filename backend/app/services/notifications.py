"""
Notification service: creates and dispatches notifications across channels.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.core.logging import get_logger
from app.models.notification import Notification, NotificationChannel, NotificationStatus, NotificationType

logger = get_logger("services.notifications")


async def create_notification(
    *,
    user_id: UUID,
    type: NotificationType = NotificationType.INFO,
    title: str,
    message: str,
    organization_id: Optional[UUID] = None,
    channels: Optional[List[NotificationChannel]] = None,
    priority: int = 0,
    reference_type: Optional[str] = None,
    reference_id: Optional[UUID] = None,
    action_url: Optional[str] = None,
    action_label: Optional[str] = None,
    data: Optional[Dict[str, Any]] = None,
) -> Notification:
    """Create a notification row and dispatch realtime + email channels."""
    from sqlalchemy import select

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    channels = channels or [NotificationChannel.IN_APP]

    notification = Notification(
        user_id=user_id,
        organization_id=organization_id,
        type=type,
        title=title,
        message=message,
        channels=channels,
        status=NotificationStatus.PENDING,
        priority=priority,
        reference_type=reference_type,
        reference_id=reference_id,
        action_url=action_url,
        action_label=action_label,
        data=data or {},
    )

    async with session_factory() as db:
        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        # Respect per-channel preferences for email/push
        from app.models.notification import NotificationPreference
        from app.models.user import User

        pref = (
            await db.execute(
                select(NotificationPreference).where(NotificationPreference.user_id == user_id)
            )
        ).scalar_one_or_none()
        user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        user_email = user.email if user else None

    try:
        if NotificationChannel.IN_APP in channels or NotificationChannel.PUSH in channels:
            from app.api.v1.websocket import send_to_user

            await send_to_user(
                user_id,
                {
                    "type": "notification",
                    "data": {
                        "id": str(notification.id),
                        "type": type.value if hasattr(type, "value") else str(type),
                        "title": title,
                        "message": message,
                        "reference_type": reference_type,
                        "reference_id": str(reference_id) if reference_id else None,
                        "action_url": action_url,
                        "action_label": action_label,
                        "created_at": notification.created_at.isoformat() if notification.created_at else None,
                    },
                },
            )
    except Exception:  # noqa: BLE001
        logger.warning("Realtime notification dispatch failed for user %s", user_id, exc_info=True)

    if NotificationChannel.EMAIL in channels and (pref is None or pref.email_enabled) and user_email:
        try:
            from app.core.email import email_service

            email_service.send_email(
                to_email=user_email,
                subject=title,
                body_text=message,
            )
        except Exception:  # noqa: BLE001
            logger.warning("Email notification dispatch failed for user %s", user_id, exc_info=True)

    return notification


async def mark_read(user_id: UUID, notification_id: UUID) -> Optional[Notification]:
    """Mark a single notification as read."""
    from sqlalchemy import select

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as db:
        notification = (
            await db.execute(
                select(Notification).where(
                    Notification.id == notification_id,
                    Notification.user_id == user_id,
                )
            )
        ).scalar_one_or_none()
        if not notification:
            return None
        notification.status = NotificationStatus.READ
        notification.read_at = datetime.utcnow()
        await db.commit()
        await db.refresh(notification)
        return notification


async def mark_all_read(user_id: UUID) -> int:
    """Mark all of a user's notifications as read."""
    from sqlalchemy import update

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    async with session_factory() as db:
        result = await db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.status != NotificationStatus.READ)
            .values(status=NotificationStatus.READ, read_at=datetime.utcnow())
        )
        await db.commit()
        return result.rowcount or 0
