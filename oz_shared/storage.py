from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Protocol, Union, runtime_checkable


@dataclass
class UploadResult:
    key: str
    url: str | None = None
    size: int | None = None
    content_type: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class StorageClient(Protocol):
    async def upload(
        self,
        key: str,
        data: bytes | BinaryIO | Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult: ...

    async def download(self, key: str) -> bytes: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...

    async def get_url(self, key: str, expires_in: int = 3600) -> str: ...

    async def list_keys(self, prefix: str = "") -> list[str]: ...


def _resolve_data(data: bytes | BinaryIO | Path) -> tuple[bytes | BinaryIO, int | None]:
    if isinstance(data, Path):
        size = data.stat().st_size
        return data.read_bytes(), size
    if isinstance(data, bytes):
        return data, len(data)
    return data, None


class S3StorageClient:
    """AWS S3 or any S3-compatible storage (MinIO, Cloudflare R2, DigitalOcean Spaces, etc.)."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._boto_kwargs: dict = {}
        if region:
            self._boto_kwargs["region_name"] = region
        if endpoint_url:
            self._boto_kwargs["endpoint_url"] = endpoint_url
        if access_key_id and secret_access_key:
            self._boto_kwargs["aws_access_key_id"] = access_key_id
            self._boto_kwargs["aws_secret_access_key"] = secret_access_key

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self._prefix}/{key}" if self._prefix else key

    @asynccontextmanager
    async def _client(self):
        import aioboto3
        session = aioboto3.Session()
        async with session.client("s3", **self._boto_kwargs) as s3:
            yield s3

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

        body, size = _resolve_data(data)

        async with self._client() as s3:
            if isinstance(body, bytes):
                await s3.put_object(Bucket=self._bucket, Key=full_key, Body=body, **extra)
            else:
                await s3.upload_fileobj(body, self._bucket, full_key, ExtraArgs=extra or None)

        endpoint = self._boto_kwargs.get("endpoint_url")
        if endpoint:
            url = f"{endpoint.rstrip('/')}/{self._bucket}/{full_key}"
        else:
            region = self._boto_kwargs.get("region_name", "us-east-1")
            url = f"https://{self._bucket}.s3.{region}.amazonaws.com/{full_key}"

        return UploadResult(
            key=key,
            url=url,
            size=size,
            content_type=content_type,
            metadata=metadata or {},
        )

    async def download(self, key: str) -> bytes:
        async with self._client() as s3:
            response = await s3.get_object(Bucket=self._bucket, Key=self._full_key(key))
            return await response["Body"].read()

    async def delete(self, key: str) -> None:
        async with self._client() as s3:
            await s3.delete_object(Bucket=self._bucket, Key=self._full_key(key))

    async def exists(self, key: str) -> bool:
        import botocore.exceptions
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=self._full_key(key))
                return True
            except botocore.exceptions.ClientError as e:
                if e.response["Error"]["Code"] == "404":
                    return False
                raise

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        async with self._client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": self._full_key(key)},
                ExpiresIn=expires_in,
            )

    async def list_keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._full_key(prefix) if prefix else (self._prefix + "/" if self._prefix else "")
        keys: list[str] = []
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=full_prefix):
                for obj in page.get("Contents", []):
                    raw_key = obj["Key"]
                    # Strip the module-level prefix so callers see logical keys
                    if self._prefix:
                        raw_key = raw_key.removeprefix(self._prefix + "/")
                    keys.append(raw_key)
        return keys


class GCSStorageClient:
    """Google Cloud Storage."""

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        project: str | None = None,
        credentials=None,
    ) -> None:
        self._bucket_name = bucket
        self._prefix = prefix.strip("/")
        self._project = project
        self._credentials = credentials

    def _client(self):
        from google.cloud import storage as gcs
        return gcs.Client(project=self._project, credentials=self._credentials)

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self._prefix}/{key}" if self._prefix else key

    def _blob(self, key: str):
        client = self._client()
        bucket = client.bucket(self._bucket_name)
        return bucket.blob(self._full_key(key))

    async def upload(
        self,
        key: str,
        data: bytes | BinaryIO | Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        import asyncio
        body, size = _resolve_data(data)

        def _do_upload():
            blob = self._blob(key)
            if metadata:
                blob.metadata = metadata
            if isinstance(body, bytes):
                blob.upload_from_string(body, content_type=content_type or "application/octet-stream")
            else:
                blob.upload_from_file(body, content_type=content_type or "application/octet-stream")
            return blob.public_url

        url = await asyncio.get_event_loop().run_in_executor(None, _do_upload)
        return UploadResult(
            key=key,
            url=url,
            size=size,
            content_type=content_type,
            metadata=metadata or {},
        )

    async def download(self, key: str) -> bytes:
        import asyncio
        blob = self._blob(key)
        return await asyncio.get_event_loop().run_in_executor(None, blob.download_as_bytes)

    async def delete(self, key: str) -> None:
        import asyncio
        blob = self._blob(key)
        await asyncio.get_event_loop().run_in_executor(None, blob.delete)

    async def exists(self, key: str) -> bool:
        import asyncio
        blob = self._blob(key)
        return await asyncio.get_event_loop().run_in_executor(None, blob.exists)

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        import asyncio
        from datetime import timedelta
        blob = self._blob(key)

        def _sign():
            return blob.generate_signed_url(expiration=timedelta(seconds=expires_in), method="GET")

        return await asyncio.get_event_loop().run_in_executor(None, _sign)

    async def list_keys(self, prefix: str = "") -> list[str]:
        import asyncio
        from google.cloud import storage as gcs

        full_prefix = self._full_key(prefix) if prefix else (self._prefix + "/" if self._prefix else "")

        def _list():
            client = self._client()
            blobs = client.list_blobs(self._bucket_name, prefix=full_prefix)
            keys = []
            for blob in blobs:
                raw = blob.name
                if self._prefix:
                    raw = raw.removeprefix(self._prefix + "/")
                keys.append(raw)
            return keys

        return await asyncio.get_event_loop().run_in_executor(None, _list)


class AzureBlobStorageClient:
    """Azure Blob Storage."""

    def __init__(
        self,
        container: str,
        prefix: str = "",
        connection_string: str | None = None,
        account_url: str | None = None,
        credential=None,
    ) -> None:
        self._container = container
        self._prefix = prefix.strip("/")
        self._connection_string = connection_string or os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        self._account_url = account_url
        self._credential = credential

    def _full_key(self, key: str) -> str:
        key = key.lstrip("/")
        return f"{self._prefix}/{key}" if self._prefix else key

    def _service_client(self):
        from azure.storage.blob.aio import BlobServiceClient
        if self._connection_string:
            return BlobServiceClient.from_connection_string(self._connection_string)
        return BlobServiceClient(account_url=self._account_url, credential=self._credential)

    async def upload(
        self,
        key: str,
        data: bytes | BinaryIO | Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        from azure.storage.blob import ContentSettings
        full_key = self._full_key(key)
        body, size = _resolve_data(data)

        async with self._service_client() as svc:
            blob = svc.get_blob_client(container=self._container, blob=full_key)
            settings = ContentSettings(content_type=content_type) if content_type else None
            await blob.upload_blob(
                body,
                overwrite=True,
                content_settings=settings,
                metadata=metadata,
            )
            url = blob.url

        return UploadResult(
            key=key,
            url=url,
            size=size,
            content_type=content_type,
            metadata=metadata or {},
        )

    async def download(self, key: str) -> bytes:
        async with self._service_client() as svc:
            blob = svc.get_blob_client(container=self._container, blob=self._full_key(key))
            stream = await blob.download_blob()
            return await stream.readall()

    async def delete(self, key: str) -> None:
        async with self._service_client() as svc:
            blob = svc.get_blob_client(container=self._container, blob=self._full_key(key))
            await blob.delete_blob()

    async def exists(self, key: str) -> bool:
        async with self._service_client() as svc:
            blob = svc.get_blob_client(container=self._container, blob=self._full_key(key))
            return await blob.exists()

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        from datetime import datetime, timezone, timedelta
        from azure.storage.blob import generate_blob_sas, BlobSasPermissions

        async with self._service_client() as svc:
            account_name = svc.account_name
            account_key = svc.credential.account_key if hasattr(svc.credential, "account_key") else None

        sas = generate_blob_sas(
            account_name=account_name,
            container_name=self._container,
            blob_name=self._full_key(key),
            account_key=account_key,
            permission=BlobSasPermissions(read=True),
            expiry=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
        return f"https://{account_name}.blob.core.windows.net/{self._container}/{self._full_key(key)}?{sas}"

    async def list_keys(self, prefix: str = "") -> list[str]:
        full_prefix = self._full_key(prefix) if prefix else (self._prefix + "/" if self._prefix else "")
        keys: list[str] = []
        async with self._service_client() as svc:
            container = svc.get_container_client(self._container)
            async for blob in container.list_blobs(name_starts_with=full_prefix):
                raw = blob.name
                if self._prefix:
                    raw = raw.removeprefix(self._prefix + "/")
                keys.append(raw)
        return keys


class LocalStorageClient:
    """Local filesystem storage — useful for development and testing."""

    def __init__(self, base_dir: str | Path, base_url: str = "") -> None:
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._base_url = base_url.rstrip("/")

    def _path(self, key: str) -> Path:
        p = self._base / key.lstrip("/")
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    async def upload(
        self,
        key: str,
        data: bytes | BinaryIO | Path,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> UploadResult:
        body, size = _resolve_data(data)
        dest = self._path(key)

        if isinstance(body, bytes):
            dest.write_bytes(body)
            size = len(body)
        else:
            content = body.read() if hasattr(body, "read") else body
            dest.write_bytes(content if isinstance(content, bytes) else content.encode())
            size = dest.stat().st_size

        url = f"{self._base_url}/{key.lstrip('/')}" if self._base_url else None
        return UploadResult(key=key, url=url, size=size, content_type=content_type, metadata=metadata or {})

    async def download(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    async def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    async def exists(self, key: str) -> bool:
        return self._path(key).exists()

    async def get_url(self, key: str, expires_in: int = 3600) -> str:
        if self._base_url:
            return f"{self._base_url}/{key.lstrip('/')}"
        return str(self._path(key))

    async def list_keys(self, prefix: str = "") -> list[str]:
        search_root = self._base / prefix.lstrip("/") if prefix else self._base
        if not search_root.exists():
            return []
        return [
            str(p.relative_to(self._base))
            for p in search_root.rglob("*")
            if p.is_file()
        ]
