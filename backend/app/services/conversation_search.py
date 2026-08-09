"""
Conversation search service.

Answers "what did we discuss about X last week?" by searching the current
user's conversations (title, rolling summary, and message content). Always
scoped to conversations the user owns or is a member of. Best effort; never
raises.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.conversation import Conversation, ConversationMember
from app.models.conversation_summary import ConversationSummary
from app.models.message import Message, MessageRole

logger = get_logger("memory.conversation_search")


async def search_user_conversations(
    user_id: UUID,
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Search the user's conversations. Returns [{conversation_id, title, summary, snippet, score}]."""
    query = (query or "").strip()
    if not query:
        return []
    term = f"%{query.lower()}%"

    async with get_db_context() as db:
        # Conversation ids the user is allowed to see.
        membership = (
            await db.execute(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == user_id
                )
            )
        ).scalars().all()
        owned = (
            await db.execute(
                select(Conversation.id).where(
                    Conversation.owner_id == user_id,
                    Conversation.is_deleted.is_(False),
                )
            )
        ).scalars().all()
        allowed = set(membership) | set(owned)
        if not allowed:
            return []

        conv_rows = (
            await db.execute(
                select(Conversation)
                .where(
                    Conversation.id.in_(allowed),
                    Conversation.is_deleted.is_(False),
                )
                .order_by(Conversation.last_message_at.desc())
            )
        ).scalars().all()
        conv_by_id = {c.id: c for c in conv_rows}

        # Title / summary keyword matches.
        title_matches = {}
        for c in conv_rows:
            score = 0.0
            if c.title and query.lower() in c.title.lower():
                score += 0.8
            if c.summary and query.lower() in c.summary.lower():
                score += 0.6
            if score > 0:
                title_matches[c.id] = score

        # Message content keyword matches (limit scans to the user's convs).
        msg_hits = {}
        if title_matches or True:
            rows = (
                await db.execute(
                    select(Message.conversation_id, Message.content)
                    .where(
                        Message.conversation_id.in_(allowed),
                        Message.is_deleted.is_(False),
                        Message.role == MessageRole.USER,
                        Message.content.ilike(term),
                    )
                    .order_by(Message.created_at.desc())
                    .limit(200)
                )
            ).all()
            for cid, content in rows:
                cid = UUID(str(cid))
                msg_hits[cid] = max(msg_hits.get(cid, 0.0), 0.7)

        # Summary semantic matches.
        summary_matches = {}
        try:
            from app.services.embedding import embedding_service

            [qvec] = await embedding_service.embed([query])
            from app.services.vector_store import SUMMARY_COLLECTION, vector_store

            summary_hits = await vector_store.search(
                SUMMARY_COLLECTION, qvec, user_id=user_id, top_k=10
            )
            for hit in summary_hits:
                cid = hit["payload"].get("conversation_id")
                if not cid:
                    continue
                try:
                    summary_matches[UUID(str(cid))] = float(hit.get("score", 0.0))
                except ValueError:
                    continue
        except Exception as exc:  # noqa: BLE001
            logger.debug("Summary semantic search failed: %s", exc)

    merged: Dict[UUID, float] = {}
    for bucket in (title_matches, msg_hits, summary_matches):
        for cid, score in bucket.items():
            merged[cid] = max(merged.get(cid, 0.0), score)

    ranked = sorted(
        merged.items(), key=lambda pair: pair[1], reverse=True
    )[:limit]

    results: List[Dict[str, Any]] = []
    for cid, score in ranked:
        conv = conv_by_id.get(cid)
        if not conv:
            continue
        results.append(
            {
                "conversation_id": str(cid),
                "title": conv.title or "Untitled conversation",
                "summary": conv.summary,
                "snippet": "",
                "score": round(score, 4),
            }
        )
    return results
