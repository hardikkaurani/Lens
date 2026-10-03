"""S3-compatible object storage abstraction for LENS binary file ingestion."""

from dataclasses import dataclass
from datetime import datetime, timezone
import io
import logging
from typing import BinaryIO, Optional, Union
from urllib.parse import urlparse
import uuid

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings, get_settings

logger = logging.getLogger(__name__)


class StorageError(Exception):
    """Base exception for storage abstraction operations."""


class ObjectNotFoundError(StorageError):
    """Raised when the specified object does not exist in the bucket."""


class StorageConnectionError(StorageError):
    """Raised when communication with the S3/MinIO service fails."""


@dataclass(frozen=True)
class StorageObjectMeta:
    """Metadata representing an object persisted in object storage."""

    bucket: str
    key: str
    size: int
    content_type: str
    etag: str
    last_modified: Optional[datetime] = None


class StorageClient:
    """Unified MinIO/S3-compatible object storage client for LENS."""

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        default_bucket: str = "lens-media",
        region: str = "us-east-1",
        secure: Optional[bool] = None,
    ) -> None:
        self.default_bucket = default_bucket
        self.region = region

        # Determine host and TLS setting from endpoint URI
        endpoint_clean = endpoint.strip()
        parsed = urlparse(endpoint_clean)

        if parsed.scheme in ("http", "https"):
            host = parsed.netloc
            is_secure = parsed.scheme == "https" if secure is None else secure
        else:
            host = endpoint_clean
            is_secure = False if secure is None else secure

        self.endpoint_host = host
        self.is_secure = is_secure

        try:
            self._client = Minio(
                endpoint=host,
                access_key=access_key,
                secret_key=secret_key,
                secure=is_secure,
                region=region,
            )
        except Exception as e:
            logger.error("Failed to initialize MinIO client for host '%s': %s", host, e)
            raise StorageConnectionError(f"Failed to initialize storage client: {e}") from e

    @property
    def client(self) -> Minio:
        """Underlying Minio client instance."""
        return self._client

    def ensure_bucket_exists(self, bucket: Optional[str] = None) -> None:
        """Verify the specified bucket exists, creating it if it does not."""
        target_bucket = bucket or self.default_bucket
        try:
            if not self._client.bucket_exists(target_bucket):
                logger.info("Bucket '%s' does not exist; creating it...", target_bucket)
                self._client.make_bucket(target_bucket, location=self.region)
                logger.info("Bucket '%s' created successfully.", target_bucket)
        except S3Error as e:
            logger.error("S3 error while ensuring bucket '%s': %s", target_bucket, e.message)
            raise StorageError(f"Storage error verifying bucket '{target_bucket}': {e.message}") from e
        except Exception as e:
            logger.error("Connection error while ensuring bucket '%s': %s", target_bucket, e)
            raise StorageConnectionError(f"Connection failure verifying bucket '{target_bucket}': {e}") from e

    def put_object(
        self,
        key: str,
        data: Union[BinaryIO, bytes],
        length: int,
        content_type: str = "application/octet-stream",
        bucket: Optional[str] = None,
    ) -> StorageObjectMeta:
        """Store an object in object storage.

        Never logs credentials or payloads.
        """
        target_bucket = bucket or self.default_bucket
        stream: BinaryIO
        if isinstance(data, bytes):
            stream = io.BytesIO(data)
            stream_length = len(data)
        else:
            stream = data
            stream_length = length

        try:
            result = self._client.put_object(
                bucket_name=target_bucket,
                object_name=key,
                data=stream,
                length=stream_length,
                content_type=content_type,
            )
            logger.info(
                "Stored object '%s' in bucket '%s' (%d bytes, etag=%s)",
                key,
                target_bucket,
                stream_length,
                result.etag,
            )
            return StorageObjectMeta(
                bucket=target_bucket,
                key=key,
                size=stream_length,
                content_type=content_type,
                etag=result.etag or "",
                last_modified=datetime.now(timezone.utc),
            )
        except S3Error as e:
            logger.error("S3 error putting object '%s' in bucket '%s': %s", key, target_bucket, e.message)
            raise StorageError(f"Failed to store object '{key}': {e.message}") from e
        except Exception as e:
            logger.error("Connection error putting object '%s' in bucket '%s': %s", key, target_bucket, e)
            raise StorageConnectionError(f"Connection failure storing object '{key}': {e}") from e

    def get_object(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> bytes:
        """Retrieve the entire binary content of an object into memory.

        Raises ObjectNotFoundError if the object does not exist.
        """
        target_bucket = bucket or self.default_bucket
        response = None
        try:
            response = self._client.get_object(target_bucket, key)
            return response.read()
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchBucket"):
                raise ObjectNotFoundError(f"Object '{key}' not found in bucket '{target_bucket}'.") from e
            logger.error("S3 error getting object '%s' from bucket '%s': %s", key, target_bucket, e.message)
            raise StorageError(f"Failed to retrieve object '{key}': {e.message}") from e
        except Exception as e:
            logger.error("Connection error getting object '%s' from bucket '%s': %s", key, target_bucket, e)
            raise StorageConnectionError(f"Connection failure retrieving object '{key}': {e}") from e
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def stat_object(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> StorageObjectMeta:
        """Retrieve metadata for an object without downloading its payload."""
        target_bucket = bucket or self.default_bucket
        try:
            stat = self._client.stat_object(target_bucket, key)
            return StorageObjectMeta(
                bucket=target_bucket,
                key=key,
                size=stat.size or 0,
                content_type=stat.content_type or "application/octet-stream",
                etag=stat.etag or "",
                last_modified=stat.last_modified,
            )
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchBucket"):
                raise ObjectNotFoundError(f"Object '{key}' not found in bucket '{target_bucket}'.") from e
            logger.error("S3 error stating object '%s' in bucket '%s': %s", key, target_bucket, e.message)
            raise StorageError(f"Failed to inspect object '{key}': {e.message}") from e
        except Exception as e:
            logger.error("Connection error stating object '%s' in bucket '%s': %s", key, target_bucket, e)
            raise StorageConnectionError(f"Connection failure inspecting object '{key}': {e}") from e

    def object_exists(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Check whether an object exists in storage without raising if absent."""
        try:
            self.stat_object(key, bucket=bucket)
            return True
        except ObjectNotFoundError:
            return False
        except Exception:
            return False

    def delete_object(
        self,
        key: str,
        bucket: Optional[str] = None,
    ) -> bool:
        """Delete an object from object storage.

        Idempotent: returns True if deleted or already nonexistent.
        """
        target_bucket = bucket or self.default_bucket
        try:
            self._client.remove_object(target_bucket, key)
            logger.info("Deleted object '%s' from bucket '%s'", key, target_bucket)
            return True
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchBucket"):
                return True
            logger.warning("S3 error deleting object '%s' from bucket '%s': %s", key, target_bucket, e.message)
            return False
        except Exception as e:
            logger.warning("Connection error deleting object '%s' from bucket '%s': %s", key, target_bucket, e)
            return False

    @staticmethod
    def generate_secure_object_key(
        capture_id: uuid.UUID,
        extension: str = ".pdf",
    ) -> str:
        """Generate a cryptographically safe, traversal-proof internal object key.

        Format: captures/<capture_uuid>/<object_uuid>.<ext>
        Never interpolates user-provided filenames or relative path components.
        """
        clean_ext = extension.lower().strip()
        if not clean_ext.startswith("."):
            clean_ext = f".{clean_ext}"
        # Filter extension to safe alphanumeric characters only
        clean_ext = "." + "".join(c for c in clean_ext[1:] if c.isalnum())
        if clean_ext == ".":
            clean_ext = ".bin"

        object_id = uuid.uuid4().hex
        return f"captures/{capture_id}/{object_id}{clean_ext}"


_storage_client: Optional[StorageClient] = None


def get_storage_client(settings: Optional[Settings] = None) -> StorageClient:
    """Return a singleton instance of StorageClient configured from application settings."""
    global _storage_client
    if _storage_client is None:
        cfg = settings or get_settings()
        _storage_client = StorageClient(
            endpoint=cfg.S3_ENDPOINT,
            access_key=cfg.S3_ACCESS_KEY,
            secret_key=cfg.S3_SECRET_KEY,
            default_bucket=cfg.S3_BUCKET,
            region=cfg.S3_REGION or "us-east-1",
        )
    return _storage_client
