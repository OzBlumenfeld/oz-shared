from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import BinaryIO


@dataclass
class UploadResult:
    key: str
    url: str
    size: int | None = None
    content_type: str | None = None
    etag: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class ObjectInfo:
    key: str
    size: int
    last_modified: datetime
    etag: str
    content_type: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class S3StorageClient:
    """S3-compatible object storage client — works with MinIO, AWS S3, Cloudflare R2, etc."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str,
        access_key_id: str,
        secret_access_key: str,
        prefix: str = "",
        region: str = "us-east-1",
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._endpoint = endpoint_url.rstrip("/")
        self._boto_kwargs = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": region,
        }

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self._prefix}/{key}" if self._prefix else key

    def _strip_prefix(self, full_key: str) -> str:
        if self._prefix:
            return full_key.removeprefix(self._prefix + "/")
        return full_key

    @asynccontextmanager
    async def _client(self):
        import aioboto3
        session = aioboto3.Session()
        async with session.client("s3", **self._boto_kwargs) as s3:
            yield s3

    # ── upload ──────────────────────────────────────────────────────────────

    async def upload(
        self,
        key: str,
        data: bytes | BinaryIO | Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        full_key = self._full_key(key)
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = metadata

        body, size = _read_data(data)

        async with self._client() as s3:
            if isinstance(body, bytes):
                resp = await s3.put_object(Bucket=self._bucket, Key=full_key, Body=body, **extra)
                etag = resp.get("ETag", "").strip('"')
            else:
                await s3.upload_fileobj(body, self._bucket, full_key, ExtraArgs=extra or None)
                etag = None

        return UploadResult(
            key=key,
            url=f"{self._endpoint}/{self._bucket}/{full_key}",
            size=size,
            content_type=content_type,
            etag=etag,
            metadata=metadata or {},
        )

    # ── download ─────────────────────────────────────────────────────────────

    async def download(self, key: str) -> bytes:
        async with self._client() as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=self._full_key(key))
            return await response["Body"].read()

    # ── delete ───────────────────────────────────────────────────────────────

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=self._full_key(key))

    async def delete_many(self, keys: list[str]) -> None:
        """Bulk-delete up to 1 000 objects in a single request."""
        if not keys:
            return
        objects = [{"Key": self._full_key(k)} for k in keys]
        async with self._client() as s3:
            await s3.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": objects, "Quiet": True},
            )

    # ── copy ─────────────────────────────────────────────────────────────────

    async def copy(self, src_key: str, dst_key: str) -> None:
        async with self._client() as s3:
            await s3.copy_object(
                Bucket=self._bucket,
                CopySource={"Bucket": self._bucket, "Key": self._full_key(src_key)},
                Key=self._full_key(dst_key),
            )

    # ── metadata / existence ─────────────────────────────────────────────────

    async def exists(self, key: str) -> bool:
        import botocore.exceptions
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=self._full_key(key))
                return True
            except botocore.exceptions.ClientError as exc:
                if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                    return False
                raise

    async def get_info(self, key: str) -> ObjectInfo:
        async with self._client() as s3:
            head = await s3.head_object(Bucket=self._bucket, Key=self._full_key(key))
        return ObjectInfo(
            key=key,
            size=head["ContentLength"],
            last_modified=head["LastModified"],
            etag=head.get("ETag", "").strip('"'),
            content_type=head.get("ContentType"),
            metadata=head.get("Metadata", {}),
        )

    # ── list ─────────────────────────────────────────────────────────────────

    async def list_keys(self, prefix: str = "") -> list[str]:
        return [obj.key for obj in await self.list_objects(prefix)]

    async def list_objects(self, prefix: str = "") -> list[ObjectInfo]:
        full_prefix = self._full_key(prefix) if prefix else (self._prefix + "/" if self._prefix else "")
        objects: list[ObjectInfo] = []
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    objects.append(
                        ObjectInfo(
                            key=self._strip_prefix(obj["Key"]),
                            size=obj["Size"],
                            last_modified=obj["LastModified"],
                            etag=obj.get("ETag", "").strip('"'),
                        )
                    )
        return objects

    # ── presigned URL ─────────────────────────────────────────────────────────

    async def get_presigned_url(
        self,
        key: str,
        expires_in: int = 3600,
        method: str = "get_object",
    ) -> str:
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                method,
                Params={"Bucket": self._bucket, "Key": self._full_key(key)},
                ExpiresIn=expires_in,
            )

    # ── bucket management ────────────────────────────────────────────────────

    async def ensure_bucket_exists(self) -> None:
        """Create the bucket if it does not already exist."""
        import botocore.exceptions
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except botocore.exceptions.ClientError as exc:
                if exc.response["Error"]["Code"] in ("404", "NoSuchBucket"):
                    await s3.create_bucket(Bucket=self._bucket)
                else:
                    raise


def make_minio_client(
    bucket: str | None = None,
    *,
    endpoint_url: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    prefix: str = "",
) -> S3StorageClient:
    """Create an S3StorageClient configured for MinIO.

    Reads connection config from environment variables; keyword arguments
    override their corresponding env var:

      MINIO_ENDPOINT   – full URL, e.g. http://minio:9000
      MINIO_ACCESS_KEY – access key (username)
      MINIO_SECRET_KEY – secret key (password)
      MINIO_BUCKET     – target bucket name
    """
    resolved_bucket = bucket or os.environ.get("MINIO_BUCKET")
    resolved_endpoint = endpoint_url or os.environ.get("MINIO_ENDPOINT")
    resolved_access_key = access_key or os.environ.get("MINIO_ACCESS_KEY")
    resolved_secret_key = secret_key or os.environ.get("MINIO_SECRET_KEY")

    missing = [
        name
        for name, value in (
            ("bucket / MINIO_BUCKET", resolved_bucket),
            ("endpoint_url / MINIO_ENDPOINT", resolved_endpoint),
            ("access_key / MINIO_ACCESS_KEY", resolved_access_key),
            ("secret_key / MINIO_SECRET_KEY", resolved_secret_key),
        )
        if not value
    ]
    if missing:
        raise ValueError(f"Missing required MinIO config: {', '.join(missing)}")

    return S3StorageClient(
        bucket=resolved_bucket,  # type: ignore[arg-type]
        endpoint_url=resolved_endpoint,  # type: ignore[arg-type]
        access_key_id=resolved_access_key,  # type: ignore[arg-type]
        secret_access_key=resolved_secret_key,  # type: ignore[arg-type]
        prefix=prefix,
    )


# ── helpers ───────────────────────────────────────────────────────────────────


def _read_data(data: bytes | BinaryIO | Path) -> tuple[bytes | BinaryIO, int | None]:
    if isinstance(data, Path):
        raw = data.read_bytes()
        return raw, len(raw)
    if isinstance(data, bytes):
        return data, len(data)
    return data, None
