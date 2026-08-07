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
from app.core.config import settings
from app.core.logging import get_logger
from app.db.session import get_db_context
from app.models.agent import Agent
from app.models.message import Message, MessageRole

logger = get_logger("ai.chat")

MAX_HISTORY_MESSAGES = 40


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
    history = await _load_history(
        conversation.id,
        exclude_ids=[assistant_message_id],
    )

    agent = await _resolve_agent(agent_id)
    if agent:
        system_prompt = system_prompt or agent.system_prompt
        model = model or agent.model
        provider_name = provider_name or agent.model_provider
        tools = tools or agent.tools

    # RAG context
    citations: List[Dict[str, Any]] = []
    base_system_prompt = system_prompt or "You are a helpful assistant."
    if knowledge_base_ids:
        retrieved = await _retrieve_context(conversation.id, knowledge_base_ids, user_message_content)
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
        else:
            system_prompt = base_system_prompt

    # Web search augmentation
    if use_web_search:
        try:
            from app.ai.websearch import web_search_augment

            search_context, search_citations = await web_search_augment(user_message_content)
            if search_context:
                system_prompt = f"{system_prompt or base_system_prompt}\n\nLive web search results:\n{search_context}"
                citations.extend(search_citations)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Web search failed: %s", exc)

    if citations:
        yield {"type": "citations", "citations": citations}

    messages: List[Dict[str, Any]] = history + [
        {"role": "user", "content": user_message_content}
    ]

    provider = get_provider(provider_name) if provider_name else default_provider()

    # MCP tools integration
    mcp_tools = []
    if settings.MCP_ENABLED:
        try:
            from app.ai.mcp_client import get_mcp_tools, execute_mcp_tool_calls
            mcp_tools = await get_mcp_tools()
            if mcp_tools:
                from app.ai.mcp_client import mcp_tools_to_openai_functions
                mcp_functions = mcp_tools_to_openai_functions(mcp_tools)
                if tools is None:
                    tools = []
                tools = tools + mcp_functions
        except Exception as exc:
            logger.warning("MCP tools fetch failed: %s", exc)

    try:
        async for event in provider.stream(
            messages=messages,
            model=model,
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
                            messages=messages,
                            model=model,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            tools=tools,
                            system_prompt=system_prompt,
                        ):
                            yield retry_event
                        return
                    except Exception as exc:
                        logger.warning("MCP tool execution failed: %s", exc)
            yield event
    except ProviderError as exc:
        yield {"type": "error", "message": str(exc)}
    except Exception as exc:  # noqa: BLE001
        logger.exception("Provider stream error")
        yield {"type": "error", "message": str(exc)}
