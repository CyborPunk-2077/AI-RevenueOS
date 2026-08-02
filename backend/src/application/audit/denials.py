"""Authenticated authorization denials are immutable security evidence."""

from __future__ import annotations

from typing import Any


async def audit_authorization_denial(request: Any, error: Any) -> None:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        return

    from application.audit.recorder import AuditRecorder
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    metadata = {
        "method": str(request.method),
        "path": str(request.url.path)[:500],
    }
    for field in ("required_permission", "operation", "step_up_required"):
        if field in error.details:
            metadata[field] = error.details[field]

    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        AuditRecorder(uow.session).record(
            action="authz.denied",
            resource_type="request",
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type=principal.actor_type,
            outcome="denied",
            metadata=metadata,
        )
