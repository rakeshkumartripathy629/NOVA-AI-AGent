"""
Knowledge base management endpoints.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.dependencies import generate_slug, get_current_organization
from app.core.security import get_current_active_user, require_permission
from app.db.session import get_db
from app.models.knowledge_base import (
    KnowledgeBase,
    KnowledgeBaseDocument,
    KnowledgeBaseMember,
    KnowledgeBaseRole,
)
from app.models.organization import Organization
from app.models.project import ProjectMember
from app.models.user import User

router = APIRouter()


# Request/Response Models
class KnowledgeBaseCreate(BaseModel):
    """Knowledge base create model."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    project_id: Optional[UUID] = None
    embedding_model: str = "text-embedding-3-small"
    chunk_size: int = Field(1000, ge=100, le=8000)
    chunk_overlap: int = Field(200, ge=0, le=1000)
    settings: Optional[dict] = None


class KnowledgeBaseUpdate(BaseModel):
    """Knowledge base update model."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=1000)
    embedding_model: Optional[str] = None
    chunk_size: Optional[int] = Field(None, ge=100, le=8000)
    chunk_overlap: Optional[int] = Field(None, ge=0, le=1000)
    settings: Optional[dict] = None
    is_public: Optional[bool] = None
    is_indexed: Optional[bool] = None


class KnowledgeBaseResponse(BaseModel):
    """Knowledge base response model."""
    id: UUID
    name: str
    slug: str
    description: Optional[str] = None
    project_id: Optional[UUID] = None
    organization_id: UUID
    owner_id: UUID
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    settings: dict = {}
    is_public: bool = False
    is_indexed: bool = False
    document_count: int = 0
    total_chunks: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeBaseListResponse(BaseModel):
    """Knowledge base list response model."""
    knowledge_bases: List[KnowledgeBaseResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class DocumentCreate(BaseModel):
    """Document create model."""
    title: str = Field(..., min_length=1, max_length=500)
    content: Optional[str] = None
    source_type: str = "text"
    source_url: Optional[str] = None
    metadata: Optional[dict] = None


class DocumentUpdate(BaseModel):
    """Document update model."""
    title: Optional[str] = Field(None, min_length=1, max_length=500)
    content: Optional[str] = None
    metadata: Optional[dict] = None


class DocumentResponse(BaseModel):
    """Document response model."""
    id: UUID
    knowledge_base_id: UUID
    title: str
    content: Optional[str] = None
    source_type: str
    source_url: Optional[str] = None
    source_metadata: dict = {}
    status: str
    chunk_count: int = 0
    uploaded_by: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Document list response model."""
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class SearchRequest(BaseModel):
    """Search request model."""
    query: str
    top_k: int = Field(10, ge=1, le=50)
    score_threshold: float = Field(0.0, ge=0.0, le=1.0)
    filters: Optional[dict] = None


class SearchResult(BaseModel):
    """Search result model."""
    document_id: UUID
    title: str
    content: str
    score: float
    metadata: dict


class SearchResponse(BaseModel):
    """Search response model."""
    results: List[SearchResult]
    total: int
    query: str


async def _require_member(db: AsyncSession, kb_id: UUID, user: User) -> None:
    """Ensure the user is a member or owner of the knowledge base."""
    result = await db.execute(
        select(KnowledgeBaseMember).where(
            KnowledgeBaseMember.knowledge_base_id == kb_id,
            KnowledgeBaseMember.user_id == user.id,
        )
    )
    if result.scalar_one_or_none():
        return
    result = await db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id == kb_id,
            KnowledgeBase.owner_id == user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this knowledge base")


async def _get_kb(db: AsyncSession, kb_id: UUID) -> KnowledgeBase:
    result = await db.execute(
        select(KnowledgeBase).where(KnowledgeBase.id == kb_id, KnowledgeBase.is_deleted.is_(False))
    )
    kb = result.scalar_one_or_none()
    if not kb:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge base not found")
    return kb


# Endpoints
@router.get("", response_model=KnowledgeBaseListResponse, summary="List knowledge bases")
async def list_knowledge_bases(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    project_id: Optional[UUID] = Query(None),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List knowledge bases in the organization the user can access."""
    member_result = await db.execute(
        select(KnowledgeBaseMember.knowledge_base_id).where(
            KnowledgeBaseMember.user_id == current_user.id,
        )
    )
    member_ids = list(member_result.scalars().all())

    query = select(KnowledgeBase).where(
        KnowledgeBase.organization_id == organization.id,
        KnowledgeBase.is_deleted.is_(False),
    )

    if current_user.role.value != "super_admin":
        query = query.where(
            or_(
                KnowledgeBase.owner_id == current_user.id,
                KnowledgeBase.id.in_(member_ids) if member_ids else False,
            )
        )

    if project_id:
        query = query.where(KnowledgeBase.project_id == project_id)

    if search:
        query = query.where(
            or_(
                KnowledgeBase.name.ilike(f"%{search}%"),
                KnowledgeBase.description.ilike(f"%{search}%"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(query.subquery()))

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(desc(KnowledgeBase.updated_at))
    knowledge_bases = (await db.execute(query)).scalars().all()

    return KnowledgeBaseListResponse(
        knowledge_bases=[KnowledgeBaseResponse.model_validate(kb) for kb in knowledge_bases],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("", response_model=KnowledgeBaseResponse, status_code=status.HTTP_201_CREATED, summary="Create knowledge base")
async def create_knowledge_base(
    kb_data: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Create a new knowledge base."""
    if kb_data.project_id:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == kb_data.project_id,
                ProjectMember.user_id == current_user.id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")

    base_slug = generate_slug(kb_data.name)
    slug = base_slug
    counter = 1
    while (
        await db.execute(
            select(KnowledgeBase.id).where(KnowledgeBase.slug == slug)
        )
    ).scalar_one_or_none():
        counter += 1
        slug = f"{base_slug}-{counter}"

    kb = KnowledgeBase(
        name=kb_data.name,
        slug=slug,
        description=kb_data.description,
        project_id=kb_data.project_id,
        owner_id=current_user.id,
        organization_id=organization.id,
        embedding_model=kb_data.embedding_model,
        chunk_size=kb_data.chunk_size,
        chunk_overlap=kb_data.chunk_overlap,
        settings=kb_data.settings or {},
    )
    db.add(kb)
    await db.flush()

    member = KnowledgeBaseMember(
        knowledge_base_id=kb.id,
        user_id=current_user.id,
        role=KnowledgeBaseRole.OWNER,
    )
    db.add(member)

    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseResponse.model_validate(kb)


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse, summary="Get knowledge base")
async def get_knowledge_base(
    kb_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get knowledge base by ID."""
    await _require_member(db, kb_id, current_user)
    kb = await _get_kb(db, kb_id)
    return KnowledgeBaseResponse.model_validate(kb)


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse, summary="Update knowledge base")
async def update_knowledge_base(
    kb_id: UUID,
    kb_data: KnowledgeBaseUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update knowledge base."""
    kb = await _get_kb(db, kb_id)

    member = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not member or member.role not in (KnowledgeBaseRole.OWNER, KnowledgeBaseRole.ADMIN):
        if kb.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this knowledge base")

    for field, value in kb_data.model_dump(exclude_unset=True).items():
        setattr(kb, field, value)

    await db.commit()
    await db.refresh(kb)
    return KnowledgeBaseResponse.model_validate(kb)


@router.delete("/{kb_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete knowledge base")
async def delete_knowledge_base(
    kb_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete knowledge base (owner only)."""
    kb = await _get_kb(db, kb_id)
    if kb.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the owner can delete the knowledge base")

    kb.is_deleted = True
    kb.deleted_at = datetime.utcnow()
    await db.commit()


# Document endpoints
@router.get("/{kb_id}/documents", response_model=DocumentListResponse, summary="List documents")
async def list_documents(
    kb_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List documents in a knowledge base."""
    await _require_member(db, kb_id, current_user)

    query = select(KnowledgeBaseDocument).where(
        KnowledgeBaseDocument.knowledge_base_id == kb_id,
        KnowledgeBaseDocument.is_deleted.is_(False),
    )

    if status_filter:
        query = query.where(KnowledgeBaseDocument.status == status_filter)

    if search:
        query = query.where(
            or_(
                KnowledgeBaseDocument.title.ilike(f"%{search}%"),
                KnowledgeBaseDocument.content.ilike(f"%{search}%"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(query.subquery()))

    query = query.offset((page - 1) * page_size).limit(page_size).order_by(desc(KnowledgeBaseDocument.created_at))
    documents = (await db.execute(query)).scalars().all()

    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(d) for d in documents],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("/{kb_id}/documents", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED, summary="Create document")
async def create_document(
    kb_id: UUID,
    doc_data: DocumentCreate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Add a document to a knowledge base."""
    await _require_member(db, kb_id, current_user)
    kb = await _get_kb(db, kb_id)

    document = KnowledgeBaseDocument(
        knowledge_base_id=kb_id,
        title=doc_data.title,
        content=doc_data.content,
        source_type=doc_data.source_type,
        source_url=doc_data.source_url,
        source_metadata=doc_data.metadata or {},
        uploaded_by=current_user.id,
        status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    from app.services.indexing import schedule_document_processing

    schedule_document_processing(document.id, organization.id)

    return DocumentResponse.model_validate(document)


@router.get("/{kb_id}/documents/{doc_id}", response_model=DocumentResponse, summary="Get document")
async def get_document(
    kb_id: UUID,
    doc_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get document by ID."""
    await _require_member(db, kb_id, current_user)

    result = await db.execute(
        select(KnowledgeBaseDocument).where(
            KnowledgeBaseDocument.id == doc_id,
            KnowledgeBaseDocument.knowledge_base_id == kb_id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    return DocumentResponse.model_validate(document)


@router.patch("/{kb_id}/documents/{doc_id}", response_model=DocumentResponse, summary="Update document")
async def update_document(
    kb_id: UUID,
    doc_id: UUID,
    doc_data: DocumentUpdate,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Update a document."""
    result = await db.execute(
        select(KnowledgeBaseDocument).where(
            KnowledgeBaseDocument.id == doc_id,
            KnowledgeBaseDocument.knowledge_base_id == kb_id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    member = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not member or member.role not in (KnowledgeBaseRole.OWNER, KnowledgeBaseRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to update this document")

    update_data = doc_data.model_dump(exclude_unset=True)
    if "metadata" in update_data:
        update_data["source_metadata"] = update_data.pop("metadata")

    for field, value in update_data.items():
        setattr(document, field, value)

    document.status = "pending"  # Re-process on update
    await db.commit()
    await db.refresh(document)

    from app.services.indexing import schedule_document_processing

    schedule_document_processing(document.id, organization.id)

    return DocumentResponse.model_validate(document)


@router.delete("/{kb_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete document")
async def delete_document(
    kb_id: UUID,
    doc_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document."""
    result = await db.execute(
        select(KnowledgeBaseDocument).where(
            KnowledgeBaseDocument.id == doc_id,
            KnowledgeBaseDocument.knowledge_base_id == kb_id,
        )
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    member = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not member or member.role not in (KnowledgeBaseRole.OWNER, KnowledgeBaseRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this document")

    document.is_deleted = True
    document.deleted_at = datetime.utcnow()
    document.status = "deleted"
    await db.commit()

    try:
        from app.ai.rag import delete_document_chunks

        await delete_document_chunks(document.id)
    except Exception:  # noqa: BLE001
        pass


# Search endpoint
@router.post("/{kb_id}/search", response_model=SearchResponse, summary="Search knowledge base")
async def search_knowledge_base(
    kb_id: UUID,
    search_request: SearchRequest,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Search knowledge base using vector similarity."""
    await _require_member(db, kb_id, current_user)

    try:
        from app.ai.rag import retrieve

        hits = await retrieve(
            query=search_request.query,
            knowledge_base_ids=[kb_id],
            top_k=search_request.top_k,
            score_threshold=search_request.score_threshold if search_request.score_threshold else None,
            organization_id=organization.id,
        )
    except Exception:  # noqa: BLE001
        hits = []

    results = [
        SearchResult(
            document_id=UUID(h["document_id"]),
            title=h["title"],
            content=h["content"],
            score=h["score"],
            metadata=h,
        )
        for h in hits
    ]
    return SearchResponse(results=results, total=len(results), query=search_request.query)


# Member endpoints
@router.get("/{kb_id}/members", summary="List knowledge base members")
async def list_kb_members(
    kb_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List knowledge base members."""
    await _require_member(db, kb_id, current_user)

    members = (
        await db.execute(
            select(KnowledgeBaseMember)
            .where(KnowledgeBaseMember.knowledge_base_id == kb_id)
            .options(selectinload(KnowledgeBaseMember.user))
        )
    ).scalars().all()

    return [
        {
            "id": m.id,
            "user_id": m.user_id,
            "knowledge_base_id": m.knowledge_base_id,
            "role": m.role,
            "created_at": m.created_at.isoformat(),
            "user": {
                "id": m.user.id,
                "email": m.user.email,
                "username": m.user.username,
                "full_name": m.user.full_name,
                "avatar_url": m.user.avatar_url,
            } if m.user else None,
        }
        for m in members
    ]


@router.post("/{kb_id}/members", status_code=status.HTTP_201_CREATED, summary="Add knowledge base member")
async def add_kb_member(
    kb_id: UUID,
    user_id: UUID,
    role: KnowledgeBaseRole = KnowledgeBaseRole.VIEWER,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to the knowledge base."""
    member = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not member or member.role not in (KnowledgeBaseRole.OWNER, KnowledgeBaseRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires knowledge base admin access")

    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User is already a member")

    new_member = KnowledgeBaseMember(
        knowledge_base_id=kb_id,
        user_id=user_id,
        role=role,
        invited_by=current_user.id,
        invited_at=datetime.utcnow(),
    )
    db.add(new_member)
    await db.commit()
    await db.refresh(new_member)

    return {"id": new_member.id, "user_id": new_member.user_id, "role": new_member.role}


@router.delete("/{kb_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove knowledge base member")
async def remove_kb_member(
    kb_id: UUID,
    member_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove member from knowledge base."""
    member = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.id == member_id,
                KnowledgeBaseMember.knowledge_base_id == kb_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    if member.role == KnowledgeBaseRole.OWNER:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove owner")

    current = (
        await db.execute(
            select(KnowledgeBaseMember).where(
                KnowledgeBaseMember.knowledge_base_id == kb_id,
                KnowledgeBaseMember.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not current or current.role not in (KnowledgeBaseRole.OWNER, KnowledgeBaseRole.ADMIN):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Requires knowledge base admin access")

    await db.delete(member)
    await db.commit()
