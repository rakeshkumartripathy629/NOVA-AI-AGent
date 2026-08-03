"""
Global search across files, knowledge bases, conversations and messages.
"""
from __future__ import annotations

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_organization
from app.core.security import get_current_active_user
from app.db.session import get_db
from app.models.conversation import Conversation, ConversationMember
from app.models.file import File as FileModel
from app.models.knowledge_base import KnowledgeBase, KnowledgeBaseMember
from app.models.message import Message
from app.models.organization import Organization
from app.models.project import Project, ProjectMember
from app.models.user import User

router = APIRouter()


class SearchRequest(BaseModel):
    """Global search request model."""
    query: str = Field(..., min_length=1, max_length=500)
    scope: Optional[List[str]] = Field(None, description="files, knowledge_bases, conversations, messages, projects")
    limit: int = Field(10, ge=1, le=50)


class SearchHit(BaseModel):
    """A single search result."""
    type: str
    id: UUID
    title: str
    snippet: str = ""
    url: str = ""
    score: float = 1.0
    created_at: Optional[str] = None


class SearchResponse(BaseModel):
    """Global search response model."""
    query: str
    results: List[SearchHit]
    total: int


def _snippet(text: Optional[str], length: int = 180) -> str:
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    return text[:length] + ("..." if len(text) > length else "")


@router.post("", response_model=SearchResponse, summary="Search across the workspace")
async def search_all(
    search_request: SearchRequest,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Search across projects, knowledge bases, files, conversations and messages."""
    q = f"%{search_request.query.strip()}%"
    scope = search_request.scope or ["files", "knowledge_bases", "conversations", "messages", "projects"]
    limit = search_request.limit
    results: List[SearchHit] = []
    total = 0

    member_ids = [
        r
        for r in (
            await db.execute(select(ProjectMember.project_id).where(ProjectMember.user_id == current_user.id))
        )
        .scalars()
        .all()
    ]

    if "projects" in scope:
        query = select(Project).where(
            Project.organization_id == organization.id,
            Project.is_deleted.is_(False),
            or_(Project.name.ilike(q), Project.description.ilike(q)),
        )
        if current_user.role.value != "super_admin":
            query = query.where(
                or_(Project.owner_id == current_user.id, Project.id.in_(member_ids) if member_ids else False)
            )
        projects = (await db.execute(query.limit(limit))).scalars().all()
        for p in projects:
            results.append(
                SearchHit(type="project", id=p.id, title=p.name, snippet=p.description or "", score=1.0)
            )
        total += len(projects)

    if "knowledge_bases" in scope:
        kb_member_ids = [
            r
            for r in (
                await db.execute(
                    select(KnowledgeBaseMember.knowledge_base_id).where(
                        KnowledgeBaseMember.user_id == current_user.id
                    )
                )
            )
            .scalars()
            .all()
        ]
        query = select(KnowledgeBase).where(
            KnowledgeBase.organization_id == organization.id,
            KnowledgeBase.is_deleted.is_(False),
            or_(KnowledgeBase.name.ilike(q), KnowledgeBase.description.ilike(q)),
        )
        if current_user.role.value != "super_admin":
            query = query.where(
                or_(
                    KnowledgeBase.owner_id == current_user.id,
                    KnowledgeBase.id.in_(kb_member_ids) if kb_member_ids else False,
                )
            )
        kbs = (await db.execute(query.limit(limit))).scalars().all()
        for kb in kbs:
            results.append(
                SearchHit(
                    type="knowledge_base",
                    id=kb.id,
                    title=kb.name,
                    snippet=kb.description or "",
                    url=f"/knowledge-bases/{kb.id}",
                )
            )
        total += len(kbs)

    if "files" in scope:
        query = select(FileModel).where(
            FileModel.organization_id == organization.id,
            FileModel.is_deleted.is_(False),
            or_(FileModel.filename.ilike(q), FileModel.original_filename.ilike(q)),
        )
        files = (await db.execute(query.limit(limit))).scalars().all()
        for f in files:
            results.append(
                SearchHit(
                    type="file",
                    id=f.id,
                    title=f.filename,
                    snippet=f.original_filename or "",
                    url=f"/files/{f.id}",
                    created_at=f.created_at.isoformat() if f.created_at else None,
                )
            )
        total += len(files)

    if "conversations" in scope:
        conv_ids = [
            r
            for r in (
                await db.execute(
                    select(ConversationMember.conversation_id).where(
                        ConversationMember.user_id == current_user.id
                    )
                )
            )
            .scalars()
            .all()
        ]
        query = select(Conversation).where(
            Conversation.organization_id == organization.id,
            Conversation.is_deleted.is_(False),
            Conversation.title.ilike(q),
        )
        if current_user.role.value != "super_admin":
            query = query.where(
                or_(Conversation.owner_id == current_user.id, Conversation.id.in_(conv_ids) if conv_ids else False)
            )
        conversations = (await db.execute(query.limit(limit))).scalars().all()
        for c in conversations:
            results.append(
                SearchHit(
                    type="conversation",
                    id=c.id,
                    title=c.title or "Untitled conversation",
                    url=f"/conversations/{c.id}",
                    created_at=c.created_at.isoformat() if c.created_at else None,
                )
            )
        total += len(conversations)

    if "messages" in scope:
        query = (
            select(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .where(
                Conversation.organization_id == organization.id,
                Conversation.is_deleted.is_(False),
                Message.is_deleted.is_(False),
                Message.content.ilike(q),
            )
        )
        if current_user.role.value != "super_admin":
            conv_member_ids = [
                r
                for r in (
                    await db.execute(
                        select(ConversationMember.conversation_id).where(
                            ConversationMember.user_id == current_user.id
                        )
                    )
                )
                .scalars()
                .all()
            ]
            query = query.where(
                or_(
                    Conversation.owner_id == current_user.id,
                    Conversation.id.in_(conv_member_ids) if conv_member_ids else False,
                )
            )
        messages = (await db.execute(query.order_by(desc(Message.created_at)).limit(limit))).scalars().all()
        for m in messages:
            results.append(
                SearchHit(
                    type="message",
                    id=m.id,
                    title="Message",
                    snippet=_snippet(m.content),
                    url=f"/conversations/{m.conversation_id}",
                    created_at=m.created_at.isoformat() if m.created_at else None,
                )
            )
        total += len(messages)

    return SearchResponse(query=search_request.query, results=results[:limit], total=total)
