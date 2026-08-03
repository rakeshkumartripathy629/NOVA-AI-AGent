"""
File management endpoints.

Storage is delegated to the MinIO/S3-backed ``storage_service``; only
metadata lives in PostgreSQL.
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.dependencies import get_current_organization
from app.core.security import get_current_active_user
from app.core.storage import storage_service
from app.db.session import get_db
from app.models.conversation import ConversationMember
from app.models.file import File as FileModel
from app.models.file import FileStatus, FileType
from app.models.organization import Organization, OrganizationMember, OrganizationRole
from app.models.project import ProjectMember
from app.models.user import User

router = APIRouter()


# Request/Response Models
class FileResponse(BaseModel):
    """File response model (aligned with the File model)."""
    id: UUID
    filename: str
    original_filename: str
    file_type: str
    mime_type: str
    file_size: int
    status: str
    storage_path: str
    storage_bucket: str
    conversation_id: Optional[UUID] = None
    message_id: Optional[UUID] = None
    knowledge_base_id: Optional[UUID] = None
    organization_id: UUID
    uploaded_by: UUID
    metadata: dict = {}
    tags: List[str] = []
    created_at: datetime
    updated_at: datetime
    uploaded_by_user: Optional[dict] = None


class FileListResponse(BaseModel):
    """File list response model."""
    files: List[FileResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class FileUpdate(BaseModel):
    """File update model."""
    filename: Optional[str] = Field(None, max_length=255)
    tags: Optional[List[str]] = None
    metadata: Optional[dict] = None


class PresignedUrlRequest(BaseModel):
    """Presigned URL request model."""
    filename: str = Field(..., min_length=1, max_length=255)
    file_type: FileType
    mime_type: str
    size: int = Field(..., ge=1)
    conversation_id: Optional[UUID] = None


class PresignedUrlResponse(BaseModel):
    """Presigned URL response model."""
    upload_url: str
    file_id: UUID
    expires_in: int


def _to_file_response(f: FileModel) -> FileResponse:
    """Build a serializable response from a File model instance."""
    user = f.uploaded_by_user
    return FileResponse(
        id=f.id,
        filename=f.filename,
        original_filename=f.original_filename,
        file_type=f.file_type.value if hasattr(f.file_type, "value") else f.file_type,
        mime_type=f.mime_type,
        file_size=f.file_size,
        status=f.status.value if hasattr(f.status, "value") else f.status,
        storage_path=f.storage_path,
        storage_bucket=f.storage_bucket,
        conversation_id=f.conversation_id,
        message_id=f.message_id,
        knowledge_base_id=f.knowledge_base_id,
        organization_id=f.organization_id,
        uploaded_by=f.uploaded_by,
        metadata=f.metadata_ or {},
        tags=f.tags or [],
        created_at=f.created_at.isoformat(),
        updated_at=f.updated_at.isoformat(),
        uploaded_by_user={
            "id": user.id,
            "email": user.email,
            "username": user.username,
            "full_name": user.full_name,
            "avatar_url": user.avatar_url,
        } if user else None,
    )


def _classify_mime_type(mime_type: str) -> FileType:
    mapping = {
        "application/pdf": FileType.PDF,
        "application/msword": FileType.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": FileType.DOCUMENT,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": FileType.SPREADSHEET,
        "application/vnd.openxmlformats-officedocument.presentationml.presentation": FileType.PRESENTATION,
        "application/zip": FileType.ARCHIVE,
        "application/x-tar": FileType.ARCHIVE,
        "application/gzip": FileType.ARCHIVE,
        "audio/": FileType.AUDIO,
        "video/": FileType.VIDEO,
        "image/": FileType.IMAGE,
        "text/": FileType.TEXT,
    }
    for prefix, ftype in mapping.items():
        if mime_type.startswith(prefix):
            return ftype
    return FileType.OTHER


async def _ensure_project_or_conversation_access(
    db: AsyncSession,
    user_id: UUID,
    project_id: Optional[UUID] = None,
    conversation_id: Optional[UUID] = None,
) -> None:
    """Raise 403 unless the user can access the scoping project/conversation."""
    if project_id:
        result = await db.execute(
            select(ProjectMember).where(
                ProjectMember.project_id == project_id,
                ProjectMember.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this project")
    if conversation_id:
        result = await db.execute(
            select(ConversationMember).where(
                ConversationMember.conversation_id == conversation_id,
                ConversationMember.user_id == user_id,
            )
        )
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this conversation")


async def _get_accessible_file(db: AsyncSession, file_id: UUID, user: User) -> FileModel:
    result = await db.execute(
        select(FileModel)
        .where(FileModel.id == file_id, FileModel.is_deleted.is_(False))
        .options(selectinload(FileModel.uploaded_by_user))
    )
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    if file_record.uploaded_by == user.id:
        return file_record

    if file_record.organization_id:
        membership = await db.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == file_record.organization_id,
                OrganizationMember.user_id == user.id,
                OrganizationMember.status == "active",
            )
        )
        if membership.scalar_one_or_none():
            return file_record

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to access this file")


# Endpoints
@router.get("", response_model=FileListResponse, summary="List files")
async def list_files(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    conversation_id: Optional[UUID] = Query(None),
    knowledge_base_id: Optional[UUID] = Query(None),
    file_type: Optional[FileType] = Query(None),
    status_filter: Optional[FileStatus] = Query(None, alias="status"),
    search: Optional[str] = Query(None),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """List files user has access to."""
    query = select(FileModel).where(
        FileModel.is_deleted.is_(False),
        FileModel.organization_id == organization.id,
    )

    if conversation_id:
        await _ensure_project_or_conversation_access(db, current_user.id, conversation_id=conversation_id)
        query = query.where(FileModel.conversation_id == conversation_id)
    elif current_user.role.value != "super_admin":
        # Restrict to files the user uploaded or in accessible conversations
        memberships = (
            await db.execute(
                select(ConversationMember.conversation_id).where(
                    ConversationMember.user_id == current_user.id,
                )
            )
        ).scalars().all()
        query = query.where(
            or_(
                FileModel.uploaded_by == current_user.id,
                FileModel.conversation_id.in_(memberships) if memberships else False,
            )
        )

    if knowledge_base_id:
        query = query.where(FileModel.knowledge_base_id == knowledge_base_id)

    if file_type:
        query = query.where(FileModel.file_type == file_type)

    if status_filter:
        query = query.where(FileModel.status == status_filter)

    if search:
        query = query.where(
            or_(
                FileModel.filename.ilike(f"%{search}%"),
                FileModel.original_filename.ilike(f"%{search}%"),
            )
        )

    total = await db.scalar(select(func.count()).select_from(query.subquery()))

    query = (
        query.offset((page - 1) * page_size)
        .limit(page_size)
        .order_by(desc(FileModel.created_at))
        .options(selectinload(FileModel.uploaded_by_user))
    )
    files = (await db.execute(query)).scalars().all()

    return FileListResponse(
        files=[_to_file_response(f) for f in files],
        total=total or 0,
        page=page,
        page_size=page_size,
        total_pages=((total or 0) + page_size - 1) // page_size,
    )


@router.post("/presigned-url", response_model=PresignedUrlResponse, summary="Get presigned upload URL")
async def get_presigned_url(
    request: PresignedUrlRequest,
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Get presigned URL for direct upload to storage."""
    await _ensure_project_or_conversation_access(
        db, current_user.id, conversation_id=request.conversation_id
    )

    file_record = FileModel(
        filename="",
        original_filename=request.filename,
        file_type=request.file_type,
        mime_type=request.mime_type,
        file_size=request.size,
        status=FileStatus.UPLOADING,
        conversation_id=request.conversation_id,
        uploaded_by=current_user.id,
        organization_id=organization.id,
        storage_path="",
        storage_bucket=settings.STORAGE_BUCKET,
    )
    db.add(file_record)
    await db.flush()

    storage_path = storage_service.generate_path(
        file_record.id,
        request.filename,
        conversation_id=request.conversation_id,
    )
    file_record.storage_path = storage_path
    file_record.filename = storage_path.split("/")[-1]

    await db.commit()

    upload_url = await storage_service.generate_presigned_upload_url(
        storage_path,
        request.mime_type,
        expires_in=3600,
    )

    return PresignedUrlResponse(upload_url=upload_url, file_id=file_record.id, expires_in=3600)


@router.post("/upload", response_model=FileResponse, summary="Upload file directly")
async def upload_file(
    file: UploadFile = File(...),
    conversation_id: Optional[UUID] = Form(None),
    current_user: User = Depends(get_current_active_user),
    organization: Organization = Depends(get_current_organization),
    db: AsyncSession = Depends(get_db),
):
    """Upload file directly (for smaller files)."""
    await _ensure_project_or_conversation_access(db, current_user.id, conversation_id=conversation_id)

    content = await file.read()
    if len(content) > settings.MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds maximum size of {settings.MAX_FILE_SIZE} bytes",
        )

    mime_type = file.content_type or "application/octet-stream"
    file_record = FileModel(
        filename="",
        original_filename=file.filename or "unknown",
        file_type=_classify_mime_type(mime_type),
        mime_type=mime_type,
        file_size=len(content),
        status=FileStatus.PROCESSING,
        conversation_id=conversation_id,
        uploaded_by=current_user.id,
        organization_id=organization.id,
        storage_path="",
        storage_bucket=settings.STORAGE_BUCKET,
    )
    db.add(file_record)
    await db.flush()

    storage_path = storage_service.generate_path(
        file_record.id,
        file.filename or "unknown",
        conversation_id=conversation_id,
    )
    file_record.storage_path = storage_path
    file_record.filename = storage_path.split("/")[-1]

    try:
        await storage_service.upload_file(storage_path, content, mime_type)
    except Exception as exc:  # noqa: BLE001
        file_record.status = FileStatus.FAILED
        file_record.processing_error = str(exc)
        await db.commit()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Upload failed") from exc

    file_record.status = FileStatus.READY
    await db.commit()
    await db.refresh(file_record)

    return _to_file_response(file_record)


@router.post("/{file_id}/complete", response_model=FileResponse, summary="Complete upload")
async def complete_upload(
    file_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark file upload as complete (for presigned URL uploads)."""
    file_record = await _get_accessible_file(db, file_id, current_user)

    if file_record.status not in (FileStatus.UPLOADING, FileStatus.PROCESSING):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File is not in uploading state")

    if not await storage_service.file_exists(file_record.storage_path):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File not found in storage")

    metadata = await storage_service.get_file_metadata(file_record.storage_path)
    file_record.file_size = metadata.get("size", file_record.file_size)
    file_record.status = FileStatus.READY

    await db.commit()
    await db.refresh(file_record)
    return _to_file_response(file_record)


@router.get("/{file_id}", response_model=FileResponse, summary="Get file")
async def get_file(
    file_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get file by ID."""
    file_record = await _get_accessible_file(db, file_id, current_user)
    return _to_file_response(file_record)


@router.get("/{file_id}/download", summary="Download file")
async def download_file(
    file_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Get presigned download URL for file."""
    file_record = await _get_accessible_file(db, file_id, current_user)

    download_url = await storage_service.generate_presigned_download_url(
        file_record.storage_path,
        file_record.original_filename,
        expires_in=3600,
    )
    return {"download_url": download_url, "expires_in": 3600}


@router.patch("/{file_id}", response_model=FileResponse, summary="Update file metadata")
async def update_file(
    file_id: UUID,
    file_data: FileUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update file metadata."""
    file_record = await _get_accessible_file(db, file_id, current_user)

    if file_record.uploaded_by != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the uploader can update this file")

    if file_data.filename is not None:
        file_record.filename = file_data.filename
    if file_data.tags is not None:
        file_record.tags = file_data.tags
    if file_data.metadata is not None:
        file_record.metadata_ = file_data.metadata

    await db.commit()
    await db.refresh(file_record)
    return _to_file_response(file_record)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete file")
async def delete_file(
    file_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete file (soft delete + storage removal)."""
    file_record = await _get_accessible_file(db, file_id, current_user)

    is_admin = False
    if file_record.organization_id:
        member = (
            await db.execute(
                select(OrganizationMember).where(
                    OrganizationMember.organization_id == file_record.organization_id,
                    OrganizationMember.user_id == current_user.id,
                    OrganizationMember.status == "active",
                )
            )
        ).scalar_one_or_none()
        if member and member.role in (OrganizationRole.OWNER, OrganizationRole.ADMIN):
            is_admin = True

    if file_record.uploaded_by != current_user.id and not is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this file")

    await storage_service.delete_file(file_record.storage_path)

    file_record.is_deleted = True
    file_record.deleted_at = datetime.utcnow()
    file_record.status = FileStatus.DELETED
    await db.commit()
