"""Tenant-approved support access is durable, isolated and fail-closed."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from application.support.service import (
    assert_active_support_grant,
    grant_support_access,
    list_support_access,
    revoke_support_access,
)
from domain.auth.permissions import Role
from infrastructure.database.models.audit import AuditLog, EventOutbox, IdempotencyRecord
from infrastructure.database.models.users import SupportAccessGrant
from infrastructure.database.session import tenant_session
from shared.exceptions import Forbidden, IdempotencyConflict

pytestmark = pytest.mark.postgres


def _support_principal(tenant_id: UUID, ref: str) -> Any:
    return SimpleNamespace(tenant_id=tenant_id, user_id=uuid4(), email=ref)


async def test_support_grant_is_durable_idempotent_and_tenant_isolated(
    wired_engine: Any, seeded_tenants: Any, principal_factory: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    owner = principal_factory(tenant_a, Role.OWNER)
    support_ref = f"support-{uuid4().hex}@example.invalid"
    payload = {
        "support_user_ref": support_ref,
        "purpose": "Investigate ticket REV-1042 without write access",
        "duration_minutes": 15,
        "idempotency_key": f"grant-{uuid4().hex}",
    }

    first = await grant_support_access(owner, **payload)
    replay = await grant_support_access(owner, **payload)
    assert replay == first
    assert first["active"] is True
    assert first["capabilities"] == ["read"]

    await assert_active_support_grant(_support_principal(tenant_a, support_ref))
    with pytest.raises(Forbidden):
        await assert_active_support_grant(_support_principal(tenant_b, support_ref))
    assert all(
        row["id"] != first["id"]
        for row in await list_support_access(principal_factory(tenant_b, Role.OWNER))
    )

    async with tenant_session(tenant_a) as session:
        grant_id = UUID(first["id"])
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SupportAccessGrant)
                .where(SupportAccessGrant.id == grant_id)
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.resource_id == grant_id,
                    AuditLog.action == "support.access_granted",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventOutbox)
                .where(
                    EventOutbox.resource_id == grant_id,
                    EventOutbox.event_type == "support.access_granted",
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
                    IdempotencyRecord.scope == "support.access.grant",
                    IdempotencyRecord.idempotency_key == payload["idempotency_key"],
                )
            )
            == 1
        )

    with pytest.raises(IdempotencyConflict):
        await grant_support_access(
            owner,
            support_user_ref=support_ref,
            purpose="A different support purpose must conflict",
            duration_minutes=15,
            idempotency_key=payload["idempotency_key"],
        )


async def test_support_revocation_is_atomic_and_immediate(
    wired_engine: Any, seeded_tenants: Any, principal_factory: Any
) -> None:
    tenant_a, _ = seeded_tenants
    owner = principal_factory(tenant_a, Role.OWNER)
    support_ref = f"support-{uuid4().hex}@example.invalid"
    grant = await grant_support_access(
        owner,
        support_user_ref=support_ref,
        purpose="Investigate ticket REV-1043 without write access",
        duration_minutes=10,
        idempotency_key=f"grant-{uuid4().hex}",
    )
    revoked = await revoke_support_access(
        owner,
        grant_id=UUID(grant["id"]),
        idempotency_key=f"revoke-{uuid4().hex}",
    )
    assert revoked["active"] is False
    with pytest.raises(Forbidden):
        await assert_active_support_grant(_support_principal(tenant_a, support_ref))

    async with tenant_session(tenant_a) as session:
        grant_id = UUID(grant["id"])
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.resource_id == grant_id,
                    AuditLog.action == "support.access_revoked",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventOutbox)
                .where(
                    EventOutbox.resource_id == grant_id,
                    EventOutbox.event_type == "support.access_revoked",
                )
            )
            == 1
        )


async def test_support_grant_rolls_back_when_audit_fails(
    wired_engine: Any,
    seeded_tenants: Any,
    principal_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a, _ = seeded_tenants
    owner = principal_factory(tenant_a, Role.OWNER)
    support_ref = f"rollback-{uuid4().hex}@example.invalid"

    def fail_audit(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("application.audit.recorder.AuditRecorder.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await grant_support_access(
            owner,
            support_user_ref=support_ref,
            purpose="Verify transaction rollback for support approval",
            duration_minutes=10,
            idempotency_key=f"rollback-{uuid4().hex}",
        )

    async with tenant_session(tenant_a) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(SupportAccessGrant)
                .where(SupportAccessGrant.support_user_ref == support_ref)
            )
            == 0
        )
