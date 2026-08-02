"""Private upload inspection and malware-scan worker."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.base import airev_task


def build_scanner() -> Any:
    from infrastructure.integrations.storage import ClamAvScanner
    from shared.settings import get_settings

    cfg = get_settings()
    return ClamAvScanner(
        host=cfg.clamav_host,
        region=cfg.s3_region,
        endpoint_url=cfg.s3_endpoint_url,
    )


@airev_task("critical.scan_file", max_attempts=5)
async def scan_file(context: TaskContext, file_id: str) -> dict[str, Any]:
    return await _scan_file_once(context, file_id)


async def _scan_file_once(context: TaskContext, file_id: str) -> dict[str, Any]:
    tenant_id = context.require_tenant()
    from sqlalchemy import select

    from application.crm.documents import build_storage
    from infrastructure.database.models.documents import FileObject
    from infrastructure.database.session import tenant_session
    from infrastructure.integrations.storage import content_is_safe, verify_magic_bytes
    from shared.exceptions import ProviderUnavailable

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(select(FileObject).where(FileObject.id == UUID(file_id)))
        ).scalar_one_or_none()
        if row is None:
            return {"state": "missing"}
        if row.scan_status in {"clean", "quarantined", "rejected"}:
            return {"state": row.scan_status, "duplicate": True}
        if row.scan_status != "scanning":
            return {"state": row.scan_status, "queued": False}
        bucket, key = row.bucket, row.object_key
        declared_mime, expected_size = row.declared_mime or row.mime_type, row.size_bytes

    storage = build_storage()
    try:
        inspected = await storage.inspect_for_scan(bucket=bucket, key=key)
        sample = bytes(inspected["sample"])
        reason: str | None = None
        if int(inspected["size_bytes"]) != expected_size:
            reason = "object size changed after upload completion"
        elif not verify_magic_bytes(declared_mime, sample):
            reason = "magic bytes do not match the declared content type"
        else:
            safety = content_is_safe(declared_mime, sample)
            if not safety.ok:
                reason = safety.reason or "active content is not permitted"
    except Exception as exc:
        await _record_retry(
            tenant_id, UUID(file_id), f"object inspection failed: {type(exc).__name__}"
        )
        raise ProviderUnavailable("Stored object inspection is temporarily unavailable.") from exc

    if reason:
        return await _finalize(
            tenant_id=tenant_id,
            file_id=UUID(file_id),
            state="rejected",
            sha256=str(inspected["sha256"]),
            detail={"reason": reason},
            context=context,
        )

    verdict = await build_scanner().scan(bucket=bucket, key=key)
    if verdict.queued:
        await _record_retry(
            tenant_id,
            UUID(file_id),
            verdict.error_message or "malware scanner unavailable",
        )
        raise ProviderUnavailable(verdict.error_message or "Malware scanner unavailable.")
    state = "clean" if verdict.ok else "quarantined"
    return await _finalize(
        tenant_id=tenant_id,
        file_id=UUID(file_id),
        state=state,
        sha256=str(inspected["sha256"]),
        detail={
            "scanner": verdict.provider,
            "error_code": verdict.error_code,
            **dict(verdict.raw),
        },
        context=context,
    )


async def _record_retry(tenant_id: UUID, file_id: UUID, reason: str) -> None:
    from sqlalchemy import select

    from infrastructure.database.models.documents import FileObject
    from infrastructure.database.session import tenant_session

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(FileObject).where(FileObject.id == file_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is not None and row.scan_status == "scanning":
            row.scan_detail = {
                **dict(row.scan_detail or {}),
                "last_error": reason[:500],
            }


async def _finalize(
    *,
    tenant_id: UUID,
    file_id: UUID,
    state: str,
    sha256: str,
    detail: dict[str, Any],
    context: TaskContext,
) -> dict[str, Any]:
    from sqlalchemy import select

    from application.audit.recorder import AuditRecorder
    from domain.base import DomainEvent
    from domain.events.catalog import FILE_SCAN_COMPLETED
    from infrastructure.database.models.documents import FileObject
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
    from shared.utils.timeutil import utcnow

    async with SqlAlchemyUnitOfWork(tenant_id) as uow:
        row = (
            await uow.session.execute(
                select(FileObject).where(FileObject.id == file_id).with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            return {"state": "missing"}
        if row.scan_status in {"clean", "quarantined", "rejected"}:
            return {"state": row.scan_status, "duplicate": True}
        row.scan_status = state
        row.sha256 = sha256
        row.scanned_at = utcnow()
        row.scan_detail = {**dict(row.scan_detail or {}), **detail}
        AuditRecorder(uow.session).record(
            action="file.scan_completed",
            resource_type="file",
            resource_id=file_id,
            tenant_id=tenant_id,
            actor_id=context.actor_id,
            actor_type="worker",
            outcome="success" if state == "clean" else state,
            new_values={"scan_status": state, "sha256": sha256},
        )
        uow.collect(
            DomainEvent(
                event_type=FILE_SCAN_COMPLETED,
                tenant_id=tenant_id,
                resource_type="file",
                resource_id=file_id,
                actor_id=context.actor_id,
                actor_type="worker",
                correlation_id=context.correlation_id,
                payload={"scan_status": state},
            )
        )
    return {"state": state, "sha256": sha256}
