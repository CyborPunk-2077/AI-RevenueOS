"""Onboarding persistence is isolated, idempotent and atomic in real PostgreSQL."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, text

from application.tenants.onboarding import (
    finish_onboarding,
    read_onboarding_state,
    update_onboarding_step,
)
from domain.auth.permissions import Role
from infrastructure.database.models.audit import AuditLog, EventOutbox, IdempotencyRecord
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.session import tenant_session
from shared.exceptions import Conflict, Forbidden

pytestmark = pytest.mark.postgres


async def _fresh_tenant(session_factory: Any, label: str) -> UUID:
    tenant_id = uuid4()
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                "INSERT INTO app.tenants (id, name, slug, plan_code, status, timezone, currency,"
                " locale, settings, branding, business_hours, holidays, billing_address,"
                " onboarding_state, version, created_at, updated_at) VALUES (:id, :name, :slug,"
                " 'starter', 'active', 'Asia/Kolkata', 'INR', 'en-IN', '{}', '{}', '{}', '[]',"
                " '{}', '{}', 1, now(), now())"
            ),
            {"id": tenant_id, "name": label, "slug": f"{label}-{tenant_id.hex[:10]}"},
        )
    return tenant_id


async def test_onboarding_updates_are_durable_idempotent_and_isolated(
    wired_engine: Any, session_factory: Any, principal_factory: Any
) -> None:
    tenant_a = await _fresh_tenant(session_factory, "onboarding-a")
    tenant_b = await _fresh_tenant(session_factory, "onboarding-b")
    admin_a = principal_factory(tenant_a, Role.ADMIN)
    key = f"onboarding-{uuid4().hex}"

    first = await update_onboarding_step(
        admin_a, step="welcome", status="completed", idempotency_key=key
    )
    replay = await update_onboarding_step(
        admin_a, step="welcome", status="completed", idempotency_key=key
    )
    assert replay == first
    assert first["steps"]["welcome"]["status"] == "completed"
    assert (await read_onboarding_state(principal_factory(tenant_b, Role.ADMIN)))["status"] == (
        "not_started"
    )

    async with tenant_session(tenant_a) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_a,
                    AuditLog.action == "tenant.onboarding_updated",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventOutbox)
                .where(
                    EventOutbox.tenant_id == tenant_a,
                    EventOutbox.event_type == "tenant.onboarding.updated",
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
                    IdempotencyRecord.scope == "tenant.onboarding.update",
                    IdempotencyRecord.idempotency_key == key,
                )
            )
            == 1
        )


async def test_onboarding_completion_requires_required_steps(
    wired_engine: Any, session_factory: Any, principal_factory: Any
) -> None:
    tenant_id = await _fresh_tenant(session_factory, "onboarding-complete")
    principal = principal_factory(tenant_id, Role.ADMIN)
    with pytest.raises(Conflict) as exc:
        await finish_onboarding(principal, idempotency_key=f"premature-{uuid4().hex}")
    assert exc.value.details["missing_steps"] == ["welcome", "tenant", "industry"]

    for step in ("welcome", "tenant", "industry"):
        await update_onboarding_step(
            principal, step=step, status="completed", idempotency_key=f"{step}-{uuid4().hex}"
        )
    completed = await finish_onboarding(principal, idempotency_key=f"complete-{uuid4().hex}")
    assert completed["status"] == "completed"
    assert completed["completed_at"]

    async with tenant_session(tenant_id) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.tenant_id == tenant_id,
                    AuditLog.action == "tenant.onboarding_completed",
                )
            )
            == 1
        )
        assert (
            await session.scalar(
                select(func.count())
                .select_from(EventOutbox)
                .where(
                    EventOutbox.tenant_id == tenant_id,
                    EventOutbox.event_type == "tenant.onboarding.completed",
                )
            )
            == 1
        )


async def test_onboarding_mutation_rolls_back_when_audit_fails(
    wired_engine: Any,
    session_factory: Any,
    principal_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _fresh_tenant(session_factory, "onboarding-rollback")
    principal = principal_factory(tenant_id, Role.ADMIN)

    def fail_audit(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("application.audit.recorder.AuditRecorder.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await update_onboarding_step(
            principal,
            step="welcome",
            status="completed",
            idempotency_key=f"rollback-{uuid4().hex}",
        )

    async with tenant_session(tenant_id) as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.id == tenant_id))
        assert tenant is not None
        assert tenant.onboarding_state == {}
        assert (
            await session.scalar(
                select(func.count())
                .select_from(IdempotencyRecord)
                .where(
                    IdempotencyRecord.tenant_id == tenant_id,
                    IdempotencyRecord.scope == "tenant.onboarding.update",
                )
            )
            == 0
        )


async def test_member_cannot_mutate_onboarding(
    wired_engine: Any, session_factory: Any, principal_factory: Any
) -> None:
    tenant_id = await _fresh_tenant(session_factory, "onboarding-member")
    member = principal_factory(tenant_id, Role.MEMBER)
    with pytest.raises(Forbidden):
        await update_onboarding_step(
            member,
            step="welcome",
            status="completed",
            idempotency_key=f"member-{uuid4().hex}",
        )
