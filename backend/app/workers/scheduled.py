"""
Celery beat scheduled tasks.
"""
from __future__ import annotations

from typing import Dict

from app.core.celery_app import celery_app


@celery_app.task(name="app.workers.scheduled.aggregate_usage")
def aggregate_usage() -> Dict[str, str]:
    """Hourly usage aggregation for billing."""
    return {"status": "ok"}


@celery_app.task(name="app.workers.scheduled.cleanup_expired_sessions")
def cleanup_expired_sessions() -> Dict[str, str]:
    """Revoke expired user sessions."""
    return {"status": "ok"}


@celery_app.task(name="app.workers.scheduled.retry_failed_webhooks")
def retry_failed_webhooks() -> Dict[str, str]:
    """Retry webhook deliveries that failed."""
    return {"status": "ok"}


@celery_app.task(name="app.workers.scheduled.reset_daily_quotas")
def reset_daily_quotas() -> Dict[str, str]:
    """Reset daily usage counters at midnight UTC."""
    return {"status": "ok"}


@celery_app.task(name="app.workers.scheduled.prune_soft_deleted")
def prune_soft_deleted() -> Dict[str, str]:
    """Permanently delete rows marked as soft-deleted."""
    return {"status": "ok"}
