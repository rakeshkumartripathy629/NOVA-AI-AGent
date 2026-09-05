"""
Indexing orchestration with a synchronous fallback for environments where
the Celery worker / broker is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy import select

from app.db.session import get_session_factory

logger = logging.getLogger(__name__)

# Tracks in-flight background file jobs so the event loop keeps them alive.
_FILES_TASKS: set = set()


async def index_document_record(document_id, organization_id) -> int:
    """Chunk, embed and store a knowledge base document (inline path)."""
    from app.ai.rag import delete_document_chunks, index_document
    from app.models.knowledge_base import KnowledgeBaseDocument

    chunk_count = 0
    async with get_session_factory()() as db:
        result = await db.execute(
            select(KnowledgeBaseDocument).where(KnowledgeBaseDocument.id == document_id)
        )
        document = result.scalar_one_or_none()
        if not document:
            return 0
        try:
            chunk_count = await index_document(
                knowledge_base_id=document.knowledge_base_id,
                document_id=document.id,
                title=document.title,
                content=document.content or "",
                source_type=document.source_type,
                organization_id=organization_id,
            )
            document.status = "ready"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Indexing failed for document %s: %s", document_id, exc)
            document.status = "failed"
            try:
                await delete_document_chunks(document.id)
            except Exception:  # noqa: BLE001
                pass
        document.chunk_count = chunk_count
        await db.commit()
    return chunk_count


async def queue_document_processing(document_id, organization_id) -> bool:
    """Queue a document via Celery, falling back to inline indexing.

    Returns True when handed to Celery, False when processed inline.
    """
    try:
        from app.workers.tasks import process_document

        process_document.delay(str(document_id), str(organization_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("Celery unavailable (%s); indexing document %s inline", exc, document_id)
        await index_document_record(document_id, organization_id)
        return False


async def queue_file_processing(file_id, organization_id) -> bool:
    """Queue a file via Celery, falling back to inline processing.

    Returns True when handed to Celery, False when processed inline.
    """
    try:
        from app.workers.tasks import process_file

        process_file.delay(str(file_id), str(organization_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("Celery unavailable (%s); processing file %s inline", exc, file_id)
        from app.services.files import process_file as process_file_service

        await process_file_service(str(file_id), str(organization_id))
        return False


def schedule_file_processing(file_id, organization_id) -> None:
    """Start file processing in the background and return immediately.

    Never block the upload request on PDF parsing + embedding. Also do NOT go
    through Celery here: this container has no worker/broker, and importing
    the Celery task module synchronously on the event loop stalls uvicorn long
    enough that the upload response times out (502). A short initial delay
    guarantees the upload response is flushed before any heavy work starts.
    """

    async def _run() -> None:
        await asyncio.sleep(1.0)
        try:
            from app.services.files import process_file as process_file_service

            await process_file_service(str(file_id), str(organization_id))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background file processing failed for %s: %s", file_id, exc)

    task = asyncio.create_task(_run())
    _FILES_TASKS.add(task)
    task.add_done_callback(_FILES_TASKS.discard)


def schedule_document_processing(document_id, organization_id) -> None:
    """Index a knowledge-base document in the background (no Celery)."""

    async def _run() -> None:
        await asyncio.sleep(1.0)
        try:
            await index_document_record(document_id, organization_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Background document indexing failed for %s: %s", document_id, exc)

    task = asyncio.create_task(_run())
    _FILES_TASKS.add(task)
    task.add_done_callback(_FILES_TASKS.discard)
