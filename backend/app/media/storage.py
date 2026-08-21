"""S3-compatible object storage, with a filesystem backend for no-Docker local runs.

Images never touch PostgreSQL. The browser never receives bucket credentials.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings
from app.core.errors import ProviderUnavailableError
from app.core.logging import get_logger

log = get_logger(__name__)


class ObjectStorage:
    def ensure_bucket(self) -> None: ...
    def put(self, key: str, data: bytes, content_type: str) -> str: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def presigned_url(self, key: str | None, expires_in: int | None = None) -> str | None: ...

    @staticmethod
    def build_key(claim_id: uuid.UUID, filename: str, *, variant: str = "original") -> str:
        stamp = datetime.now(UTC).strftime("%Y/%m/%d")
        suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
        return f"claims/{stamp}/{claim_id}/{variant}/{uuid.uuid4().hex}.{suffix}"


class FileSystemStorage(ObjectStorage):
    """Local disk. Used when MinIO/S3 is not running."""

    def __init__(self) -> None:
        root = settings.storage_local_path or ".data/claim-images"
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def ensure_bucket(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        log.info("storage.filesystem", path=str(self.root))

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise ProviderUnavailableError("Invalid storage key.")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise ProviderUnavailableError("Could not read the stored image.")
        return path.read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            path.unlink()

    def presigned_url(self, key: str | None, expires_in: int | None = None) -> str | None:
        if not key:
            return None
        return f"/api/v1/media/{quote(key, safe='/')}"


class S3Storage(ObjectStorage):
    def __init__(self) -> None:
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.storage_endpoint,
            aws_access_key_id=settings.storage_access_key,
            aws_secret_access_key=settings.storage_secret_key,
            region_name=settings.storage_region,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
        self._public_client = (
            boto3.client(
                "s3",
                endpoint_url=settings.storage_public_endpoint,
                aws_access_key_id=settings.storage_access_key,
                aws_secret_access_key=settings.storage_secret_key,
                region_name=settings.storage_region,
                config=Config(signature_version="s3v4"),
            )
            if settings.storage_public_endpoint != settings.storage_endpoint
            else self._client
        )
        self.bucket = settings.storage_bucket

    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self.bucket)
                log.info("storage.bucket_created", bucket=self.bucket)
            except (ClientError, BotoCoreError) as exc:
                raise ProviderUnavailableError(
                    f"Could not create storage bucket '{self.bucket}'."
                ) from exc

    def put(self, key: str, data: bytes, content_type: str) -> str:
        try:
            self._client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                ACL="private",
            )
        except (ClientError, BotoCoreError) as exc:
            log.error("storage.put_failed", key=key, error=str(exc))
            raise ProviderUnavailableError("Image storage is currently unavailable.") from exc
        return key

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
            return response["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            log.error("storage.get_failed", key=key, error=str(exc))
            raise ProviderUnavailableError("Could not read the stored image.") from exc

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            log.warning("storage.delete_failed", key=key, error=str(exc))

    def presigned_url(self, key: str | None, expires_in: int | None = None) -> str | None:
        if not key:
            return None
        try:
            return self._public_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_in or settings.storage_presign_ttl_seconds,
            )
        except (ClientError, BotoCoreError) as exc:
            log.warning("storage.presign_failed", key=key, error=str(exc))
            return None


@lru_cache
def get_storage() -> ObjectStorage:
    backend = (settings.storage_backend or "auto").lower()
    if backend == "filesystem" or (
        backend == "auto" and not settings.storage_access_key
    ):
        return FileSystemStorage()
    return S3Storage()
