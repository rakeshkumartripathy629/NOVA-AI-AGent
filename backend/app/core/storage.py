"""
Object storage abstraction (S3 compatible / MinIO) with a local-disk
fallback for environments where MinIO/S3 is unreachable.

Provides presigned URLs, direct upload/download, metadata and lifecycle
helpers used by the file service.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import time
from datetime import timedelta
from typing import Any, Dict, Optional
from uuid import UUID

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised for storage failures."""


_PROBE_TTL_SECONDS = 30


class StorageService:
    """Thin wrapper around the MinIO/S3 client with a local-disk fallback."""

    def __init__(self) -> None:
        self.provider = "minio"
        self._client: Optional[Minio] = None
        self._bucket = settings.STORAGE_BUCKET
        self._probe_result: Optional[bool] = None
        self._probe_time: float = 0.0

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
                timeout=5,
            )
        return self._client

    # ------------------------------------------------------------------
    # Backend selection
    # ------------------------------------------------------------------
    def _local_root(self) -> str:
        return os.path.abspath(settings.STORAGE_LOCAL_DIR)

    def _local_path(self, path: str) -> str:
        return os.path.join(self._local_root(), path.replace("/", os.sep))

    def _probe_minio(self) -> bool:
        """Probe MinIO availability, caching the result briefly."""
        now = time.monotonic()
        if self._probe_result is not None and (now - self._probe_time) < _PROBE_TTL_SECONDS:
            return self._probe_result
        try:
            self.client.bucket_exists(self._bucket)
            self._probe_result = True
            logger.debug("MinIO reachable")
        except Exception as exc:  # noqa: BLE001
            self._probe_result = False
            logger.warning("MinIO unreachable, using local-disk storage: %s", exc)
        self._probe_time = now
        return self._probe_result

    def is_local(self) -> bool:
        """Return True when storage is running against local disk."""
        if not settings.STORAGE_AUTO_FALLBACK:
            return False
        return not self._probe_minio()

    # ------------------------------------------------------------------
    # Bucket / lifecycle
    # ------------------------------------------------------------------
    async def ensure_bucket(self) -> None:
        """Create the storage bucket if it does not exist (MinIO only)."""
        if self.is_local():
            os.makedirs(self._local_root(), exist_ok=True)
            return
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

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------
    async def upload_file(
        self,
        path: str,
        content: bytes,
        content_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Upload raw bytes to storage (MinIO or local disk)."""
        content_type = content_type or mimetypes.guess_type(path)[0] or "application/octet-stream"
        if self.is_local():
            local = self._local_path(path)
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as handle:
                handle.write(content)
            return {
                "path": path,
                "size": len(content),
                "checksum": hashlib.sha256(content).hexdigest(),
                "etag": None,
            }
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
        if self.is_local():
            local = self._local_path(path)
            with open(local, "rb") as handle:
                return handle.read()
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
        if self.is_local():
            return os.path.isfile(self._local_path(path))
        try:
            self.client.stat_object(self._bucket, path)
            return True
        except S3Error:
            return False

    async def get_file_metadata(self, path: str) -> Dict[str, Any]:
        if self.is_local():
            local = self._local_path(path)
            if not os.path.isfile(local):
                raise StorageError(f"Metadata failed: object not found")
            stat = os.stat(local)
            return {
                "size": stat.st_size,
                "etag": None,
                "content_type": mimetypes.guess_type(path)[0] or "application/octet-stream",
                "last_modified": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            }
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
        if self.is_local():
            try:
                os.remove(self._local_path(path))
            except FileNotFoundError:
                pass
            return
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
        if self.is_local():
            raise StorageError("Presigned URLs are unavailable in local-disk mode")
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
        if self.is_local():
            raise StorageError("Presigned URLs are unavailable in local-disk mode")
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
