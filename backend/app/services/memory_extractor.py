"""
Memory extraction service.

Turns a conversation turn into durable memory candidates using the default LLM
provider, then deduplicates and merges them into the user's existing memories.
Conflict detection: when a new fact clearly contradicts/updates an existing
one in the same category, the existing memory is superseded instead of both
being kept, so newer explicit information wins.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select

from app.ai.providers import ProviderError, default_provider
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.memory import MemoryCategory, MemoryItem

logger = get_logger("memory.extractor")

_EXTRACTION_SYSTEM_PROMPT = """You extract durable facts worth remembering about the user from a conversation turn.
Return ONLY a JSON array of objects with fields:
{"content": str, "category": "<category>", "importance": int 1-5, "confidence": float 0-1}.
Categories: profile, skills, education, work_experience, project, goals, interests,
preference, technical_preference, past_event, fact, topic.
Rules:
- Only extract stable, reusable facts: personal details, skills, education, work
  experience, projects, goals, interests, preferences, important past events.
- Do NOT extract the assistant's reply, generic statements, or filler.
- Skip anything already covered by the "Existing memories" list.
- If the user explicitly corrects or replaces an existing fact (e.g. "I switched
  from MongoDB to PostgreSQL"), return the NEW fact and set "supersedes" to the
  exact content of the existing memory it replaces.
- content must be a self-contained sentence in second person ("You ..."),
  e.g. "You prefer dark mode for code editors."
- confidence: 0.9+ for explicit statements, ~0.7 for implied facts, lower for guesses.
- Return [] if nothing is worth remembering."""

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _normalize(text: str) -> str:
    """Lowercase and strip non-alphanumeric characters for fuzzy dedup."""
    return _NORMALIZE_RE.sub(" ", text.lower()).strip()


async def _extract_candidates(
    user_content: str,
    assistant_content: str,
    existing: List[str],
) -> List[Dict[str, Any]]:
    """Ask the default provider for memory candidates from a conversation turn."""
    messages = [
        {
            "role": "user",
            "content": (
                "Existing memories:\n"
                + ("\n".join(f"- {e}" for e in existing[:30]) if existing else "- (none)")
                + f"\n\nNew user message:\n{user_content}"
                + f"\n\nAssistant reply:\n{assistant_content}"
            ),
        }
    ]
    reply = await default_provider().complete(
        messages=messages,
        model=settings.MEMORY_EXTRACTION_MODEL or None,
        temperature=0.2,
        max_tokens=1200,
        system_prompt=_EXTRACTION_SYSTEM_PROMPT,
    )
    cleaned = reply.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("No JSON array found in extraction reply")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, list):
        raise ValueError("Extraction reply is not a JSON array")
    return data


def _coerce_category(value: Any) -> MemoryCategory:
    raw = str(value or "").strip().lower()
    if raw in MemoryCategory._value2member_map_:
        return MemoryCategory(raw)
    if raw in MemoryCategory.__members__:
        return MemoryCategory[raw.upper()]
    return MemoryCategory.FACT


async def extract_memories(
    user_id: UUID,
    organization_id: Optional[UUID],
    conversation_id: Optional[UUID],
    user_content: str,
    assistant_content: str,
) -> List[MemoryItem]:
    """Extract, deduplicate, merge and persist new memories.

    Returns the newly persisted MemoryItem objects (empty if nothing new).
    Never raises: failures are logged so extraction cannot break chat.
    """
    from app.services.embedding import embedding_service
    from app.services.vector_store import MEMORY_COLLECTION, vector_store

    if not settings.MEMORY_ENABLED or not settings.MEMORY_AUTO_EXTRACT:
        return []
    if len(user_content.strip()) < settings.MEMORY_EXTRACTION_MIN_MESSAGE_LEN:
        return []
    if len(assistant_content.strip()) < settings.MEMORY_EXTRACTION_MIN_REPLY_LEN:
        return []

    user_content = user_content[:4000]
    assistant_content = assistant_content[:4000]

    async with get_db_context() as db:
        result = await db.execute(
            select(MemoryItem).where(
                MemoryItem.user_id == user_id,
                MemoryItem.is_deleted.is_(False),
                MemoryItem.superseded_by_id.is_(None),
            )
        )
        existing_items = list(result.scalars().all())

    try:
        candidates = await _extract_candidates(
            user_content, assistant_content, [i.content for i in existing_items]
        )
    except (ProviderError, Exception) as exc:  # noqa: BLE001
        logger.warning("Memory extraction provider error: %s", exc)
        return []

    # Deduplicate within the batch itself.
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    for cand in candidates:
        content = str(cand.get("content", "")).strip()
        if not content:
            continue
        norm = _normalize(content)
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(cand)

    to_create: List[MemoryItem] = []
    to_update: List[MemoryItem] = []
    for cand in unique[: settings.MEMORY_EXTRACTION_MAX_ITEMS]:
        content = str(cand.get("content", "")).strip()
        category = _coerce_category(cand.get("category"))
        try:
            importance = max(1, min(5, int(cand.get("importance", 1) or 1)))
        except (TypeError, ValueError):
            importance = 1
        try:
            confidence = max(0.0, min(1.0, float(cand.get("confidence", 0.8) or 0.8)))
        except (TypeError, ValueError):
            confidence = 0.8

        supersedes_content = str(cand.get("supersedes") or "").strip()
        # Merge / supersede against an existing memory with identical meaning.
        existing = _find_match(existing_items, content)
        if existing is not None:
            # Newer explicit information supersedes the older statement.
            if _looks_like_update(existing.content, content):
                existing.superseded_by_id = None
                existing.content = content
                existing.category = category
                existing.importance = max(existing.importance, importance)
                existing.confidence = confidence
                to_update.append(existing)
                _supersede_older(existing_items, to_update, existing, content)
            else:
                # Near-duplicate -> refresh instead of duplicating.
                existing.use_count = existing.use_count + 1
                existing.confidence = max(existing.confidence, confidence)
                to_update.append(existing)
            continue

        # Explicit supersede reference to an older memory by content match.
        if supersedes_content:
            older = _find_by_content(existing_items, supersedes_content)
            if older is not None:
                older.superseded_by_id = None
                older.is_deleted = True
                older.deleted_at = datetime.utcnow()
                to_update.append(older)

        item = MemoryItem(
            user_id=user_id,
            organization_id=organization_id,
            content=content,
            category=category,
            importance=importance,
            confidence=confidence,
            source_conversation_id=conversation_id,
            metadata_={"auto": True},
        )
        to_create.append(item)
        existing_items.append(item)

    if not to_create and not to_update:
        return []

    try:
        async with get_db_context() as db:
            for item in to_create:
                db.add(item)
                await db.flush()
            for item in to_update:
                db.add(item)
            await db.commit()
            persisted = [i for i in to_create if i.id is not None]
            refreshed = []
            for i in persisted:
                await db.refresh(i)
                refreshed.append(i)
            for i in to_update:
                if i.id is not None:
                    await db.refresh(i)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory persistence failed: %s", exc)
        return []

    # Embed + index the newly created items (best effort, scoped to user).
    try:
        vectors = await embedding_service.embed([i.content for i in refreshed])
        await vector_store.ensure_collection(
            MEMORY_COLLECTION, embedding_service.dimension()
        )
        async with get_db_context() as db:
            for item, vec in zip(refreshed, vectors, strict=True):
                db.add(item)
                item.embedding = vec
            await db.commit()
        for item, vec in zip(refreshed, vectors, strict=True):
            await vector_store.upsert(
                MEMORY_COLLECTION,
                str(item.id),
                vec,
                {
                    "user_id": str(user_id),
                    "memory_id": str(item.id),
                    "content": item.content,
                    "category": item.category.value,
                    "importance": item.importance,
                    "confidence": item.confidence,
                    "created_at": item.created_at.isoformat()
                    if item.created_at
                    else "",
                },
            )
        logger.info("Extracted %d new memory item(s) for user %s", len(refreshed), user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Memory embedding/indexing failed: %s", exc)

    return refreshed


def _find_match(items: List[MemoryItem], content: str) -> Optional[MemoryItem]:
    """Return an existing active memory that duplicates ``content``."""
    target_norm = _normalize(content)
    for item in items:
        if item.is_deleted or item.superseded_by_id:
            continue
        if _normalize(item.content) == target_norm:
            return item
    return None


def _find_by_content(items: List[MemoryItem], content: str) -> Optional[MemoryItem]:
    target_norm = _normalize(content)
    for item in items:
        if item.is_deleted or item.superseded_by_id:
            continue
        if target_norm in _normalize(item.content) or _normalize(item.content) in target_norm:
            return item
    return None


_UPDATE_HINTS = (
    "switched", "changed", "now use", "using ", "replaced", "no longer",
    "moved to", "migrated", "updated", "decided to", "upgraded",
)


def _looks_like_update(old: str, new: str) -> bool:
    """Heuristic: the new fact overrides the old one rather than duplicating it."""
    norm_new = _normalize(new)
    for hint in _UPDATE_HINTS:
        if hint in norm_new:
            return True
    # Same category + significant shared vocabulary, but a different claim.
    shared = set(_normalize(old).split()) & set(norm_new.split())
    return len(shared) >= 2


def _supersede_older(
    items: List[MemoryItem],
    to_update: List[MemoryItem],
    winner: MemoryItem,
    new_content: str,
) -> None:
    """Mark older conflicting memories (same category, overlapping) as superseded."""
    norm_new = _normalize(new_content)
    new_words = set(norm_new.split())
    for item in items:
        if item is winner or item.is_deleted or item.superseded_by_id:
            continue
        if item.category != winner.category:
            continue
        norm_item = _normalize(item.content)
        shared = new_words & set(norm_item.split())
        if len(shared) >= 2:
            item.superseded_by_id = winner.id
            if item not in to_update:
                to_update.append(item)
