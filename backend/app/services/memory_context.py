"""
Memory context service.

Builds the "Remembered context" prompt block injected before each LLM call.
Enforces the strict memory token limit and merges long-term memories with
relevant conversation summaries.
"""
from __future__ import annotations

from typing import List

from app.core.config import settings
from app.core.logging import get_logger
from app.models.memory import MemoryItem
from app.services.embedding import count_tokens

logger = get_logger("memory.context")

_REMEMBERED_HEADER = "Remembered context (from this user's memory):"


def build_memory_context(
    memories: List[MemoryItem],
    summaries: List["str"] = None,
    token_limit: int = 0,
) -> str:
    """Render memories + summaries as a prompt block within the token budget.

    Returns '' when nothing is relevant, so no empty blocks bloat the prompt.
    """
    token_limit = token_limit or settings.MEMORY_TOKEN_LIMIT
    summaries = summaries or []
    lines: List[str] = []
    used = 0
    header_tokens = count_tokens(_REMEMBERED_HEADER)

    for item in memories:
        line = f"- {item.content}"
        tokens = count_tokens(line)
        if used + tokens > token_limit:
            break
        lines.append(line)
        used += tokens

    if summaries and used < token_limit:
        lines.append("")
        lines.append("From your previous conversations:")
        used += count_tokens(lines[-1])
        for summary in summaries:
            line = f"- {summary}"
            tokens = count_tokens(line)
            if used + tokens > token_limit:
                break
            lines.append(line)
            used += tokens

    if not lines:
        return ""
    return f"{_REMEMBERED_HEADER}\n" + "\n".join(lines)
