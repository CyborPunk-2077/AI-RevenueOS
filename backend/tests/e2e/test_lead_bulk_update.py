"""Atomic, durably idempotent lead bulk operations under RLS and role scope."""

from __future__ import annotations

from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from application.leads.service import LeadService
from domain.auth.permissions import Role, Scope
from infrastructure.caching.redis import get_redis
from infrastructure.database.models.audit import AuditLog, EventOutbox, IdempotencyRecord
from infrastructure.database.models.leads import Lead
from infrastructure.database.session import tenant_session
from shared.exceptions import NotFound

pytestmark = pytest.mark.postgres


async def _lead(service: LeadService, name: str) -> dict[str, Any]:
    return await service.capture(
        {
            "first_name": name,
            "email": f"{name.lower()}-{uuid4().hex}@example.invalid",
            "source": "manual",
        }
    )


async def test_bulk_update_is_atomic_audited_and_survives_redis_loss(
    wired_engine: Any, seeded_tenants: Any, principal_factory: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    principal = principal_factory(tenant_a, Role.ADMIN)
    service = LeadService.for_principal(principal)
    first = await _lead(service, "BulkA")
    second = await _lead(service, "BulkB")
    lead_ids = [UUID(first["id"]), UUID(second["id"])]
    key = f"bulk-{uuid4().hex}"

    result = await service.bulk_update(lead_ids, {"status": "contacted"}, idempotency_key=key)
    await get_redis().flushall()
    replay = await service.bulk_update(
        list(reversed(lead_ids)), {"status": "contacted"}, idempotency_key=key
    )
    assert replay == result
    assert result["requested_count"] == 2
    assert result["changed_count"] == 2
    assert result["changed_fields"] == ["status"]

    operation_id = UUID(result["operation_id"])
    async with tenant_session(tenant_a) as session:
        rows = (
            (await session.execute(select(Lead).where(Lead.id.in_(lead_ids)).order_by(Lead.id)))
            .scalars()
            .all()
        )
        assert [row.status for row in rows] == ["contacted", "contacted"]
        assert [row.version for row in rows] == [2, 2]
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.resource_id == operation_id,
                    AuditLog.action == "bulk.operation",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventOutbox)
                .where(
                    EventOutbox.resource_id == operation_id,
                    EventOutbox.event_type == "bulk.operation.completed",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(
                    IdempotencyRecord.tenant_id == tenant_a,
                    IdempotencyRecord.scope == "lead.bulk.update",
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            == 1
        )

    async with tenant_session(tenant_b) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.resource_id == operation_id)
            )
            == 0
        )


async def test_bulk_update_fails_closed_for_cross_tenant_and_self_scope(
    wired_engine: Any, seeded_tenants: Any, principal_factory: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    principal_a = principal_factory(tenant_a, Role.ADMIN)
    principal_b = principal_factory(tenant_b, Role.ADMIN)
    own = await _lead(LeadService.for_principal(principal_a), "ScopedOwn")
    other_tenant = await _lead(LeadService.for_principal(principal_b), "ScopedOtherTenant")

    with pytest.raises(NotFound):
        await LeadService.for_principal(principal_a).bulk_update(
            [UUID(own["id"]), UUID(other_tenant["id"])],
            {"status": "contacted"},
            idempotency_key=f"cross-{uuid4().hex}",
        )
    async with tenant_session(tenant_a) as session:
        assert await session.scalar(select(Lead.status).where(Lead.id == UUID(own["id"]))) == "new"

    different_actor = principal_factory(tenant_a, Role.ADMIN)
    inaccessible = await _lead(LeadService.for_principal(different_actor), "ScopedOtherActor")
    self_scoped = replace(principal_a, scope=Scope.SELF)
    with pytest.raises(NotFound):
        await LeadService.for_principal(self_scoped).bulk_update(
            [UUID(own["id"]), UUID(inaccessible["id"])],
            {"status": "contacted"},
            idempotency_key=f"self-{uuid4().hex}",
        )
    async with tenant_session(tenant_a) as session:
        assert await session.scalar(select(Lead.status).where(Lead.id == UUID(own["id"]))) == "new"


async def test_bulk_update_rolls_back_state_idempotency_and_outbox_when_audit_fails(
    wired_engine: Any,
    seeded_tenants: Any,
    principal_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a, _ = seeded_tenants
    principal = principal_factory(tenant_a, Role.ADMIN)
    lead = await _lead(LeadService.for_principal(principal), "BulkRollback")
    lead_id = UUID(lead["id"])
    key = f"rollback-{uuid4().hex}"

    def fail_audit(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("application.audit.recorder.AuditRecorder.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await LeadService.for_principal(principal).bulk_update(
            [lead_id], {"status": "contacted"}, idempotency_key=key
        )

    async with tenant_session(tenant_a) as session:
        row = await session.scalar(select(Lead).where(Lead.id == lead_id))
        assert row is not None and row.status == "new" and row.version == 1
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(
                    IdempotencyRecord.tenant_id == tenant_a,
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            == 0
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventOutbox)
                .where(
                    EventOutbox.resource_id == lead_id,
                    EventOutbox.event_type == "lead.updated",
                )
            )
            == 0
        )
