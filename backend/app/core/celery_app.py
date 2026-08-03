"""
Celery application configuration.

Tasks are discovered from :mod:`app.workers.tasks`.
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "nova_ai",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks",
        "app.workers.scheduled",
    ],
)

celery_app.conf.update(
    task_track_started=settings.CELERY_TASK_TRACK_STARTED,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    worker_prefetch_multiplier=settings.CELERY_WORKER_PREFETCH_MULTIPLIER,
    worker_concurrency=settings.CELERY_WORKER_CONCURRENCY,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.process_file": {"queue": "files"},
        "app.workers.tasks.process_document": {"queue": "files"},
        "app.workers.tasks.send_email_task": {"queue": "emails"},
        "app.workers.tasks.deliver_webhook": {"queue": "webhooks"},
        "app.workers.tasks.send_notification": {"queue": "notifications"},
        "app.workers.tasks.run_agent": {"queue": "agents"},
        "app.workers.tasks.run_workflow": {"queue": "workflows"},
        "app.workers.tasks.aggregate_usage": {"queue": "analytics"},
    },
    task_queues=(
        "default",
        "files",
        "emails",
        "webhooks",
        "notifications",
        "agents",
        "workflows",
        "analytics",
    ),
)

if settings.CELERY_BEAT_SCHEDULE_ENABLED:
    celery_app.conf.beat_schedule = {
        "aggregate-usage-hourly": {
            "task": "app.workers.scheduled.aggregate_usage",
            "schedule": crontab(minute=5),
        },
        "cleanup-expired-sessions-daily": {
            "task": "app.workers.scheduled.cleanup_expired_sessions",
            "schedule": crontab(hour=3, minute=0),
        },
        "retry-failed-webhooks": {
            "task": "app.workers.scheduled.retry_failed_webhooks",
            "schedule": crontab(minute="*/15"),
        },
        "reset-daily-quotas": {
            "task": "app.workers.scheduled.reset_daily_quotas",
            "schedule": crontab(hour=0, minute=0),
        },
        "prune-soft-deleted": {
            "task": "app.workers.scheduled.prune_soft_deleted",
            "schedule": crontab(hour=4, minute=0),
        },
    }
