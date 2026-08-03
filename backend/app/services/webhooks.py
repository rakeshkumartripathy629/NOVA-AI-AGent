"""
Webhook delivery service.

Signs and sends payloads to subscribed endpoints, records ``WebhookDelivery``
attempts and updates webhook health statistics.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx

from app.core.logging import get_logger
from app.models.webhook import Webhook, WebhookDelivery

logger = get_logger("services.webhooks")


def sign_payload(payload: Dict[str, Any], secret: str) -> str:
    """Compute an HMAC-SHA256 signature for a webhook payload."""
    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={signature}"


async def deliver_webhook_payload(webhook: Webhook, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deliver a single webhook payload synchronously (called from workers)."""
    from sqlalchemy import select

    from app.db.session import get_session_factory

    session_factory = get_session_factory()
    start = time.monotonic()

    body = json.dumps(payload, separators=(",", ":")).encode()
    signature = sign_payload(payload, webhook.secret)

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "NovaAI-Webhooks/1.0",
        "X-Nova-Event": event,
        "X-Nova-Signature": signature,
        "X-Nova-Timestamp": str(int(time.time())),
        **webhook.headers,
    }

    attempt = 0
    max_attempts = max(webhook.retry_count, 1)
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    response_headers: Optional[dict] = None
    error: Optional[str] = None

    while attempt < max_attempts:
        attempt += 1
        try:
            async with httpx.AsyncClient(timeout=webhook.timeout_seconds) as client:
                resp = await client.post(webhook.url, content=body, headers=headers)
            response_status = resp.status_code
            response_body = resp.text[:2000]
            response_headers = dict(resp.headers)
            if 200 <= resp.status_code < 300:
                break
            error = f"HTTP {resp.status_code}"
            if attempt < max_attempts:
                continue
            break
        except httpx.HTTPError as exc:
            error = str(exc)
            if attempt < max_attempts:
                continue
            break
        except Exception as exc:  # noqa: BLE001
            error = str(exc)
            break

    duration_ms = int((time.monotonic() - start) * 1000)
    delivered = response_status is not None and 200 <= response_status < 300

    async with session_factory() as db:
        delivery = WebhookDelivery(
            webhook_id=webhook.id,
            event=event,
            payload=payload,
            response_status=response_status,
            response_body=response_body,
            response_headers=response_headers,
            attempt=attempt,
            status="delivered" if delivered else "failed",
            error=error,
            duration_ms=duration_ms,
            delivered_at=datetime.utcnow() if delivered else None,
        )
        db.add(delivery)

        current = (
            await db.execute(select(Webhook).where(Webhook.id == webhook.id))
        ).scalar_one_or_none()
        if current:
            current.last_triggered_at = datetime.utcnow()
            if delivered:
                current.last_success_at = datetime.utcnow()
                current.consecutive_failures = 0
            else:
                current.last_failure_at = datetime.utcnow()
                current.failure_count += 1
                current.consecutive_failures += 1
                if current.consecutive_failures >= current.retry_count and current.is_active:
                    current.is_active = False
                    current.disabled_at = datetime.utcnow()
                    logger.warning("Webhook %s auto-disabled after repeated failures", webhook.id)
        await db.commit()

    if delivered:
        logger.info("Webhook %s delivered for event %s in %dms", webhook.id, event, duration_ms)
    else:
        logger.error("Webhook %s failed for event %s: %s", webhook.id, event, error)

    return {
        "status": "delivered" if delivered else "failed",
        "event": event,
        "attempts": attempt,
        "response_status": response_status,
        "error": error,
        "duration_ms": duration_ms,
    }
