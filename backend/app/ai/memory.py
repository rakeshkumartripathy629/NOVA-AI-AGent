"""
Compatibility wrapper for the long-term memory feature.

The implementation now lives in ``app.services`` (memory_service, extractor,
retriever, context, conversation_summary, conversation_search, embedding,
vector_store). This module keeps the old import surface working so existing
callers (``app.ai.chat``, ``messages.py``) do not need changes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from app.models.memory import MemoryItem
from app.services.memory_extractor import _normalize  # noqa: F401  (re-export)
from app.services.memory_service import (
    extract_and_store,
    memory_enabled,
    recall_context,
    recall_memories,
    schedule_extraction,
)

__all__ = [
    "MemoryItem",
    "extract_and_store",
    "memory_enabled",
    "recall_context",
    "recall_memories",
    "schedule_extraction",
]
