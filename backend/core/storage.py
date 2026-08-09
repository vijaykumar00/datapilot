"""Storage providers for uploaded datasets and generated artifacts."""

from __future__ import annotations

import logging
import os
import re
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

logger = logging.getLogger("datapilot.storage")

PRODUCTION_ENVS = {"production", "prod"}
TRUTHY = {"1", "true", "yes", "on"}


def _is_production() -> bool:
    return os.getenv("APP_ENV", "development").strip().lower() in PRODUCTION_ENVS


def _truthy_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in TRUTHY


def _safe_part(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", (value or "").strip()).strip(".-")
    return cleaned or fallback


def _safe_filename(filename: str) -> str:
    return _safe_part(Path(filename or "dataset").name, "dataset")


class BaseStorageProvider(ABC):
    """Abstract base class for file storage engines."""

    @abstractmethod
    def save_file(self, workspace_id: str, dataset_id: str, filename: str, content: bytes) -> tuple[Path, str]:
        """Save file content and return a local readable path plus durable URI."""
        raise NotImplementedError

    @abstractmethod
    def read_file(self, workspace_id: str, dataset_id: str, filename: str) -> bytes:
        """Read file bytes."""
        raise NotImplementedError

    @abstractmethod
    def delete_file(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        """Delete a file."""
        raise NotImplementedError

    @abstractmethod
    def delete_dataset_dir(self, workspace_id: str, dataset_id: str) -> bool:
        """Delete all files for a dataset."""
        raise NotImplementedError

    @abstractmethod
    def exists(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        """Return True when a file exists."""
        raise NotImplementedError

    @abstractmethod
    def signed_url(self, workspace_id: str, dataset_id: str, filename: str, expires_seconds: int = 900) -> str:
        """Return a temporary read URL or local path URI."""
        raise NotImplementedError

    @abstractmethod
    def metadata(self, workspace_id: str, dataset_id: str, filename: str) -> dict[str, Any]:
        """Return storage metadata."""
        raise NotImplementedError

    @abstractmethod
    def size(self, workspace_id: str, dataset_id: str, filename: str) -> int:
        """Return object size in bytes."""
        raise NotImplementedError

    @abstractmethod
    def list(self, workspace_id: str, dataset_id: str | None = None) -> list[str]:
        """List object names under a workspace or dataset."""
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> tuple[bool, str]:
        """Return provider readiness."""
        raise NotImplementedError

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name."""
        raise NotImplementedError


class LocalStorageProvider(BaseStorageProvider):
    """Local disk provider for development and single-node testing."""

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).parent.parent / "uploads"
        self.base_dir.mkdir(exist_ok=True, parents=True)

    def _target_dir(self, workspace_id: str, dataset_id: str) -> Path:
        target = self.base_dir / _safe_part(workspace_id, "workspace") / _safe_part(dataset_id, "dataset")
        target.mkdir(exist_ok=True, parents=True)
        return target

    def _target_path(self, workspace_id: str, dataset_id: str, filename: str) -> Path:
        return self._target_dir(workspace_id, dataset_id) / _safe_filename(filename)

    def save_file(self, workspace_id: str, dataset_id: str, filename: str, content: bytes) -> tuple[Path, str]:
        target_path = self._target_path(workspace_id, dataset_id, filename)
        target_path.write_bytes(content)
        uri = f"/uploads/{_safe_part(workspace_id, 'workspace')}/{_safe_part(dataset_id, 'dataset')}/{target_path.name}"
        logger.info("Saved file locally: %s", uri)
        return target_path, uri

    def read_file(self, workspace_id: str, dataset_id: str, filename: str) -> bytes:
        target_path = self._target_path(workspace_id, dataset_id, filename)
        if not target_path.exists():
            raise FileNotFoundError(f"File not found: {target_path}")
        return target_path.read_bytes()

    def delete_file(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        target_path = self._target_path(workspace_id, dataset_id, filename)
        if not target_path.exists():
            return False
        try:
            target_path.unlink()
            logger.info("Deleted local file: %s", target_path)
            return True
        except Exception as exc:
            logger.error("Error deleting local file %s: %s", target_path, exc)
            return False

    def delete_dataset_dir(self, workspace_id: str, dataset_id: str) -> bool:
        target_dir = self.base_dir / _safe_part(workspace_id, "workspace") / _safe_part(dataset_id, "dataset")
        if not target_dir.exists():
            return False
        try:
            shutil.rmtree(target_dir)
            logger.info("Deleted dataset directory: %s", target_dir)
            return True
        except Exception as exc:
            logger.error("Error removing directory %s: %s", target_dir, exc)
            return False

    def exists(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        return self._target_path(workspace_id, dataset_id, filename).exists()

    def signed_url(self, workspace_id: str, dataset_id: str, filename: str, expires_seconds: int = 900) -> str:
        path = self._target_path(workspace_id, dataset_id, filename)
        return path.as_posix()

    def metadata(self, workspace_id: str, dataset_id: str, filename: str) -> dict[str, Any]:
        path = self._target_path(workspace_id, dataset_id, filename)
        stat = path.stat()
        return {"path": path.as_posix(), "size": stat.st_size, "modified_at": stat.st_mtime}

    def size(self, workspace_id: str, dataset_id: str, filename: str) -> int:
        return self._target_path(workspace_id, dataset_id, filename).stat().st_size

    def list(self, workspace_id: str, dataset_id: str | None = None) -> list[str]:
        root = self.base_dir / _safe_part(workspace_id, "workspace")
        if dataset_id:
            root = root / _safe_part(dataset_id, "dataset")
        if not root.exists():
            return []
        return [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]

    def health_check(self) -> tuple[bool, str]:
        return (self.base_dir.exists() and os.access(self.base_dir, os.W_OK), f"local:{self.base_dir.as_posix()}")

    @property
    def provider_name(self) -> str:
        return "local"


class S3CompatibleStorageProvider(BaseStorageProvider):
    """S3-compatible provider for AWS S3, Cloudflare R2, and MinIO."""

    def __init__(self, local_cache_dir: Path | None = None):
        self.bucket = os.getenv("S3_BUCKET", "")
        self.region = os.getenv("S3_REGION", "us-east-1")
        self.endpoint_url = os.getenv("S3_ENDPOINT_URL") or None
        self.presign_expires = int(os.getenv("S3_PRESIGN_EXPIRES", "900"))
        self.create_bucket = _truthy_env("S3_CREATE_BUCKET", False)
        self.local_cache_dir = local_cache_dir or Path(os.getenv("STORAGE_LOCAL_CACHE_DIR", Path(__file__).parent.parent / "uploads" / "_cache"))
        self.local_cache_dir.mkdir(parents=True, exist_ok=True)
        self._client = None
        self._bucket_checked = False
        if not self.bucket:
            raise RuntimeError("S3_BUCKET is required when STORAGE_PROVIDER=s3.")

    def _client_for_s3(self):
        if self._client is not None:
            return self._client
        try:
            import boto3  # type: ignore
            from botocore.config import Config  # type: ignore
        except ImportError as exc:
            raise RuntimeError("boto3 is required when STORAGE_PROVIDER=s3.") from exc

        access_key = os.getenv("S3_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID")
        secret_key = os.getenv("S3_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY")
        config = Config(
            signature_version=os.getenv("S3_SIGNATURE_VERSION", "s3v4"),
            s3={"addressing_style": os.getenv("S3_ADDRESSING_STYLE", "path")},
        )
        self._client = boto3.client(
            "s3",
            region_name=self.region,
            endpoint_url=self.endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=config,
        )
        return self._client

    def _ensure_bucket(self) -> None:
        if self._bucket_checked:
            return
        client = self._client_for_s3()
        try:
            client.head_bucket(Bucket=self.bucket)
        except Exception:
            if not self.create_bucket:
                raise
            client.create_bucket(Bucket=self.bucket)
        self._bucket_checked = True

    def _key(self, workspace_id: str, dataset_id: str, filename: str) -> str:
        return (
            f"workspace/{_safe_part(workspace_id, 'workspace')}/"
            f"datasets/{_safe_part(dataset_id, 'dataset')}/{_safe_filename(filename)}"
        )

    def _cache_path(self, workspace_id: str, dataset_id: str, filename: str) -> Path:
        path = self.local_cache_dir / _safe_part(workspace_id, "workspace") / _safe_part(dataset_id, "dataset")
        path.mkdir(parents=True, exist_ok=True)
        return path / _safe_filename(filename)

    def save_file(self, workspace_id: str, dataset_id: str, filename: str, content: bytes) -> tuple[Path, str]:
        self._ensure_bucket()
        key = self._key(workspace_id, dataset_id, filename)
        self._client_for_s3().put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            Metadata={
                "workspace_id": _safe_part(workspace_id, "workspace"),
                "dataset_id": _safe_part(dataset_id, "dataset"),
            },
        )
        cache_path = self._cache_path(workspace_id, dataset_id, filename)
        cache_path.write_bytes(content)
        return cache_path, f"s3://{self.bucket}/{key}"

    def read_file(self, workspace_id: str, dataset_id: str, filename: str) -> bytes:
        self._ensure_bucket()
        obj = self._client_for_s3().get_object(Bucket=self.bucket, Key=self._key(workspace_id, dataset_id, filename))
        return obj["Body"].read()

    def delete_file(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        self._ensure_bucket()
        self._client_for_s3().delete_object(Bucket=self.bucket, Key=self._key(workspace_id, dataset_id, filename))
        cache_path = self._cache_path(workspace_id, dataset_id, filename)
        cache_path.unlink(missing_ok=True)
        return True

    def delete_dataset_dir(self, workspace_id: str, dataset_id: str) -> bool:
        self._ensure_bucket()
        client = self._client_for_s3()
        prefix = f"workspace/{_safe_part(workspace_id, 'workspace')}/datasets/{_safe_part(dataset_id, 'dataset')}/"
        paginator = client.get_paginator("list_objects_v2")
        deleted_any = False
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
            if objects:
                client.delete_objects(Bucket=self.bucket, Delete={"Objects": objects})
                deleted_any = True
        shutil.rmtree(self.local_cache_dir / _safe_part(workspace_id, "workspace") / _safe_part(dataset_id, "dataset"), ignore_errors=True)
        return deleted_any

    def exists(self, workspace_id: str, dataset_id: str, filename: str) -> bool:
        try:
            self._ensure_bucket()
            self._client_for_s3().head_object(Bucket=self.bucket, Key=self._key(workspace_id, dataset_id, filename))
            return True
        except Exception:
            return False

    def signed_url(self, workspace_id: str, dataset_id: str, filename: str, expires_seconds: int = 900) -> str:
        self._ensure_bucket()
        return self._client_for_s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(workspace_id, dataset_id, filename)},
            ExpiresIn=expires_seconds or self.presign_expires,
        )

    def metadata(self, workspace_id: str, dataset_id: str, filename: str) -> dict[str, Any]:
        self._ensure_bucket()
        response = self._client_for_s3().head_object(Bucket=self.bucket, Key=self._key(workspace_id, dataset_id, filename))
        return {
            "uri": f"s3://{self.bucket}/{self._key(workspace_id, dataset_id, filename)}",
            "size": response.get("ContentLength", 0),
            "content_type": response.get("ContentType"),
            "metadata": response.get("Metadata", {}),
        }

    def size(self, workspace_id: str, dataset_id: str, filename: str) -> int:
        return int(self.metadata(workspace_id, dataset_id, filename).get("size", 0))

    def list(self, workspace_id: str, dataset_id: str | None = None) -> list[str]:
        self._ensure_bucket()
        prefix = f"workspace/{_safe_part(workspace_id, 'workspace')}/"
        if dataset_id:
            prefix += f"datasets/{_safe_part(dataset_id, 'dataset')}/"
        paginator = self._client_for_s3().get_paginator("list_objects_v2")
        keys: list[str] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(item["Key"] for item in page.get("Contents", []))
        return keys

    def health_check(self) -> tuple[bool, str]:
        try:
            self._ensure_bucket()
            return True, f"s3:{self.bucket}"
        except Exception as exc:
            return False, str(exc)

    @property
    def provider_name(self) -> str:
        return "s3"


_storage_provider: BaseStorageProvider | None = None


def get_storage_provider() -> BaseStorageProvider:
    global _storage_provider
    if _storage_provider is not None:
        return _storage_provider

    provider = os.getenv("STORAGE_PROVIDER", "local").strip().lower()
    if provider in {"s3", "r2", "minio"}:
        _storage_provider = S3CompatibleStorageProvider()
        return _storage_provider

    if _is_production() and not _truthy_env("ALLOW_LOCAL_STORAGE_IN_PRODUCTION", False):
        raise RuntimeError(
            "STORAGE_PROVIDER=local is not allowed in production. "
            "Use STORAGE_PROVIDER=s3 with S3_BUCKET/S3_ENDPOINT_URL, or set "
            "ALLOW_LOCAL_STORAGE_IN_PRODUCTION=true only for an explicitly accepted single-node beta."
        )

    _storage_provider = LocalStorageProvider()
    return _storage_provider


def reset_storage_provider() -> None:
    global _storage_provider
    _storage_provider = None


def storage_health() -> dict[str, object]:
    provider = get_storage_provider()
    ok, detail = provider.health_check()
    return {"ok": ok, "provider": provider.provider_name, "detail": detail}
