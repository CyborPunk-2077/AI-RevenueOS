"""Upload completion and scan-state transitions on real PostgreSQL."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from application.crm.documents import DocumentService
from domain.auth.permissions import Scope
from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.files import _scan_file_once
from infrastructure.database.models.audit import AuditLog, EventOutbox
from infrastructure.database.models.documents import FileObject
from infrastructure.database.session import tenant_session
from shared.exceptions import ProviderUnavailable
from shared.utils.ids import uuid7


class FakeStorage:
    def __init__(self, content: bytes) -> None:
        self.content = content

    async def head(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ContentLength": len(self.content),
            "ContentType": "application/pdf",
            "ServerSideEncryption": "aws:kms",
            "ETag": '"etag"',
        }

    async def inspect_for_scan(self, **_kwargs: Any) -> dict[str, Any]:
        import hashlib

        return {
            "size_bytes": len(self.content),
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "sample": self.content,
        }

    async def presign_download(self, **_kwargs: Any) -> str:
        return "https://signed.example.test/private"


class FakeScanner:
    def __init__(self, *, clean: bool = True, unavailable: bool = False) -> None:
        self.clean = clean
        self.unavailable = unavailable

    async def scan(self, **_kwargs: Any) -> Any:
        from application.ports import ProviderResult

        if self.unavailable:
            return ProviderResult(
                False,
                "clamav",
                "scan",
                queued=True,
                error_code="SCANNER_UNAVAILABLE",
                error_message="scanner unavailable",
            )
        return ProviderResult(
            self.clean,
            "clamav",
            "scan",
            error_code=None if self.clean else "MALWARE_FOUND",
            raw={} if self.clean else {"signature": "Eicar-Test-Signature"},
        )


async def _file(tenant_id: Any, content: bytes) -> Any:
    file_id, owner_id = uuid7(), uuid7()
    async with tenant_session(tenant_id) as session:
        session.add(
            FileObject(
                id=file_id,
                tenant_id=tenant_id,
                owner_id=owner_id,
                object_key=f"tenants/{tenant_id}/uploads/{file_id}.pdf",
                bucket="real-private-bucket",
                name=f"scan-{uuid4().hex}.pdf",
                size_bytes=len(content),
                mime_type="application/pdf",
                declared_mime="application/pdf",
                scan_status="pending",
                scan_detail={},
                classification="P2",
            )
        )
    return file_id, owner_id


@pytest.mark.postgres
async def test_completion_scan_and_download_evidence_are_atomic(
    wired_engine: Any, seeded_tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_a, tenant_b = seeded_tenants
    content = b"%PDF-1.7 safe content"
    file_id, owner_id = await _file(tenant_a, content)
    storage = FakeStorage(content)
    service = DocumentService(
        tenant_id=tenant_a,
        user_id=owner_id,
        permissions=frozenset({"file:read", "file:create"}),
        scope=Scope.GLOBAL,
    )
    monkeypatch.setattr(DocumentService, "storage_status", lambda _self: {"configured": True})
    monkeypatch.setattr("application.crm.documents.build_storage", lambda: storage)

    completed = await service.complete_upload(file_id)
    duplicate = await service.complete_upload(file_id)
    assert completed["scan_status"] == "scanning" and completed["duplicate"] is False
    assert duplicate["duplicate"] is True

    monkeypatch.setattr("infrastructure.celery.tasks.files.build_scanner", lambda: FakeScanner())
    result = await _scan_file_once(
        TaskContext(tenant_a, "file-scan-test", owner_id, "worker"), str(file_id)
    )
    assert result["state"] == "clean"
    assert (await service.download_url(file_id))["url"].startswith("https://signed.example.test/")
    assert (
        await _scan_file_once(
            TaskContext(tenant_a, "file-scan-test", owner_id, "worker"), str(file_id)
        )
    )["duplicate"] is True
    assert (
        await _scan_file_once(
            TaskContext(tenant_b, "cross-tenant", owner_id, "worker"), str(file_id)
        )
    )["state"] == "missing"

    async with tenant_session(tenant_a) as session:
        row = await session.get(FileObject, file_id)
        assert row is not None and row.sha256 and row.scan_status == "clean"
        actions = set(
            (
                await session.execute(
                    select(AuditLog.action).where(AuditLog.resource_id == file_id)
                )
            ).scalars()
        )
        events = set(
            (
                await session.execute(
                    select(EventOutbox.event_type).where(EventOutbox.resource_id == file_id)
                )
            ).scalars()
        )
        assert {"file.upload_completed", "file.scan_completed", "file.downloaded"} <= actions
        assert {"file.upload_completed", "file.scan_completed"} <= events


@pytest.mark.postgres
async def test_malware_quarantines_and_scanner_failure_never_marks_clean(
    wired_engine: Any, seeded_tenants: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_a, _ = seeded_tenants
    content = b"%PDF-1.7 sample"
    infected_id, owner_id = await _file(tenant_a, content)
    unavailable_id, _ = await _file(tenant_a, content)
    async with tenant_session(tenant_a) as session:
        for file_id in (infected_id, unavailable_id):
            row = await session.get(FileObject, file_id)
            assert row is not None
            row.scan_status = "scanning"
            row.scan_detail = {"uploaded": True}
    monkeypatch.setattr("application.crm.documents.build_storage", lambda: FakeStorage(content))
    monkeypatch.setattr(
        "infrastructure.celery.tasks.files.build_scanner", lambda: FakeScanner(clean=False)
    )
    infected = await _scan_file_once(
        TaskContext(tenant_a, "infected", owner_id, "worker"), str(infected_id)
    )
    assert infected["state"] == "quarantined"

    monkeypatch.setattr(
        "infrastructure.celery.tasks.files.build_scanner",
        lambda: FakeScanner(unavailable=True),
    )
    with pytest.raises(ProviderUnavailable):
        await _scan_file_once(
            TaskContext(tenant_a, "unavailable", owner_id, "worker"), str(unavailable_id)
        )
    async with tenant_session(tenant_a) as session:
        unavailable = await session.get(FileObject, unavailable_id)
        assert unavailable is not None and unavailable.scan_status == "scanning"
        assert "scanner unavailable" in unavailable.scan_detail["last_error"]
