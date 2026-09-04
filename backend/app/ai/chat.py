"""
Chat orchestration: builds history, retrieves RAG context, streams provider
tokens and emits structured SSE events.
"""
from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator, Dict, List, Optional
from uuid import UUID

from sqlalchemy import select

from app.ai.providers import ProviderError, default_provider, get_provider
from app.ai.prompts import build_base_system_prompt
from app.ai.memory import memory_enabled
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.agent import Agent
from app.models.message import Message, MessageRole

logger = get_logger("ai.chat")

MAX_HISTORY_MESSAGES = 10


async def _load_history(conversation_id: UUID, exclude_ids: List[UUID]) -> List[Dict[str, str]]:
    """Load recent message history for context, oldest first."""
    async with get_db_context() as db:
        result = await db.execute(
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted.is_(False),
            )
            .order_by(Message.created_at.desc())
            .limit(MAX_HISTORY_MESSAGES)
        )
        messages = list(result.scalars().all())
        messages.reverse()

    history: List[Dict[str, str]] = []
    for m in messages:
        if m.id in exclude_ids:
            continue
        if m.role in (MessageRole.USER, MessageRole.ASSISTANT) and m.content:
            history.append({"role": m.role.value, "content": m.content})
    return history


async def _retrieve_context(
    conversation_id: UUID,
    knowledge_base_ids: Optional[List[UUID]],
    query: str,
) -> List[Dict[str, Any]]:
    """Retrieve relevant chunks from linked knowledge bases."""
    if not knowledge_base_ids:
        return []
    try:
        from app.ai.rag import retrieve

        return await retrieve(
            query=query,
            knowledge_base_ids=knowledge_base_ids,
            top_k=settings.RAG_TOP_K,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG retrieval failed: %s", exc)
        return []


async def _resolve_agent(agent_id: Optional[UUID]) -> Optional[Agent]:
    if not agent_id:
        return None
    async with get_db_context() as db:
        return (
            await db.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()


async def stream_chat_response(
    conversation,
    user_message_content: str,
    assistant_message_id: UUID,
    user,
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    system_prompt: Optional[str] = None,
    knowledge_base_ids: Optional[List[UUID]] = None,
    use_web_search: bool = True,
    agent_id: Optional[UUID] = None,
    file_ids: Optional[List[UUID]] = None,
    provider_name: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """Stream an AI chat response as a sequence of event dicts."""
    import time as _perf
    _t0 = _perf.monotonic()

    # Skip history for very short messages for speed
    if len(user_message_content.strip()) < 10 and not agent_id:
        history = []
    else:
        history = await _load_history(
            conversation.id,
            exclude_ids=[assistant_message_id],
        )
    logger.info("[PERF] History load: %.2fs", _perf.monotonic() - _t0)

    # Skip agent resolution if no agent_id
    agent = await _resolve_agent(agent_id) if agent_id else None
    if agent:
        system_prompt = system_prompt or agent.system_prompt
        model = model or agent.model
        provider_name = provider_name or agent.model_provider
        tools = tools or agent.tools

    # RAG context
    citations: List[Dict[str, Any]] = []

    # Always start from a concrete system prompt.
    base_system_prompt = system_prompt or build_base_system_prompt(user, user_message_content)

    # Run memory recall, RAG retrieval, and web search in parallel for speed
    import asyncio
    _t1 = _perf.monotonic()

    # ── Graceful degradation with timeouts ──────────────────────────────
    async def _do_memory():
        # Skip memory for short messages for speed
        if len(user_message_content.strip()) < 10:
            return ""
        if memory_enabled(user):
            try:
                from app.ai.memory import recall_context
                return await asyncio.wait_for(
                    recall_context(user.id, user_message_content),
                    timeout=1.0,
                )
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                return ""
        return ""

    async def _do_rag():
        if knowledge_base_ids:
            try:
                return await asyncio.wait_for(
                    _retrieve_context(conversation.id, knowledge_base_ids, user_message_content),
                    timeout=1.0,
                )
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                return []
        return []

    async def _do_web():
        if use_web_search:
            try:
                from app.ai.websearch import web_search_augment
                return await asyncio.wait_for(
                    web_search_augment(user_message_content),
                    timeout=2.0,
                )
            except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                pass
        return "", []

    memory_block, retrieved, (search_context, search_citations) = await asyncio.gather(
        _do_memory(), _do_rag(), _do_web()
    )
    logger.info("[PERF] Memory+RAG+Web gather: %.2fs", _perf.monotonic() - _t1)

    if memory_block:
        base_system_prompt = f"{base_system_prompt}\n\n{memory_block}"
    system_prompt = base_system_prompt

    if retrieved:
        context_block = "\n\n".join(
            f"[{i + 1}] {r['content']}" for i, r in enumerate(retrieved)
        )
        system_prompt = (
            f"{base_system_prompt}\n\n"
            f"Answer the user's question using the retrieved context below. "
            f"If the context does not contain the answer, use live web search results if available. "
            f"Keep the answer short and relevant. Cite sources as [n].\n\n"
            f"Context:\n{context_block}"
        )
        citations = [
            {
                "index": i + 1,
                "content": r["content"][:300],
                "document_id": str(r.get("document_id", "")),
                "title": r.get("title", ""),
                "score": r.get("score", 0.0),
            }
            for i, r in enumerate(retrieved)
        ]

    if search_context:
        system_prompt = f"{system_prompt}\n\nLive web search results:\n{search_context}"
        citations.extend(search_citations)

    if citations:
        yield {"type": "citations", "citations": citations}

    messages: List[Dict[str, Any]] = history + [
        {"role": "user", "content": user_message_content}
    ]

    from app.ai.providers import is_provider_healthy

    logger.info("[PERF] Total prep before stream: %.2fs", _perf.monotonic() - _t0)
    primary_provider = get_provider(provider_name) if provider_name else default_provider()
    # Skip primary if it's in cooldown — try next available instantly
    if not is_provider_healthy(primary_provider.name):
        from app.core.config import settings as _s
        for name in ("groq", "cerebras", "gemini"):
            key = f"{name.upper()}_API_KEY"
            if getattr(_s, key, None) and is_provider_healthy(name):
                primary_provider = get_provider(name)
                break

    # Build fallback list: skip unhealthy providers instantly (no timeout wait)
    def _fallback_providers():
        from app.core.config import settings as _s
        fallbacks = []
        for name in ("groq", "gemini", "cerebras"):
            if name == primary_provider.name:
                continue
            key = f"{name.upper()}_API_KEY"
            if getattr(_s, key, None) and is_provider_healthy(name):
                fallbacks.append(get_provider(name))
        return fallbacks

    # MCP tools integration (skipped for speed — re-enable when MCP server is running)
    mcp_tools = []

    async def _stream_from(provider, retry_num=0, use_default_model=False):
        """Stream from a provider with error handling."""
        # For fallback providers, use their default model (don't pass wrong model name)
        stream_model = None if use_default_model else model
        async for event in provider.stream(
            messages=messages,
            model=stream_model,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            system_prompt=system_prompt,
        ):
            if event.get("type") == "tool_call":
                if mcp_tools:
                    try:
                        tool_results = await execute_mcp_tool_calls([event])
                        for tr in tool_results:
                            messages.append({"role": "assistant", "content": None, "tool_calls": [event]})
                            messages.append({"role": "tool", "content": tr["content"]})
                        async for retry_event in provider.stream(
                            messages=messages, model=stream_model, temperature=temperature,
                            max_tokens=max_tokens, tools=tools, system_prompt=system_prompt,
                        ):
                            yield retry_event
                        return
                    except Exception as exc:
                        logger.warning("MCP tool execution failed: %s", exc)
            yield event

    try:
        async for event in _stream_from(primary_provider):
            yield event
    except ProviderError as exc:
        logger.warning("Primary provider (%s) failed: %s", primary_provider.name, exc)
        # Auto-fallback to next available provider
        for fallback in _fallback_providers():
            try:
                logger.info("Falling back to provider: %s", fallback.name)
                # Silent fallback — don't show switching message to user
                # Use fallback provider's own default model
                async for event in _stream_from(fallback, use_default_model=True):
                    yield event
                return
            except ProviderError as fb_exc:
                logger.warning("Fallback provider (%s) also failed: %s", fallback.name, fb_exc)
                continue
            except Exception as fb_exc:
                logger.warning("Fallback provider (%s) error: %s", fallback.name, fb_exc)
                continue
        # All providers failed
        yield {"type": "error", "message": f"All providers failed. Last error: {exc}"}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Provider stream error")
        yield {"type": "error", "message": str(exc)}
