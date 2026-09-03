"""
Message management and AI streaming endpoints.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_active_user
from app.db.session import get_db, get_db_context
from app.models.conversation import Conversation, ConversationMember
from app.models.message import Message, MessageRole, MessageStatus, MessageType
from app.models.user import User


router = APIRouter()


class MessageCreate(BaseModel):
    """Message create model."""
    content: str
    role: MessageRole = MessageRole.USER
    type: MessageType = MessageType.TEXT
    parent_id: Optional[UUID] = None
    metadata: Optional[dict] = None
    attachments: Optional[List[dict]] = None


class MessageUpdate(BaseModel):
    """Message update model."""
    content: Optional[str] = None
    metadata: Optional[dict] = None


class MessageResponse(BaseModel):
    """Message response model."""
    id: UUID
    conversation_id: UUID
    user_id: Optional[UUID]
    role: str
    type: str
    status: str
    content: Optional[str]
    parent_id: Optional[UUID]
    metadata: dict
    attachments: List[dict]
    citations: List[dict]
    model: Optional[str]
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost: float
    is_edited: bool
    created_at: datetime
    updated_at: datetime
    user: Optional[dict] = None

    class Config:
        from_attributes = True


class MessageListResponse(BaseModel):
    """Message list response model."""
    messages: List[MessageResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class MessageStreamRequest(BaseModel):
    """AI streaming request model."""
    content: str = Field(..., min_length=1)
    model: Optional[str] = None
    provider_name: Optional[str] = None
    temperature: Optional[float] = Field(None, ge=0, le=2)
    max_tokens: Optional[int] = Field(None, ge=1, le=100000)
    stream: bool = True
    tools: Optional[List[dict]] = None
    system_prompt: Optional[str] = None
    knowledge_base_ids: Optional[List[UUID]] = None
    use_web_search: bool = False
    agent_id: Optional[UUID] = None
    files: Optional[List[UUID]] = None
    user_message_id: Optional[UUID] = None


def _message_dict(message: Message) -> dict:
    return {
        "id": str(message.id),
        "conversation_id": str(message.conversation_id),
        "user_id": str(message.user_id) if message.user_id else None,
        "role": message.role.value if hasattr(message.role, "value") else str(message.role),
        "type": message.type.value if hasattr(message.type, "value") else str(message.type),
        "status": message.status.value if hasattr(message.status, "value") else str(message.status),
        "content": message.content,
        "parent_id": str(message.parent_id) if message.parent_id else None,
        "metadata": message.metadata_,
        "attachments": message.attachments,
        "citations": message.citations,
        "model": message.model,
        "prompt_tokens": message.prompt_tokens,
        "completion_tokens": message.completion_tokens,
        "total_tokens": message.total_tokens,
        "cost": message.cost,
        "is_edited": message.is_edited,
        "created_at": message.created_at.isoformat() if message.created_at else None,
        "updated_at": message.updated_at.isoformat() if message.updated_at else None,
    }


async def _check_membership(db: AsyncSession, conversation_id: UUID, user_id: UUID) -> None:
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == user_id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this conversation",
        )


@router.get("/conversations/{conversation_id}/messages", response_model=MessageListResponse, summary="List messages")
async def list_messages(
    conversation_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    before_id: Optional[UUID] = Query(None),
    after_id: Optional[UUID] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List messages in a conversation (newest last)."""
    await _check_membership(db, conversation_id, current_user.id)

    query = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.is_deleted.is_(False),
    ).options(selectinload(Message.user))

    if before_id:
        before_msg = await db.execute(select(Message.created_at).where(Message.id == before_id))
        before_time = before_msg.scalar_one_or_none()
        if before_time:
            query = query.where(Message.created_at < before_time)

    if after_id:
        after_msg = await db.execute(select(Message.created_at).where(Message.id == after_id))
        after_time = after_msg.scalar_one_or_none()
        if after_time:
            query = query.where(Message.created_at > after_time)

    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)

    query = query.order_by(Message.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    result = await db.execute(query)
    messages = list(result.scalars().all())
    messages.reverse()  # return oldest first

    return MessageListResponse(
        messages=[MessageResponse(**m) for m in (_message_dict(x) for x in messages)],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED, summary="Create message")
async def create_message(
    conversation_id: UUID,
    message_data: MessageCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a message (without AI generation)."""
    await _check_membership(db, conversation_id, current_user.id)

    if message_data.parent_id:
        result = await db.execute(
            select(Message).where(Message.id == message_data.parent_id, Message.conversation_id == conversation_id)
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Parent message not found")

    message = Message(
        conversation_id=conversation_id,
        user_id=current_user.id if message_data.role == MessageRole.USER else None,
        role=message_data.role,
        type=message_data.type,
        content=message_data.content,
        parent_id=message_data.parent_id,
        metadata_=message_data.metadata or {},
        attachments=message_data.attachments or [],
    )
    db.add(message)

    conversation_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = conversation_result.scalar_one_or_none()
    if conversation:
        conversation.last_message_at = datetime.utcnow()
        conversation.message_count += 1

    await db.commit()
    await db.refresh(message)
    return MessageResponse(**_message_dict(message))


@router.get("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageResponse, summary="Get message")
async def get_message(
    conversation_id: UUID,
    message_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single message by ID."""
    await _check_membership(db, conversation_id, current_user.id)

    result = await db.execute(
        select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conversation_id,
            Message.is_deleted.is_(False),
        ).options(selectinload(Message.user))
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    return MessageResponse(**_message_dict(message))


@router.patch("/conversations/{conversation_id}/messages/{message_id}", response_model=MessageResponse, summary="Update message")
async def update_message(
    conversation_id: UUID,
    message_id: UUID,
    message_data: MessageUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a user message (content or metadata)."""
    await _check_membership(db, conversation_id, current_user.id)

    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if message.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only edit your own messages")
    if message.role != MessageRole.USER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can only edit user messages")

    update_data = message_data.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["metadata_"] = update_data.pop("metadata")
    for field, value in update_data.items():
        setattr(message, field, value)
    message.is_edited = True

    await db.commit()
    await db.refresh(message)
    return MessageResponse(**_message_dict(message))


@router.delete("/conversations/{conversation_id}/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete message")
async def delete_message(
    conversation_id: UUID,
    message_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a message."""
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this conversation")

    result = await db.execute(
        select(Message).where(Message.id == message_id, Message.conversation_id == conversation_id)
    )
    message = result.scalar_one_or_none()
    if not message:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if message.user_id != current_user.id and member.role.value not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only delete your own messages")

    message.is_deleted = True
    message.deleted_at = datetime.utcnow()
    message.content = "[Deleted]"

    conversation_result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conversation = conversation_result.scalar_one_or_none()
    if conversation:
        conversation.message_count = max(0, conversation.message_count - 1)

    await db.commit()


@router.post("/conversations/{conversation_id}/messages/stream", summary="Stream AI response")
async def stream_message(
    conversation_id: UUID,
    request: MessageStreamRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and stream an AI response for a conversation (SSE)."""
    # Combined membership + conversation check in one query for speed
    conversation_result = await db.execute(
        select(Conversation)
        .join(ConversationMember, ConversationMember.conversation_id == Conversation.id)
        .where(
            Conversation.id == conversation_id,
            ConversationMember.user_id == current_user.id,
        )
    )
    conversation = conversation_result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found or not a member")

    # AI rate limiting per user (in-memory, no DB)
    from app.core.config import settings as _s
    from app.core.security import rate_limiter as _rl
    chat_key = f"chat:{current_user.id}"
    if not _rl.is_allowed(chat_key, _s.RATE_LIMIT_CHAT_REQUESTS, _s.RATE_LIMIT_CHAT_WINDOW):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"AI rate limit exceeded. Max {_s.RATE_LIMIT_CHAT_REQUESTS} requests per minute.",
        )

    user_message = None
    if request.user_message_id:
        result = await db.execute(
            select(Message).where(
                Message.id == request.user_message_id,
                Message.conversation_id == conversation_id,
                Message.role == MessageRole.USER,
                Message.user_id == current_user.id,
            )
        )
        user_message = result.scalar_one_or_none()
        if not user_message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User message not found")
        user_message.content = request.content
        user_message.is_edited = True
        await db.flush()
    else:
        user_message = Message(
            conversation_id=conversation_id,
            user_id=current_user.id,
            role=MessageRole.USER,
            type=MessageType.TEXT,
            content=request.content,
            status=MessageStatus.COMPLETED,
            attachments=[
                {"file_id": str(fid), "type": "file"}
                for fid in (request.files or [])
            ],
            metadata_={"agent_id": str(request.agent_id)} if request.agent_id else {},
        )
        db.add(user_message)
        await db.flush()

    assistant_message = Message(
        conversation_id=conversation_id,
        user_id=None,
        role=MessageRole.ASSISTANT,
        type=MessageType.TEXT,
        content="",
        status=MessageStatus.STREAMING,
        model=request.model or conversation.model,
    )
    db.add(assistant_message)
    conversation.last_message_at = datetime.utcnow()
    if not request.user_message_id:
        conversation.message_count += 1
    await db.flush()
    await db.commit()

    from app.ai.chat import stream_chat_response

    async def generate():
        accumulated = []
        citations = []
        try:
            async for event in stream_chat_response(
                conversation=conversation,
                user_message_content=request.content,
                assistant_message_id=assistant_message.id,
                user=current_user,
                model=request.model,
                provider_name=request.provider_name,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                tools=request.tools,
                system_prompt=request.system_prompt,
                knowledge_base_ids=request.knowledge_base_ids,
                use_web_search=request.use_web_search,
                agent_id=request.agent_id,
                file_ids=request.files,
            ):
                if event.get("type") == "content":
                    accumulated.append(event.get("content", ""))
                if event.get("type") == "citations":
                    citations = event.get("citations", [])
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.exception("Streaming failed for conversation %s", conversation_id)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)})}\n\n"

        # Finalize the assistant message
        async with get_db_context() as final_db:
            result = await final_db.execute(
                select(Message).where(Message.id == assistant_message.id)
            )
            msg = result.scalar_one_or_none()
            if msg:
                msg.content = "".join(accumulated)
                msg.status = MessageStatus.COMPLETED
                msg.citations = citations
            conv_result = await final_db.execute(
                select(Conversation).where(Conversation.id == conversation_id)
            )
            conv = conv_result.scalar_one_or_none()
            if conv and not conv.title:
                title = " ".join(request.content.split())[:60] or "New conversation"
                conv.title = title
            elif conv and conv.title in ("New conversation", "Untitled"):
                title = " ".join(request.content.split())[:60] or conv.title
                conv.title = title
            await final_db.commit()

        # Long-term memory: extract durable facts in the background
        try:
            from app.ai.memory import memory_enabled, schedule_extraction

            if memory_enabled(current_user):
                schedule_extraction(
                    user_id=current_user.id,
                    organization_id=getattr(conversation, "organization_id", None),
                    conversation_id=conversation_id,
                    user_content=request.content,
                    assistant_content="".join(accumulated),
                )
        except Exception as exc:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).debug("Memory scheduling failed: %s", exc)

        yield f"data: {json.dumps({'type': 'done', 'message_id': str(assistant_message.id)})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


class FollowupSuggestResponse(BaseModel):
    """Follow-up question suggestions."""
    suggestions: List[str]


@router.post("/conversations/{conversation_id}/followups", response_model=FollowupSuggestResponse, summary="Suggest follow-up questions")
async def suggest_followups(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate 3 short follow-up questions from the recent conversation."""
    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conv = conv_result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    rows = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .limit(6)
    )
    history = list(reversed(rows.scalars().all()))
    msgs = [{"role": m.role, "content": m.content} for m in history if m.content]
    if not msgs:
        return FollowupSuggestResponse(suggestions=[])

    from app.ai.providers import default_provider

    collected: List[str] = []
    try:
        async for event in default_provider().stream(
            messages=msgs,
            temperature=0.6,
            max_tokens=150,
            system_prompt=(
                "Based on the conversation above, suggest exactly 3 short follow-up questions "
                "the user might ask next. Respond with ONLY a JSON array of strings, e.g. "
                '["question one", "question two", "question three"]. No other text.'
            ),
        ):
            if event.get("type") == "content":
                collected.append(event.get("content", ""))
    except Exception:  # noqa: BLE001
        return FollowupSuggestResponse(suggestions=[])

    text = "".join(collected).strip()
    suggestions: List[str] = []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            suggestions = [str(x)[:120] for x in parsed[:3]]
    except Exception:  # noqa: BLE001
        import re

        found = re.findall(r'"([^"]+)"', text)
        suggestions = [x[:120] for x in found[:3]]
    return FollowupSuggestResponse(suggestions=suggestions)
