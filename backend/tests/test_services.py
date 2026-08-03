"""Integration tests for the service layer against a real (test) database."""
from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from app.models.audit_log import AuditAction, AuditLog
from app.models.notification import Notification, NotificationStatus
from app.models.usage import UsageAggregate, UsageRecord, UsageType
from app.models.webhook import Webhook, WebhookDelivery
from app.services.audit import record_audit_event
from app.services.notifications import create_notification
from app.services.usage import aggregate_usage, record_usage
from app.services.webhooks import deliver_webhook_payload, sign_payload


@pytest.fixture
async def organization(db_session, superuser):
    from app.models.organization import Organization

    owner = await superuser()
    org = Organization(
        name=f"Test Org {uuid4().hex[:8]}",
        slug=f"test-org-{uuid4().hex[:8]}",
        owner_id=owner.id,
    )
    db_session.add(org)
    await db_session.commit()
    await db_session.refresh(org)
    return org


# --- Audit -----------------------------------------------------------

@pytest.mark.asyncio
async def test_record_audit_event(db_session, superuser):
    user = await superuser()
    entry = await record_audit_event(
        action=AuditAction.CREATE,
        resource_type="conversation",
        resource_name="My Chat",
        user_id=user.id,
        ip_address="127.0.0.1",
        endpoint="/api/v1/conversations",
        method="POST",
        status_code=201,
    )
    assert entry.id is not None
    assert entry.action == AuditAction.CREATE

    fetched = await db_session.get(AuditLog, entry.id)
    assert fetched is not None
    assert fetched.resource_name == "My Chat"
    assert fetched.endpoint == "/api/v1/conversations"


# --- Notifications ---------------------------------------------------

@pytest.mark.asyncio
async def test_create_notification_in_app(db_session, superuser, monkeypatch):
    user = await superuser()

    async def fake_send_to_user(*args, **kwargs):
        return None

    monkeypatch.setattr("app.api.v1.websocket.send_to_user", fake_send_to_user)

    notification = await create_notification(
        user_id=user.id,
        title="Hello",
        message="World",
    )
    assert notification.id is not None
    assert notification.title == "Hello"

    fetched = await db_session.get(Notification, notification.id)
    assert fetched is not None
    assert fetched.status == NotificationStatus.PENDING


# --- Usage -----------------------------------------------------------

@pytest.mark.asyncio
async def test_record_and_aggregate_usage(db_session, organization):
    first = await record_usage(
        organization_id=organization.id,
        type=UsageType.TOKEN,
        quantity=100,
        unit="tokens",
    )
    second = await record_usage(
        organization_id=organization.id,
        type=UsageType.TOKEN,
        quantity=50,
        unit="tokens",
    )
    assert first.id is not None
    assert second.id is not None

    updated = await aggregate_usage()
    assert updated >= 1

    agg = (
        await db_session.execute(
            select(UsageAggregate).where(UsageAggregate.organization_id == organization.id)
        )
    ).scalars().first()
    assert agg is not None
    assert agg.total_quantity == 150

    count = (
        await db_session.execute(
            select(func.count()).select_from(UsageRecord).where(UsageRecord.organization_id == organization.id)
        )
    ).scalar_one()
    assert count == 2


# --- Webhooks --------------------------------------------------------

@pytest.mark.asyncio
async def test_sign_payload_roundtrip():
    payload = {"event": "test", "data": {"id": 1}}
    signature = sign_payload(payload, "sekret")
    assert signature.startswith("sha256=")
    assert sign_payload(payload, "sekret") == signature
    assert sign_payload(payload, "other") != signature


@pytest.mark.asyncio
async def test_deliver_webhook_success(db_session, organization, monkeypatch):
    webhook = Webhook(
        organization_id=organization.id,
        name="test-hook",
        url="https://example.com/hook",
        secret="sekret",
        events=["message.created"],
        retry_count=3,
        timeout_seconds=5,
    )
    db_session.add(webhook)
    await db_session.commit()
    await db_session.refresh(webhook)

    class FakeResponse:
        status_code = 200
        text = "ok"
        headers = {"content-type": "application/json"}

    async def fake_post(self, url, content=None, headers=None):
        assert url == "https://example.com/hook"
        return FakeResponse()

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await deliver_webhook_payload(webhook, "message.created", {"hello": "world"})
    assert result["status"] == "delivered"
    assert result["response_status"] == 200

    delivery = (
        await db_session.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook.id))
    ).scalars().first()
    assert delivery is not None
    assert delivery.status == "delivered"

    await db_session.refresh(webhook)
    assert webhook.last_success_at is not None
    assert webhook.consecutive_failures == 0


@pytest.mark.asyncio
async def test_deliver_webhook_failure_then_disabled(db_session, organization, monkeypatch):
    webhook = Webhook(
        organization_id=organization.id,
        name="failing-hook",
        url="https://example.com/fail",
        secret="sekret",
        events=["message.created"],
        retry_count=1,
        timeout_seconds=1,
    )
    db_session.add(webhook)
    await db_session.commit()
    await db_session.refresh(webhook)

    async def fake_post(self, url, content=None, headers=None):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    result = await deliver_webhook_payload(webhook, "message.created", {"hello": "world"})
    assert result["status"] == "failed"
    assert result["attempts"] == 1

    delivery = (
        await db_session.execute(select(WebhookDelivery).where(WebhookDelivery.webhook_id == webhook.id))
    ).scalars().first()
    assert delivery.status == "failed"
    assert "connection refused" in (delivery.error or "")

    await db_session.refresh(webhook)
    assert webhook.consecutive_failures == 1
    assert webhook.failure_count == 1
    assert webhook.is_active is False
    assert webhook.disabled_at is not None
