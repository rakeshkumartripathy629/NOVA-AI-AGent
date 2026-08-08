"""
Conversation management endpoints.
"""
import json
import secrets
from datetime import datetime
from typing import Optional, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.security import get_current_active_user, require_permission
from app.core.dependencies import get_current_organization
from app.db.session import get_db
from app.models.user import User
from app.models.conversation import Conversation, ConversationMember, ConversationRole
from app.models.message import Message
from app.models.organization import Organization
from app.models.project import ProjectMember


router = APIRouter()


# Request/Response Models
class ConversationCreate(BaseModel):
    """Conversation create model."""
    title: Optional[str] = Field(None, max_length=200)
    project_id: Optional[UUID] = None
    is_private: bool = False
    settings: Optional[dict] = None


class ConversationUpdate(BaseModel):
    """Conversation update model."""
    title: Optional[str] = Field(None, max_length=200)
    is_private: Optional[bool] = None
    is_archived: Optional[bool] = None
    is_pinned: Optional[bool] = None
    folder: Optional[str] = None
    settings: Optional[dict] = None


class ConversationResponse(BaseModel):
    """Conversation response model."""
    id: UUID
    title: Optional[str]
    project_id: Optional[UUID]
    owner_id: UUID
    is_private: bool
    is_archived: bool
    is_pinned: bool = False
    summary: Optional[str] = None
    settings: dict
    message_count: int
    last_message_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ConversationListResponse(BaseModel):
    """Conversation list response model."""
    conversations: List[ConversationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ConversationMemberAdd(BaseModel):
    """Conversation member add model."""
    user_id: UUID
    role: ConversationRole = ConversationRole.MEMBER


class ConversationMemberUpdate(BaseModel):
    """Conversation member update model."""
    role: ConversationRole


class ConversationMemberResponse(BaseModel):
    """Conversation member response model."""
    id: UUID
    conversation_id: UUID
    user_id: UUID
    role: str
    created_at: datetime
    user: Optional[dict] = None
    
    class Config:
        from_attributes = True


class ConversationMemberListResponse(BaseModel):
    """Conversation member list response model."""
    members: List[ConversationMemberResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


# Endpoints
@router.get("", response_model=ConversationListResponse, summary="List conversations")
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    project_id: Optional[UUID] = Query(None),
    is_archived: Optional[bool] = Query(False),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversations user has access to."""
    # Get conversation IDs user has access to
    member_result = await db.execute(
        select(ConversationMember.conversation_id).where(
            ConversationMember.user_id == current_user.id,
        )
    )
    conversation_ids = member_result.scalars().all()
    
    if not conversation_ids:
        return ConversationListResponse(
            conversations=[],
            total=0,
            page=page,
            page_size=page_size,
            total_pages=0,
        )
    
    query = select(Conversation).where(
        Conversation.id.in_(conversation_ids),
        Conversation.is_deleted.is_(False),
    )
    
    if project_id:
        query = query.where(Conversation.project_id == project_id)
    
    if is_archived is not None:
        query = query.where(Conversation.is_archived == is_archived)
    
    if search:
        query = query.where(
            or_(
                Conversation.title.ilike(f"%{search}%"),
            )
        )
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(desc(Conversation.last_message_at).nullslast())
    
    result = await db.execute(query)
    conversations = result.scalars().all()
    
    return ConversationListResponse(
        conversations=[ConversationResponse.model_validate(c) for c in conversations],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED, summary="Create conversation")
async def create_conversation(
    conversation_data: ConversationCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Create a new conversation."""
    # Verify project access if provided
    if conversation_data.project_id:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == conversation_data.project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this project",
            )

    # Create conversation
    conversation = Conversation(
        title=conversation_data.title,
        project_id=conversation_data.project_id,
        owner_id=current_user.id,
        organization_id=organization.id,
        is_private=conversation_data.is_private,
        settings=conversation_data.settings or {},
    )
    db.add(conversation)
    await db.flush()
    
    # Add creator as owner
    member = ConversationMember(
        conversation_id=conversation.id,
        user_id=current_user.id,
        role=ConversationRole.OWNER,
    )
    db.add(member)
    
    await db.commit()
    await db.refresh(conversation)
    
    return ConversationResponse.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationResponse, summary="Get conversation")
async def get_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get conversation by ID."""
    # Check membership
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this conversation",
        )
    
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.is_deleted.is_(False),
        )
    )
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    return ConversationResponse.model_validate(conversation)


@router.patch("/{conversation_id}", response_model=ConversationResponse, summary="Update conversation")
async def update_conversation(
    conversation_id: UUID,
    conversation_data: ConversationUpdate,
    current_user: User = Depends(require_permission("conversation:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update conversation."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    # Check permission
    member_result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id,
        )
    )
    member = member_result.scalar_one_or_none()
    
    if not member or member.role not in [ConversationRole.OWNER, ConversationRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this conversation",
        )
    
    update_data = conversation_data.model_dump(exclude_unset=True)

    if "folder" in update_data:
        folder = update_data.pop("folder")
        settings = dict(conversation.settings or {})
        if folder:
            settings["folder"] = folder
        elif "folder" in settings:
            del settings["folder"]
        conversation.settings = settings

    for field, value in update_data.items():
        setattr(conversation, field, value)
    
    await db.commit()
    await db.refresh(conversation)
    
    return ConversationResponse.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete conversation")
async def delete_conversation(
    conversation_id: UUID,
    current_user: User = Depends(require_permission("conversation:delete")),
    db: AsyncSession = Depends(get_db),
):
    """Delete conversation (owner only)."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    
    # Only owner can delete
    if conversation.owner_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the owner can delete the conversation",
        )
    
    # Soft delete
    conversation.is_deleted = True
    conversation.deleted_at = datetime.utcnow()
    await db.commit()


# Member endpoints
@router.get("/{conversation_id}/members", response_model=ConversationMemberListResponse, summary="List conversation members")
async def list_conversation_members(
    conversation_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    role: Optional[ConversationRole] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversation members."""
    # Check membership
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this conversation",
        )
    
    query = select(ConversationMember).where(
        ConversationMember.conversation_id == conversation_id
    ).options(selectinload(ConversationMember.user))
    
    if role:
        query = query.where(ConversationMember.role == role)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query)
    
    # Apply pagination
    query = query.offset((page - 1) * page_size).limit(page_size)
    query = query.order_by(ConversationMember.created_at.desc())
    
    result = await db.execute(query)
    members = result.scalars().all()
    
    return ConversationMemberListResponse(
        members=[
            ConversationMemberResponse(
                id=m.id,
                conversation_id=m.conversation_id,
                user_id=m.user_id,
                role=m.role,
                created_at=m.created_at.isoformat(),
                user={
                    "id": m.user.id,
                    "email": m.user.email,
                    "username": m.user.username,
                    "full_name": m.user.full_name,
                    "avatar_url": m.user.avatar_url,
                } if m.user else None,
            )
            for m in members
        ],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.post("/{conversation_id}/members", response_model=ConversationMemberResponse, status_code=status.HTTP_201_CREATED, summary="Add conversation member")
async def add_conversation_member(
    conversation_id: UUID,
    member_data: ConversationMemberAdd,
    current_user: User = Depends(require_permission("conversation:member:add")),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to the conversation."""
    # Check if user exists
    result = await db.execute(
        select(User).where(User.id == member_data.user_id)
    )
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )
    
    # Check if already a member
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == member_data.user_id,
        )
    )
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already a member",
        )
    
    # Verify user has access to project if conversation belongs to project
    conversation_result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = conversation_result.scalar_one_or_none()
    
    if conversation.project_id:
        project_result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == conversation.project_id,
                ProjectMember.user_id == member_data.user_id,
            )
        )
        if not project_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User must be a member of the conversation's project",
            )
    
    # Create member
    member = ConversationMember(
        conversation_id=conversation_id,
        user_id=member_data.user_id,
        role=member_data.role,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    
    return ConversationMemberResponse.model_validate(member)


@router.patch("/{conversation_id}/members/{member_id}", response_model=ConversationMemberResponse, summary="Update conversation member")
async def update_conversation_member(
    conversation_id: UUID,
    member_id: UUID,
    member_data: ConversationMemberUpdate,
    current_user: User = Depends(require_permission("conversation:member:update")),
    db: AsyncSession = Depends(get_db),
):
    """Update conversation member role."""
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.id == member_id,
            ConversationMember.conversation_id == conversation_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    
    # Cannot change owner role
    if member.role == ConversationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change owner role",
        )
    
    # Only owner can change admin roles
    if member_data.role == ConversationRole.ADMIN or member.role == ConversationRole.ADMIN:
        current_member_result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == current_user.id,
            )
        )
        current_member = current_member_result.scalar_one_or_none()
        if not current_member or current_member.role != ConversationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only owner can manage admin roles",
            )
    
    member.role = member_data.role
    await db.commit()
    await db.refresh(member)
    
    return ConversationMemberResponse.model_validate(member)


@router.delete("/{conversation_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove conversation member")
async def remove_conversation_member(
    conversation_id: UUID,
    member_id: UUID,
    current_user: User = Depends(require_permission("conversation:member:remove")),
    db: AsyncSession = Depends(get_db),
):
    """Remove member from conversation."""
    result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.id == member_id,
            ConversationMember.conversation_id == conversation_id,
        )
    )
    member = result.scalar_one_or_none()
    
    if not member:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )
    
    # Cannot remove owner
    if member.role == ConversationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove owner",
        )
    
    # Users can remove themselves, admins can remove others
    current_member_result = await db.execute(
        select(ConversationMember).where(
            ConversationMember.conversation_id == conversation_id,
            ConversationMember.user_id == current_user.id,
        )
    )
    current_member = current_member_result.scalar_one_or_none()
    
    if member.user_id != current_user.id and current_member.role not in [ConversationRole.OWNER, ConversationRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to remove this member",
        )
    
    await db.delete(member)
    await db.commit()


# Import datetime at the end
from datetime import datetime


class SummarizeResponse(BaseModel):
    """Conversation summary result."""
    summary: str


@router.post("/{conversation_id}/summarize", response_model=SummarizeResponse, summary="Summarize conversation")
async def summarize_conversation(
    conversation_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and store a summary of the conversation using the LLM."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    rows = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at)
    )
    messages = rows.scalars().all()
    if not messages:
        return SummarizeResponse(summary="No messages to summarize yet.")

    transcript = "\n".join(
        f"{m.role.upper()}: {m.content[:2000]}" for m in messages if m.content
    )[:30000]

    from app.ai.providers import default_provider

    collected: List[str] = []
    try:
        async for event in default_provider().stream(
            messages=[{"role": "user", "content": transcript}],
            temperature=0.3,
            max_tokens=400,
            system_prompt=(
                "Summarize the following conversation into clear bullet points (about 150 words max). "
                "Cover the main topic, key points, decisions, and action items."
            ),
        ):
            if event.get("type") == "content":
                collected.append(event.get("content", ""))
    except Exception:  # noqa: BLE001
        return SummarizeResponse(summary="Summary generation failed.")

    summary = "".join(collected).strip() or "Summary unavailable."
    conversation.summary = summary
    await db.commit()
    return SummarizeResponse(summary=summary)


class ShareResponse(BaseModel):
    """Share link response."""
    url: str
    token: str


@router.post("/{conversation_id}/share", response_model=ShareResponse, summary="Create a public share link")
async def share_conversation(
    conversation_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a read-only public share link for the conversation."""
    result = await db.execute(
        select(Conversation).where(Conversation.id == conversation_id)
    )
    conversation = result.scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    settings = dict(conversation.settings or {})
    token = secrets.token_urlsafe(24)
    settings["share_token"] = token
    conversation.settings = settings
    await db.commit()
    base = str(request.base_url).rstrip("/")
    return ShareResponse(url=f"{base}/share/{token}", token=token)


class PublicShareResponse(BaseModel):
    """Public shared conversation payload."""
    title: str
    messages: List[dict]


@router.get("/public/{token}", response_model=PublicShareResponse, summary="Get a shared conversation (no auth)")
async def get_shared_conversation(token: str, db: AsyncSession = Depends(get_db)):
    """Public read-only view of a shared conversation (no authentication required)."""
    result = await db.execute(select(Conversation))
    conversations = result.scalars().all()
    conversation = next(
        (c for c in conversations if (c.settings or {}).get("share_token") == token),
        None,
    )
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shared conversation not found")

    rows = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at)
    )
    messages = rows.scalars().all()
    return PublicShareResponse(
        title=conversation.title or "Shared conversation",
        messages=[{"role": m.role, "content": m.content} for m in messages if m.content],
    )