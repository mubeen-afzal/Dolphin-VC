import asyncio
import hashlib
import io
import uuid
from typing import Any, cast

import boto3  # type: ignore[import-untyped]

from app.config import Settings
from app.errors import AppError

PDF_MAGIC = b"%PDF-"
ZIP_MAGIC = b"PK\x03\x04"


def sniff_document_mime(data: bytes) -> str:
    if data.startswith(PDF_MAGIC):
        return "application/pdf"
    if data.startswith(ZIP_MAGIC):
        return "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    raise AppError(
        "UNSUPPORTED_MEDIA_TYPE",
        "Only PDF and PPTX documents are accepted.",
        status_code=415,
    )


class ObjectStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.local_root = settings.local_storage_path.resolve()
        self._client: Any = None
        if settings.storage_backend == "s3":
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint,
                aws_access_key_id=settings.s3_access_key,
                aws_secret_access_key=settings.s3_secret_key,
                region_name=settings.s3_region,
            )

    async def put(self, data: bytes, *, bucket: str, suffix: str = "") -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{digest[:2]}/{uuid.uuid4().hex}{suffix}"
        if self.settings.storage_backend == "local":
            target = (self.local_root / bucket / key).resolve()
            if self.local_root not in target.parents:
                raise RuntimeError("unsafe object path")
            target.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_bytes, data)
        else:
            assert self._client is not None
            await asyncio.to_thread(
                self._client.upload_fileobj,
                io.BytesIO(data),
                bucket,
                key,
            )
        return key, digest

    async def get(self, *, bucket: str, key: str) -> bytes:
        if self.settings.storage_backend == "local":
            target = (self.local_root / bucket / key).resolve()
            if self.local_root not in target.parents:
                raise RuntimeError("unsafe object path")
            return await asyncio.to_thread(target.read_bytes)
        assert self._client is not None

        def download() -> bytes:
            client = self._client
            result = client.get_object(Bucket=bucket, Key=key)
            return cast(bytes, result["Body"].read())

        return await asyncio.to_thread(download)

    async def ready(self) -> bool:
        if self.settings.storage_backend == "local":
            await asyncio.to_thread(self.local_root.mkdir, parents=True, exist_ok=True)
            return True
        assert self._client is not None
        try:
            await asyncio.to_thread(self._client.list_buckets)
            return True
        except Exception:
            return False


async def read_limited_upload(upload: object, max_mb: int) -> bytes:
    maximum = max_mb * 1024 * 1024
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(1024 * 1024)  # type: ignore[attr-defined]
        if not chunk:
            break
        total += len(chunk)
        if total > maximum:
            raise AppError(
                "MAX_BODY_EXCEEDED",
                f"Upload exceeds the {max_mb} MB limit.",
                status_code=413,
                details={"max_mb": max_mb},
            )
        chunks.append(chunk)
    return b"".join(chunks)
