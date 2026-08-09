"""
Conversation summary service.

Long conversations are summarized in the background so the assistant can answer
"What did we discuss...?" questions without sending full history to the LLM.
Summaries are stored in ``conversation_summaries`` and embedded for semantic
recall (they appear in the "From your previous conversations" context block).
"""
from __future__ import annotations

import asyncio
from typing import List, Optional
from uuid import UUID

from sqlalchemy import select

from app.ai.providers import default_provider
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.conversation import Conversation
from app.models.conversation_summary import ConversationSummary
from app.models.message import Message, MessageRole, MessageStatus
from app.services.embedding import count_tokens, embedding_service
from app.services.vector_store import SUMMARY_COLLECTION, vector_store

logger = get_logger("memory.conversation_summary")

_SUMMARY_TASKS: set = set()

_SUMMARY_PROMPT = (
    "Summarize the following conversation in 3-6 concise sentences, in the "
    "user's own voice. Capture: the user's goal, facts they stated about "
    "themselves, decisions, and open questions. Keep it self-contained so it "
    "makes sense without the original messages."
)


async def _messages_for(db, conversation_id: UUID, limit: int = 40) -> List[Message]:
    result = await db.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.is_deleted.is_(False),
            Message.status == MessageStatus.COMPLETED,
        )
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return rows


def _format_messages(messages: List[Message]) -> str:
    parts = []
    for m in messages:
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content:
            parts.append(f"{m.role.value}: {m.content}")
    return "\n".join(parts) if parts else ""


async def generate_summary(conversation_id: UUID, user_id: UUID) -> Optional[ConversationSummary]:
    """Summarize a conversation and persist + embed the summary (best effort)."""
    if not settings.MEMORY_SUMMARY_ENABLED:
        return None
    try:
        async with get_db_context() as db:
            conversation = await db.get(Conversation, conversation_id)
            if not conversation:
                return None
            messages = await _messages_for(db, conversation_id)
            text = _format_messages(messages)
            if len(text) < 100:
                return None
            reply = await default_provider().complete(
                messages=[{"role": "user", "content": text}],
                model=settings.MEMORY_SUMMARY_MODEL or None,
                temperature=0.3,
                max_tokens=settings.MEMORY_SUMMARY_MAX_LENGTH,
                system_prompt=_SUMMARY_PROMPT,
            )
            summary = (reply or "").strip()
            if not summary:
                return None

            row = await db.execute(
                select(ConversationSummary).where(
                    ConversationSummary.conversation_id == conversation_id
                )
            )
            existing = row.scalar_one_or_none()
            record = existing or ConversationSummary(
                conversation_id=conversation_id,
                user_id=user_id,
                organization_id=conversation.organization_id,
                summary=summary,
                message_count=conversation.message_count,
                message_end_id=messages[-1].id if messages else None,
                token_estimate=count_tokens(summary),
            )
            if existing:
                record.summary = summary
                record.message_count = conversation.message_count
                if messages:
                    record.message_end_id = messages[-1].id
                record.token_estimate = count_tokens(summary)
            db.add(record)
            await db.commit()
            await db.refresh(record)

        try:
            [vec] = await embedding_service.embed([record.summary])
            await vector_store.ensure_collection(
                SUMMARY_COLLECTION, embedding_service.dimension()
            )
            async with get_db_context() as db:
                db.add(record)
                record.embedding = vec
                await db.commit()
            await vector_store.upsert(
                SUMMARY_COLLECTION,
                str(record.id),
                vec,
                {
                    "user_id": str(user_id),
                    "summary_id": str(record.id),
                    "conversation_id": str(conversation_id),
                    "content": record.summary,
                    "created_at": record.created_at.isoformat() if record.created_at else "",
                },
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Summary embedding failed: %s", exc)

        logger.info("Stored summary for conversation %s", conversation_id)
        return record
    except Exception as exc:  # noqa: BLE001
        logger.warning("Conversation summary failed: %s", exc)
        return None


def schedule_summary(conversation_id: UUID, user_id: UUID) -> None:
    """Fire-and-forget summary generation (never blocks the chat reply)."""
    task = asyncio.create_task(generate_summary(conversation_id, user_id))
    _SUMMARY_TASKS.add(task)
    task.add_done_callback(_SUMMARY_TASKS.discard)


async def relevant_summaries(user_id: UUID, query: str, top_k: int = 3) -> List[str]:
    """Return summary texts relevant to ``query``, scoped to the user."""
    try:
        [qvec] = await embedding_service.embed([query])
    except Exception:  # noqa: BLE001
        return []
    hits = await vector_store.search(
        SUMMARY_COLLECTION, qvec, user_id=user_id, top_k=top_k
    )
    return [str(h["payload"].get("content", "")) for h in hits if h.get("score", 0) > 0.15]
