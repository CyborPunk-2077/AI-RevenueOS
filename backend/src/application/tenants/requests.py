"""Durable tenant export and deletion requests with audit and outbox evidence."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID

from domain.base import DomainEvent
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow


async def request_tenant_export(*, tenant_id: UUID, actor_id: UUID) -> dict[str, Any]:
    """Record the request without claiming that unavailable storage delivered a file."""
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.audit import PrivacyRequest
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    request_id = uuid7()
    created_at = utcnow()
    async with SqlAlchemyUnitOfWork(tenant_id) as uow:
        uow.session.add(
            PrivacyRequest(
                id=request_id,
                tenant_id=tenant_id,
                subject_identifier=str(tenant_id),
                subject_type="tenant",
                request_type="export",
                status="received",
                verification={"step_up_verified": True},
                due_at=created_at + timedelta(days=30),
                created_at=created_at,
                requested_by=actor_id,
            )
        )
        AuditRecorder(uow.session).record(
            action="privacy.request",
            resource_type="privacy_request",
            resource_id=request_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"request_type": "export", "status": "received"},
        )
        uow.collect(
            DomainEvent(
                event_type="privacy.requested",
                tenant_id=tenant_id,
                resource_type="privacy_request",
                resource_id=request_id,
                actor_id=actor_id,
                payload={"request_type": "export", "status": "received"},
            )
        )
    return {
        "request_id": str(request_id),
        "status": "received",
        "delivery": "pending_private_storage_activation",
        "due_at": (created_at + timedelta(days=30)).isoformat(),
        "download_available": False,
    }


async def request_tenant_deletion(*, tenant_id: UUID, actor_id: UUID) -> dict[str, Any]:
    """Persist the delayed request; no tenant data is deleted synchronously."""
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.audit import PrivacyRequest
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    request_id = uuid7()
    created_at = utcnow()
    due_at = created_at + timedelta(days=90)
    async with SqlAlchemyUnitOfWork(tenant_id) as uow:
        uow.session.add(
            PrivacyRequest(
                id=request_id,
                tenant_id=tenant_id,
                subject_identifier=str(tenant_id),
                subject_type="tenant",
                request_type="delete",
                status="received",
                verification={"step_up_verified": True, "retention_days": 90},
                due_at=due_at,
                created_at=created_at,
                requested_by=actor_id,
            )
        )
        recorder = AuditRecorder(uow.session)
        recorder.record(
            action="privacy.request",
            resource_type="privacy_request",
            resource_id=request_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"request_type": "delete", "status": "received"},
        )
        recorder.record(
            action="tenant.delete_requested",
            resource_type="tenant",
            resource_id=tenant_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"request_id": str(request_id), "retention_days": 90},
        )
        uow.collect(
            DomainEvent(
                event_type="tenant.delete_requested",
                tenant_id=tenant_id,
                resource_type="tenant",
                resource_id=tenant_id,
                actor_id=actor_id,
                payload={"request_id": str(request_id), "retention_days": 90},
            )
        )
    return {
        "request_id": str(request_id),
        "status": "received",
        "retention_days": 90,
        "due_at": due_at.isoformat(),
        "note": "Deletion remains delayed by the retention policy.",
    }
