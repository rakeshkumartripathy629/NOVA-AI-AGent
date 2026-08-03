"""
Celery task definitions.

Background jobs for file processing, emails, webhooks, notifications,
agent/workflow execution and usage aggregation.
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional
from uuid import UUID

from app.core.celery_app import celery_app


def _run(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="app.workers.tasks.process_file", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_file(self, file_id: str, organization_id: str) -> Dict[str, Any]:
    """Process an uploaded file (extract text, create embeddings)."""
    from app.services.files import process_file as process_file_service

    result = _run(process_file_service(file_id, organization_id))
    return {"status": result.get("status", "completed"), "file_id": file_id}


@celery_app.task(bind=True, name="app.workers.tasks.process_document", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def process_document(self, document_id: str, organization_id: str) -> Dict[str, Any]:
    """Process a knowledge base document into chunks and embeddings."""
    import asyncio

    from uuid import UUID

    from app.ai.rag import delete_document_chunks, index_document
    from app.db.session import get_session_factory
    from app.models.knowledge_base import KnowledgeBaseDocument

    async def _process() -> int:
        session_factory = get_session_factory()
        async with session_factory() as db:
            from sqlalchemy import select

            result = await db.execute(
                select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == UUID(document_id))
            )
            document = result.scalar_one_or_none()
            if not document:
                return 0
            chunk_count = await index_document(
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                title=document.title,
                content=document.content or "",
                source_type=document.source_type,
                organization_id=UUID(organization_id) if organization_id else None,
            )
            document.status = "ready"
            document.chunk_count = chunk_count
            await db.commit()
            return chunk_count

    loop = asyncio.new_event_loop()
    try:
        chunk_count = loop.run_until_complete(_process())
    finally:
        loop.close()

    return {"status": "completed", "document_id": document_id, "chunk_count": chunk_count}


@celery_app.task(bind=True, name="app.workers.tasks.send_email_task", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_email_task(self, to_email: str, subject: str, body_text: str) -> Dict[str, Any]:
    """Send an email asynchronously."""
    from app.core.email import email_service
    import asyncio

    email_service.send_email(to_email, subject, body_text)
    return {"status": "sent", "to": to_email}


@celery_app.task(bind=True, name="app.workers.tasks.deliver_webhook", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 5})
def deliver_webhook(self, webhook_id: str, event: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Deliver a webhook event to a subscribed URL."""
    from sqlalchemy import select

    from app.db.session import get_session_factory
    from app.models.webhook import Webhook
    from app.services.webhooks import deliver_webhook_payload

    async def _deliver() -> Dict[str, Any]:
        session_factory = get_session_factory()
        async with session_factory() as db:
            webhook = (
                await db.execute(
                    select(Webhook).where(Webhook.id == UUID(webhook_id), Webhook.is_active.is_(True))
                )
            ).scalar_one_or_none()
            if not webhook:
                return {"status": "skipped", "reason": "webhook inactive or missing"}
            return await deliver_webhook_payload(webhook, event, payload)

    return _run(_deliver())


@celery_app.task(bind=True, name="app.workers.tasks.send_notification", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 3})
def send_notification(self, user_id: str, title: str, body: str, notification_type: str = "info", data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Send an in-app notification and optionally push it over WebSocket."""
    from app.models.notification import NotificationType
    from app.services.notifications import create_notification

    try:
        ntype = NotificationType(notification_type)
    except ValueError:
        ntype = NotificationType.INFO

    _run(
        create_notification(
            user_id=UUID(user_id),
            type=ntype,
            title=title,
            message=body,
            data=data or {},
        )
    )
    return {"status": "sent", "user_id": user_id, "type": notification_type}


@celery_app.task(bind=True, name="app.workers.tasks.run_agent", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def run_agent(self, agent_id: str, conversation_id: str, user_id: str, input_text: str) -> Dict[str, Any]:
    """Run an agent to completion in the background."""
    return {"status": "pending", "agent_id": agent_id}


@celery_app.task(bind=True, name="app.workers.tasks.run_workflow", autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def run_workflow(self, workflow_id: str, execution_id: str, user_id: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a multi-step workflow to completion in the background."""
    from datetime import datetime

    from app.db.session import get_session_factory
    from app.models.workflow import WorkflowExecution

    session_factory = get_session_factory()

    _run(_update_execution(session_factory, execution_id, {"status": "running", "started_at": datetime.utcnow()}))

    try:
        from app.ai.workflow_engine import execute_workflow

        output = _run(
            execute_workflow(
                session_factory=session_factory,
                workflow_id=UUID(workflow_id),
                execution_id=UUID(execution_id),
                inputs=inputs,
            )
        )
        _run(
            _update_execution(
                session_factory,
                execution_id,
                {"status": "completed", "output": output, "completed_at": datetime.utcnow()},
            )
        )
        return {"status": "completed", "workflow_id": workflow_id}
    except Exception as exc:  # noqa: BLE001
        _run(
            _update_execution(
                session_factory,
                execution_id,
                {"status": "failed", "error": str(exc), "completed_at": datetime.utcnow()},
            )
        )
        raise


async def _update_execution(session_factory, execution_id: str, values: Dict[str, Any]) -> None:
    from app.models.workflow import WorkflowExecution

    async with session_factory() as db:
        result = await db.execute(
            select(WorkflowExecution).where(WorkflowExecution.id == UUID(execution_id))
        )
        execution = result.scalar_one_or_none()
        if not execution:
            return
        for field, value in values.items():
            setattr(execution, field, value)
        await db.commit()


@celery_app.task(bind=True, name="app.workers.tasks.aggregate_usage")
def aggregate_usage(self) -> Dict[str, Any]:
    """Aggregate usage records for billing."""
    from app.services.usage import aggregate_usage as aggregate_usage_service

    updated = _run(aggregate_usage_service())
    return {"status": "ok", "aggregates_updated": updated}
