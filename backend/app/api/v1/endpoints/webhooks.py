"""
Webhook management endpoints for outbound event delivery.
"""
from __future__ import annotations

import secrets
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import get_current_organization
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery

router = APIRouter()


class WebhookCreate(BaseModel):
    """Webhook create model."""
    name: str = Field(..., min_length=1, max_length=255)
    url: str = Field(..., max_length=500)
    events: List[str] = Field(default_factory=list)
    retry_count: int = Field(3, ge=0, le=10)
    timeout_seconds: int = Field(30, ge=1, le=120)
    headers: dict = Field(default_factory=dict)


class WebhookUpdate(BaseModel):
    """Webhook update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    url: Optional[str] = Field(None, max_length=500)
    events: Optional[List[str]] = None
    is_active: Optional[bool] = None
    retry_count: Optional[int] = Field(None, ge=0, le=10)
    timeout_seconds: Optional[int] = Field(None, ge=1, le=120)
    headers: Optional[dict] = None


class WebhookResponse(BaseModel):
    """Webhook response model (secret never exposed)."""
    id: UUID
    name: str
    url: str
    events: List[str] = []
    is_active: bool = True
    retry_count: int = 3
    timeout_seconds: int = 30
    last_triggered_at: Optional[datetime] = None
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    failure_count: int = 0
    consecutive_failures: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class WebhookCreatedResponse(WebhookResponse):
    """Response after creation, includes the signing secret shown once."""
    secret: str


class WebhookListResponse(BaseModel):
    """Paginated webhook list."""
    webhooks: List[WebhookResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DeliveryResponse(BaseModel):
    """Webhook delivery response model."""
    id: UUID
    event: str
    status: str
    attempt: int
    response_status: Optional[int] = None
    error: Optional[str] = None
    duration_ms: int = 0
    delivered_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


async def _get_webhook(db: AsyncSession, webhook_id: UUID, organization: Organization) -> Webhook:
    result = await db.execute(
        select(Webhook).where(
            Webhook.id == webhook_id,
            Webhook.organization_id == organization.id,
        )
    )
    webhook = result.scalar_one_or_none()
    if not webhook:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return webhook


@router.get("", response_model=WebhookListResponse, summary="List webhooks")
async def list_webhooks(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List webhooks for the current organization."""
    query = select(Webhook).where(Webhook.organization_id == organization.id)
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(Webhook.created_at)).offset((page - 1) * page_size).limit(page_size)
    webhooks = (await db.execute(query)).scalars().all()

    return WebhookListResponse(
        webhooks=[WebhookResponse.model_validate(w) for w in webhooks],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("", response_model=WebhookCreatedResponse, status_code=status.HTTP_201_CREATED, summary="Create webhook")
async def create_webhook(
    webhook_data: WebhookCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Create a webhook endpoint. The signing secret is returned only once."""
    secret = secrets.token_urlsafe(32)
    webhook = Webhook(
        organization_id=organization.id,
        name=webhook_data.name,
        url=webhook_data.url,
        secret=secret,
        events=webhook_data.events,
        is_active=True,
        retry_count=webhook_data.retry_count,
        timeout_seconds=webhook_data.timeout_seconds,
        headers=webhook_data.headers,
    )
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)

    response = WebhookCreatedResponse.model_validate(webhook)
    response.secret = secret
    return response


@router.get("/{webhook_id}", response_model=WebhookResponse, summary="Get webhook")
async def get_webhook(
    webhook_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get a single webhook."""
    webhook = await _get_webhook(db, webhook_id, organization)
    return WebhookResponse.model_validate(webhook)


@router.patch("/{webhook_id}", response_model=WebhookResponse, summary="Update webhook")
async def update_webhook(
    webhook_id: UUID,
    webhook_data: WebhookUpdate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Update a webhook."""
    webhook = await _get_webhook(db, webhook_id, organization)
    for field, value in webhook_data.model_dump(exclude_unset=True).items():
        setattr(webhook, field, value)
    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


@router.post("/{webhook_id}/rotate-secret", response_model=WebhookCreatedResponse, summary="Rotate webhook secret")
async def rotate_webhook_secret(
    webhook_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Rotate the webhook signing secret."""
    webhook = await _get_webhook(db, webhook_id, organization)
    secret = secrets.token_urlsafe(32)
    webhook.secret = secret
    await db.commit()
    await db.refresh(webhook)
    response = WebhookCreatedResponse.model_validate(webhook)
    response.secret = secret
    return response


@router.post("/{webhook_id}/test", summary="Send a test webhook delivery")
async def test_webhook(
    webhook_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Send a test payload to the webhook endpoint."""
    webhook = await _get_webhook(db, webhook_id, organization)

    payload = {
        "event": "ping",
        "data": {"message": "Test webhook delivery"},
        "webhook_id": str(webhook.id),
        "timestamp": datetime.utcnow().isoformat(),
    }

    try:
        from app.workers.tasks import deliver_webhook

        deliver_webhook.delay(str(webhook.id), "ping", payload)
        return {"status": "queued", "event": "ping"}
    except Exception:  # noqa: BLE001
        import httpx

        async with httpx.AsyncClient(timeout=webhook.timeout_seconds) as client:
            resp = await client.post(
                webhook.url,
                json=payload,
                headers={"X-Nova-Event": "ping", **webhook.headers},
            )
            resp.raise_for_status()
        return {"status": "delivered", "event": "ping", "response_status": resp.status_code}


@router.get("/{webhook_id}/deliveries", summary="List webhook deliveries")
async def list_deliveries(
    webhook_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List delivery attempts for a webhook."""
    await _get_webhook(db, webhook_id, organization)

    query = (
        select(WebhookDelivery)
        .where(WebhookDelivery.webhook_id == webhook_id)
        .options(selectinload(WebhookDelivery.webhook))
    )
    total = await db.scalar(select(func.count()).select_from(query.subquery()))
    query = query.order_by(desc(WebhookDelivery.created_at)).offset((page - 1) * page_size).limit(page_size)
    deliveries = (await db.execute(query)).scalars().all()

    return {
        "deliveries": [DeliveryResponse.model_validate(d) for d in deliveries],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
        "total_pages": ((total or 0) + page_size - 1) // page_size,
    }


@router.get("/{webhook_id}/deliveries/{delivery_id}", summary="Get webhook delivery")
async def get_delivery(
    webhook_id: UUID,
    delivery_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get a single delivery attempt including the response body."""
    await _get_webhook(db, webhook_id, organization)
    result = await db.execute(
        select(WebhookDelivery).where(
            WebhookDelivery.id == delivery_id,
            WebhookDelivery.webhook_id == webhook_id,
        )
    )
    delivery = result.scalar_one_or_none()
    if not delivery:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return DeliveryResponse.model_validate(delivery)


@router.delete("/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete webhook")
async def delete_webhook(
    webhook_id: UUID,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Delete a webhook."""
    webhook = await _get_webhook(db, webhook_id, organization)
    await db.delete(webhook)
    await db.commit()
