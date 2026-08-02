"""Tenant-approved, time-bound support access with durable evidence."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from domain.auth.permissions import Scope
from domain.base import DomainEvent
from domain.events.catalog import SUPPORT_ACCESS_GRANTED, SUPPORT_ACCESS_REVOKED
from shared.exceptions import Forbidden, NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow


def _require_owner_scope(principal: Any) -> None:
    principal.require("support_access", "approve")
    if principal.scope is not Scope.GLOBAL:
        raise Forbidden("Support access approval requires organisation-wide scope.")


def _serialize(grant: Any) -> dict[str, Any]:
    active = (
        grant.approved_by is not None and grant.revoked_at is None and grant.expires_at > utcnow()
    )
    return {
        "id": str(grant.id),
        "support_user_ref": grant.support_user_ref,
        "tier": grant.tier,
        "purpose": grant.purpose,
        "requested_at": grant.requested_at.isoformat(),
        "approved_by": str(grant.approved_by) if grant.approved_by else None,
        "expires_at": grant.expires_at.isoformat(),
        "revoked_at": grant.revoked_at.isoformat() if grant.revoked_at else None,
        "active": active,
        "capabilities": ["read"],
    }


async def list_support_access(principal: Any) -> list[dict[str, Any]]:
    _require_owner_scope(principal)
    from infrastructure.database.models.users import SupportAccessGrant
    from infrastructure.database.session import tenant_session

    async with tenant_session(principal.tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(SupportAccessGrant)
                    .where(SupportAccessGrant.tenant_id == principal.tenant_id)
                    .order_by(SupportAccessGrant.requested_at.desc())
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        return [_serialize(row) for row in rows]


async def grant_support_access(
    principal: Any,
    *,
    support_user_ref: str,
    purpose: str,
    duration_minutes: int,
    idempotency_key: str | None,
) -> dict[str, Any]:
    """Approve read-only support access; write access is intentionally unavailable."""
    _require_owner_scope(principal)
    support_ref = support_user_ref.strip().lower()
    if not support_ref:
        raise ValidationError("A support user reference is required.")
    payload = {
        "support_user_ref": support_ref,
        "purpose": purpose.strip(),
        "duration_minutes": duration_minutes,
        "tier": "read",
    }

    from application.audit.recorder import AuditRecorder
    from application.idempotency import hash_payload, reserve_idempotency
    from infrastructure.database.models.users import SupportAccessGrant
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    grant_id = uuid7()
    now = utcnow()
    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope="support.access.grant",
            key=idempotency_key,
            request_hash=hash_payload(payload),
        )
        if reservation.replay is not None:
            return reservation.replay
        grant = SupportAccessGrant(
            id=grant_id,
            tenant_id=principal.tenant_id,
            support_user_ref=support_ref,
            tier="read",
            purpose=purpose.strip(),
            requested_at=now,
            approved_by=principal.user_id,
            second_approver=None,
            expires_at=now + timedelta(minutes=duration_minutes),
        )
        uow.session.add(grant)
        result = _serialize(grant)
        AuditRecorder(uow.session).record(
            action="support.access_granted",
            resource_type="support_access_grant",
            resource_id=grant_id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            new_values={
                "support_user_ref": support_ref,
                "tier": "read",
                "duration_minutes": duration_minutes,
            },
        )
        uow.collect(
            DomainEvent(
                event_type=SUPPORT_ACCESS_GRANTED,
                tenant_id=principal.tenant_id,
                resource_type="support_access_grant",
                resource_id=grant_id,
                actor_id=principal.user_id,
                payload={"support_user_ref": support_ref, "tier": "read"},
            )
        )
        reservation.complete(status=201, body=result)
    return result


async def revoke_support_access(
    principal: Any, *, grant_id: UUID, idempotency_key: str | None
) -> dict[str, Any]:
    _require_owner_scope(principal)
    from application.audit.recorder import AuditRecorder
    from application.idempotency import hash_payload, reserve_idempotency
    from infrastructure.database.models.users import SupportAccessGrant
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope=f"support.access.revoke:{grant_id}",
            key=idempotency_key,
            request_hash=hash_payload({"grant_id": str(grant_id)}),
        )
        if reservation.replay is not None:
            return reservation.replay
        grant = await uow.session.scalar(
            select(SupportAccessGrant)
            .where(
                SupportAccessGrant.id == grant_id,
                SupportAccessGrant.tenant_id == principal.tenant_id,
            )
            .with_for_update()
        )
        if grant is None:
            raise NotFound("Support access grant not found.")
        if grant.revoked_at is None:
            grant.revoked_at = utcnow()
            AuditRecorder(uow.session).record(
                action="support.access_revoked",
                resource_type="support_access_grant",
                resource_id=grant.id,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                old_values={"active": True},
                new_values={"active": False},
            )
            uow.collect(
                DomainEvent(
                    event_type=SUPPORT_ACCESS_REVOKED,
                    tenant_id=principal.tenant_id,
                    resource_type="support_access_grant",
                    resource_id=grant.id,
                    actor_id=principal.user_id,
                    payload={"support_user_ref": grant.support_user_ref},
                )
            )
        result = _serialize(grant)
        reservation.complete(status=200, body=result)
    return result


async def assert_active_support_grant(principal: Any) -> None:
    """Fail closed unless a matching, owner-approved grant is active."""
    from infrastructure.database.models.users import SupportAccessGrant
    from infrastructure.database.session import tenant_session

    refs = {str(principal.user_id).lower(), str(principal.email).strip().lower()}
    async with tenant_session(principal.tenant_id) as session:
        grant = await session.scalar(
            select(SupportAccessGrant.id).where(
                SupportAccessGrant.tenant_id == principal.tenant_id,
                SupportAccessGrant.support_user_ref.in_(refs),
                SupportAccessGrant.approved_by.is_not(None),
                SupportAccessGrant.revoked_at.is_(None),
                SupportAccessGrant.expires_at > utcnow(),
                SupportAccessGrant.tier == "read",
            )
        )
    if grant is None:
        raise Forbidden("No active tenant-approved support access grant exists.")
