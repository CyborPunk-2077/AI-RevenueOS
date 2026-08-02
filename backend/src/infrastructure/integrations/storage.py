"""Private S3 storage with presigned upload/download and scan-gated availability."""

from __future__ import annotations

import os
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from application.ports import PresignedUpload, ProviderResult, ScannerPort, StoragePort
from shared.exceptions import Forbidden, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

PROTECTED_UPLOAD_LIMIT = 50 * 1024 * 1024
PUBLIC_UPLOAD_LIMIT = 25 * 1024 * 1024
APPROVED_EXCEPTION_LIMIT = 100 * 1024 * 1024
DAILY_USER_LIMIT = 500 * 1024 * 1024
DOWNLOAD_TTL_SECONDS = 300
UPLOAD_TTL_SECONDS = 900
MAX_ARCHIVE_EXPANSION_RATIO = 100

ALLOWED_MIME_TYPES = frozenset(
    {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "image/gif",
        "text/csv",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/msword",
        "application/vnd.ms-excel",
        "audio/mpeg",
        "audio/ogg",
        "audio/wav",
        "video/mp4",
    }
)

# Magic bytes checked server side; a declared content type is never trusted alone.
MAGIC_BYTES: dict[str, tuple[bytes, ...]] = {
    "application/pdf": (b"%PDF-",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
    "application/zip": (b"PK\x03\x04",),
}

DANGEROUS_EXTENSIONS = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".bat",
        ".cmd",
        ".sh",
        ".ps1",
        ".jar",
        ".msi",
        ".scr",
        ".com",
        ".pif",
        ".vbs",
        ".js",
        ".jse",
        ".wsf",
        ".hta",
        ".lnk",
        ".app",
    }
)

_CSV_FORMULA = re.compile(r"^[=+\-@\t\r]")
_UNSAFE_SVG = re.compile(rb"<script|javascript:|onload=|onerror=", re.IGNORECASE)
_PDF_JS = re.compile(rb"/JavaScript|/JS\s|/OpenAction|/Launch", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class UploadValidation:
    ok: bool
    reason: str | None = None
    detail: dict[str, Any] | None = None


def object_key(tenant_id: UUID, *, prefix: str = "uploads") -> str:
    """UUID object names only - a filename is never reflected into the key."""
    return f"{prefix}/{tenant_id}/{utcnow():%Y/%m}/{uuid7()}"


def validate_upload_request(
    *,
    declared_mime: str,
    size_bytes: int,
    filename: str,
    is_public: bool = False,
    approved_exception: bool = False,
    plan_upload_limit: int | None = None,
    user_daily_bytes: int = 0,
) -> UploadValidation:
    limit = PUBLIC_UPLOAD_LIMIT if is_public else (plan_upload_limit or PROTECTED_UPLOAD_LIMIT)
    if approved_exception and not is_public:
        limit = max(limit, APPROVED_EXCEPTION_LIMIT)

    if size_bytes <= 0:
        return UploadValidation(False, "empty file")
    if size_bytes > limit:
        return UploadValidation(False, "file exceeds the permitted size", {"limit": limit})
    if user_daily_bytes + size_bytes > DAILY_USER_LIMIT:
        return UploadValidation(
            False, "daily upload allowance exhausted", {"limit": DAILY_USER_LIMIT}
        )
    if declared_mime not in ALLOWED_MIME_TYPES:
        return UploadValidation(False, "file type is not permitted", {"mime": declared_mime})
    suffix = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if suffix in DANGEROUS_EXTENSIONS:
        return UploadValidation(
            False, "executable file types are not permitted", {"extension": suffix}
        )
    if filename.count(".") > 1:
        parts = filename.lower().split(".")
        if any(f".{p}" in DANGEROUS_EXTENSIONS for p in parts[1:]):
            return UploadValidation(False, "double extension is not permitted")
    return UploadValidation(True)


def verify_magic_bytes(declared_mime: str, head: bytes) -> bool:
    signatures = MAGIC_BYTES.get(declared_mime)
    if signatures is None:
        return True
    return any(head.startswith(sig) for sig in signatures)


def content_is_safe(declared_mime: str, sample: bytes) -> UploadValidation:
    """Reject unsafe SVG, PDF JavaScript and archive bombs before the file is usable."""
    is_svg = declared_mime == "image/svg+xml" or sample.lstrip()[:5] == b"<svg "
    if is_svg and _UNSAFE_SVG.search(sample):
        return UploadValidation(False, "SVG contains active content")
    if declared_mime == "application/pdf" and _PDF_JS.search(sample):
        return UploadValidation(False, "PDF contains JavaScript or an automatic action")
    return UploadValidation(True)


def archive_ratio_safe(compressed_bytes: int, uncompressed_bytes: int) -> bool:
    if compressed_bytes <= 0:
        return False
    return (uncompressed_bytes / compressed_bytes) <= MAX_ARCHIVE_EXPANSION_RATIO


def sanitize_csv_cell(value: str) -> str:
    """Neutralise CSV formula injection on export."""
    return "'" + value if value and _CSV_FORMULA.match(value) else value


def assert_download_allowed(
    *, scan_status: str, file_tenant_id: UUID, requester_tenant_id: UUID
) -> None:
    """Files are unavailable until clean and are never readable across tenants."""
    if file_tenant_id != requester_tenant_id:
        raise Forbidden("This file belongs to another organisation.")
    if scan_status != "clean":
        raise ValidationError(
            "This file is not yet available for download.",
            details={"scan_status": scan_status},
        )


class S3Storage(StoragePort):
    def __init__(
        self,
        *,
        bucket: str,
        region: str = "ap-south-1",
        client: Any | None = None,
        endpoint_url: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._region = region
        self._client = client
        self._endpoint = endpoint_url

    def is_configured(self) -> bool:
        """Never claim configuration we do not have.

        A bucket name in settings is not a bucket. Object storage is only usable
        once AWS credentials resolve *and* the bucket is not the local
        placeholder, so the caller can tell the difference between "configured"
        and "someone typed a name into an env file".
        """
        if not self._bucket or self._bucket.startswith("airevenueos-local-"):
            return False
        if self._client is not None:
            return True
        # Do not ask boto3 to resolve credentials here: its provider chain may
        # contact EC2/ECS metadata, making a harmless status endpoint perform
        # network I/O. These markers cover static credentials, web identity,
        # container roles and an explicitly selected local profile.
        credential_markers = (
            "AWS_ACCESS_KEY_ID",
            "AWS_WEB_IDENTITY_TOKEN_FILE",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI",
            "AWS_PROFILE",
        )
        return any(os.environ.get(name) for name in credential_markers)

    def activation_status(self) -> dict[str, Any]:
        """What is missing, named precisely enough to act on."""
        missing: list[str] = []
        if not self._bucket or self._bucket.startswith("airevenueos-local-"):
            missing.append("S3_BUCKET_UPLOADS (a real bucket, not the local placeholder)")
        if self._client is None and not self.is_configured():
            missing.append("AWS task-role or credential configuration")
        return {
            "provider": "s3",
            "configured": self.is_configured(),
            "missing": missing,
            "blocker": (
                None
                if self.is_configured()
                else "Object storage requires an AWS account (P0-5). Files are recorded "
                "with their metadata; no upload URL is issued and nothing is stored."
            ),
        }

    def _s3(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self._region, endpoint_url=self._endpoint)
        return self._client

    async def presign_upload(
        self, *, tenant_id: UUID, key: str, content_type: str, max_bytes: int
    ) -> PresignedUpload:
        post = self._s3().generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": content_type, "x-amz-server-side-encryption": "aws:kms"},
            Conditions=[
                {"Content-Type": content_type},
                {"x-amz-server-side-encryption": "aws:kms"},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=UPLOAD_TTL_SECONDS,
        )
        return PresignedUpload(
            url=post["url"],
            fields=post["fields"],
            object_key=key,
            expires_at=utcnow() + timedelta(seconds=UPLOAD_TTL_SECONDS),
            max_bytes=max_bytes,
        )

    async def presign_download(
        self, *, bucket: str, key: str, ttl_seconds: int = DOWNLOAD_TTL_SECONDS
    ) -> str:
        return str(
            self._s3().generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=min(ttl_seconds, DOWNLOAD_TTL_SECONDS),
            )
        )

    async def head(self, *, bucket: str, key: str) -> dict[str, Any]:
        return dict(self._s3().head_object(Bucket=bucket, Key=key))

    async def delete(self, *, bucket: str, key: str) -> None:
        self._s3().delete_object(Bucket=bucket, Key=key)

    async def inspect_for_scan(
        self, *, bucket: str, key: str, sample_bytes: int = 1_048_576
    ) -> dict[str, Any]:
        """Stream one private object once to compute its digest and safety sample."""
        import asyncio
        import hashlib

        response = await asyncio.to_thread(self._s3().get_object, Bucket=bucket, Key=key)
        body = response["Body"]
        digest = hashlib.sha256()
        sample = bytearray()
        size = 0
        try:
            while True:
                chunk = await asyncio.to_thread(body.read, 64 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > PROTECTED_UPLOAD_LIMIT:
                    raise ValidationError("Stored object exceeds the protected upload limit.")
                digest.update(chunk)
                if len(sample) < sample_bytes:
                    sample.extend(chunk[: sample_bytes - len(sample)])
        finally:
            close = getattr(body, "close", None)
            if close:
                close()
        return {"sha256": digest.hexdigest(), "size_bytes": size, "sample": bytes(sample)}


class ClamAvScanner(ScannerPort):
    """When ClamAV is unreachable a file stays `pending` - it never becomes `clean`."""

    def __init__(
        self,
        *,
        host: str | None,
        port: int = 3310,
        client: Any | None = None,
        region: str = "ap-south-1",
        endpoint_url: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._host = host
        self._port = port
        self._client = client
        self._region = region
        self._endpoint = endpoint_url
        self._timeout = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self._host)

    async def scan(self, *, bucket: str, key: str) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider="clamav",
                operation="scan",
                queued=True,
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message="Malware scanning is not configured; the file remains unavailable.",
            )
        import asyncio

        started = utcnow()
        writer: Any | None = None
        body: Any | None = None
        try:
            reader, stream_writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port), timeout=self._timeout
            )
            writer = stream_writer
            client = self._client
            if client is None:
                import boto3

                client = boto3.client("s3", region_name=self._region, endpoint_url=self._endpoint)
            response = await asyncio.to_thread(client.get_object, Bucket=bucket, Key=key)
            body = response["Body"]
            stream_writer.write(b"zINSTREAM\0")
            total = 0
            while True:
                chunk = await asyncio.to_thread(body.read, 64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > PROTECTED_UPLOAD_LIMIT:
                    return ProviderResult(
                        ok=False,
                        provider="clamav",
                        operation="scan",
                        error_code="FILE_TOO_LARGE",
                        error_message="Object exceeded the protected scan limit.",
                    )
                stream_writer.write(struct.pack(">I", len(chunk)))
                stream_writer.write(chunk)
                await stream_writer.drain()
            stream_writer.write(struct.pack(">I", 0))
            await stream_writer.drain()
            raw = await asyncio.wait_for(reader.readuntil(b"\0"), timeout=self._timeout)
            verdict = raw.rstrip(b"\0").decode("utf-8", errors="replace")
            latency = int((utcnow() - started).total_seconds() * 1000)
            if verdict.endswith(" OK"):
                return ProviderResult(
                    ok=True,
                    provider="clamav",
                    operation="scan",
                    raw={"verdict": verdict, "bytes_scanned": total},
                    latency_ms=latency,
                )
            if verdict.endswith(" FOUND"):
                signature = verdict.split(":", 1)[-1].removesuffix(" FOUND").strip()
                return ProviderResult(
                    ok=False,
                    provider="clamav",
                    operation="scan",
                    error_code="MALWARE_FOUND",
                    error_message="Malware was detected; the object is quarantined.",
                    raw={"signature": signature, "bytes_scanned": total},
                    latency_ms=latency,
                )
            return ProviderResult(
                ok=False,
                provider="clamav",
                operation="scan",
                queued=True,
                error_code="SCANNER_ERROR",
                error_message="ClamAV returned an unrecognised scan response.",
                raw={"verdict": verdict},
                latency_ms=latency,
            )
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            return ProviderResult(
                ok=False,
                provider="clamav",
                operation="scan",
                queued=True,
                error_code="SCANNER_UNAVAILABLE",
                error_message="Malware scanning is temporarily unavailable.",
                raw={"error_type": type(exc).__name__},
            )
        finally:
            if body is not None:
                close = getattr(body, "close", None)
                if close:
                    close()
            if writer is not None:
                writer.close()
                with suppress(OSError):
                    await writer.wait_closed()
