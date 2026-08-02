"""Tenant-scoped onboarding state persistence and evidence."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from domain.base import DomainEvent
from domain.events.catalog import ONBOARDING_COMPLETED, ONBOARDING_UPDATED
from domain.tenants.onboarding import complete_onboarding, normalize_state, transition_step
from shared.exceptions import NotFound
from shared.utils.timeutil import utcnow


async def read_onboarding_state(principal: Any) -> dict[str, Any]:
    principal.require("tenant", "read")
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.database.session import tenant_session

    async with tenant_session(principal.tenant_id) as session:
        state = await session.scalar(
            select(Tenant.onboarding_state).where(Tenant.id == principal.tenant_id)
        )
    if state is None:
        raise NotFound("Tenant not found.")
    return normalize_state(state)


async def update_onboarding_step(
    principal: Any,
    *,
    step: str,
    status: str,
    idempotency_key: str | None,
) -> dict[str, Any]:
    principal.require("tenant", "configure")
    payload = {"step": step, "status": status}

    from application.audit.recorder import AuditRecorder
    from application.idempotency import hash_payload, reserve_idempotency
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope="tenant.onboarding.update",
            key=idempotency_key,
            request_hash=hash_payload(payload),
        )
        if reservation.replay is not None:
            return reservation.replay
        tenant = await uow.session.scalar(
            select(Tenant).where(Tenant.id == principal.tenant_id).with_for_update()
        )
        if tenant is None:
            raise NotFound("Tenant not found.")
        before = normalize_state(tenant.onboarding_state)
        after = transition_step(before, step_code=step, target_status=status, now=utcnow())
        if after != before:
            tenant.onboarding_state = after
            tenant.version += 1
            AuditRecorder(uow.session).record(
                action="tenant.onboarding_updated",
                resource_type="tenant",
                resource_id=tenant.id,
                tenant_id=tenant.id,
                actor_id=principal.user_id,
                old_values={"step": step, "status": before["steps"][step]["status"]},
                new_values={"step": step, "status": after["steps"][step]["status"]},
            )
            uow.collect(
                DomainEvent(
                    event_type=ONBOARDING_UPDATED,
                    tenant_id=tenant.id,
                    resource_type="tenant",
                    resource_id=tenant.id,
                    actor_id=principal.user_id,
                    payload={"step": step, "status": status},
                )
            )
        reservation.complete(status=200, body=after)
    return after


async def finish_onboarding(principal: Any, *, idempotency_key: str | None) -> dict[str, Any]:
    principal.require("tenant", "configure")

    from application.audit.recorder import AuditRecorder
    from application.idempotency import hash_payload, reserve_idempotency
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope="tenant.onboarding.complete",
            key=idempotency_key,
            request_hash=hash_payload({"complete": True}),
        )
        if reservation.replay is not None:
            return reservation.replay
        tenant = await uow.session.scalar(
            select(Tenant).where(Tenant.id == principal.tenant_id).with_for_update()
        )
        if tenant is None:
            raise NotFound("Tenant not found.")
        before = normalize_state(tenant.onboarding_state)
        after = complete_onboarding(before, now=utcnow())
        if after != before:
            tenant.onboarding_state = after
            tenant.version += 1
            AuditRecorder(uow.session).record(
                action="tenant.onboarding_completed",
                resource_type="tenant",
                resource_id=tenant.id,
                tenant_id=tenant.id,
                actor_id=principal.user_id,
                old_values={"status": before["status"]},
                new_values={"status": after["status"]},
            )
            uow.collect(
                DomainEvent(
                    event_type=ONBOARDING_COMPLETED,
                    tenant_id=tenant.id,
                    resource_type="tenant",
                    resource_id=tenant.id,
                    actor_id=principal.user_id,
                    payload={"status": "completed"},
                )
            )
        reservation.complete(status=200, body=after)
    return after
