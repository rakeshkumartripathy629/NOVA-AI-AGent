"""
Object storage abstraction (S3 compatible / MinIO).

Provides presigned URLs, direct upload/download, metadata and lifecycle
helpers used by the file service.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
from datetime import timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised for storage failures."""


class StorageService:
    """Thin wrapper around the MinIO/S3 client."""

    def __init__(self) -> None:
        self.provider = "minio"
        self._client: Optional[Minio] = None
        self._bucket = settings.STORAGE_BUCKET

    @property
    def client(self) -> Minio:
        if self._client is None:
            secure = settings.STORAGE_SECURE
            endpoint = settings.STORAGE_ENDPOINT
            if endpoint.startswith(("http://", "https://")):
                from urllib.parse import urlparse
                parsed = urlparse(endpoint)
                secure = parsed.scheme == "https"
                endpoint = parsed.netloc
            self._client = Minio(
                endpoint,
                access_key=settings.STORAGE_ACCESS_KEY,
                secret_key=settings.STORAGE_SECRET_KEY,
                secure=secure,
                region=settings.STORAGE_REGION,
            )
        return self._client

    async def ensure_bucket(self) -> None:
        """Create the storage bucket if it does not exist."""
        try:
            if not self.client.bucket_exists(self._bucket):
                self.client.make_bucket(self._bucket)
                logger.info("Created storage bucket %s", self._bucket)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Storage bucket check failed: %s", exc)

    def generate_path(
        self,
        file_id: UUID,
        filename: str,
        project_id: Optional[UUID] = None,
        conversation_id: Optional[UUID] = None,
        kb_id: Optional[UUID] = None,
    ) -> str:
        """Build a namespaced object key."""
        scope = "general"
        if project_id:
            scope = f"project/{project_id}"
        elif conversation_id:
            scope = f"conversation/{conversation_id}"
        elif kb_id:
            scope = f"knowledge_base/{kb_id}"
        safe_name = filename.replace("\\", "_").replace("/", "_").replace(" ", "_")
        return f"{scope}/{file_id}/{safe_name}"

    async def upload_file(
        self,
        path: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload raw bytes to storage."""
        content_type = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        try:
            self.client.put_object(
                self._bucket,
                path,
                len(content),
                content,
                content_type=content_type,
            )
            return {
                "path": path,
                "size": len(content),
                "checksum": hashlib.sha256(content).hexdigest(),
                "etag": None,
            }
        except S3Error as exc:
            raise StorageError(f"Upload failed: {exc.message}") from exc

    async def download_file(self, path: str) -> bytes:
        """Download object content."""
        try:
            response = self.client.get_object(self._bucket, path)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except S3Error as exc:
            raise StorageError(f"Download failed: {exc.message}") from exc

    async def file_exists(self, path: str) -> bool:
        try:
            self.client.stat_object(self._bucket, path)
            return True
        except S3Error:
            return False

    async def get_file_metadata(self, path: str) -> Dict[str, Any]:
        try:
            obj = self.client.stat_object(self._bucket, path)
            return {
                "size": obj.size,
                "etag": obj.etag,
                "content_type": obj.content_type,
                "last_modified": obj.last_modified.isoformat() if obj.last_modified else None,
            }
        except S3Error as exc:
            raise StorageError(f"Metadata failed: {exc.message}") from exc

    async def delete_file(self, path: str) -> None:
        try:
            self.client.remove_object(self._bucket, path)
        except S3Error as exc:
            logger.warning("Delete failed for %s: %s", path, exc.message)

    async def generate_presigned_upload_url(
        self,
        path: str,
        content_type: str = "application/octet-stream",
        expires_in: int = 3600,
    ) -> str:
        try:
            return self.client.presigned_put_object(
                self._bucket,
                path,
                expires=timedelta(seconds=expires_in),
            )
        except S3Error as exc:
            raise StorageError(f"Presign failed: {exc.message}") from exc

    async def generate_presigned_download_url(
        self,
        path: str,
        filename: Optional[str] = None,
        expires_in: int = 3600,
    ) -> str:
        try:
            if filename:
                params = {
                    "response-content-disposition": f"attachment; filename=\"{filename}\""
                }
                return self.client.presigned_get_object(
                    self._bucket,
                    path,
                    expires=timedelta(seconds=expires_in),
                    response_headers=params,
                )
            return self.client.presigned_get_object(
                self._bucket,
                path,
                expires=timedelta(seconds=expires_in),
            )
        except S3Error as exc:
            raise StorageError(f"Presign failed: {exc.message}") from exc


storage_service = StorageService()
