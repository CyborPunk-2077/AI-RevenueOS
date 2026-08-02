"""Audit recorder. Material events reconstruct actor, action, resource and context."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.audit import AuditLog
from infrastructure.logging.context import current_context
from infrastructure.logging.redaction import redact
from shared.utils.timeutil import utcnow

# Actions that must always be audited regardless of outcome.
MANDATORY_AUDIT_ACTIONS = frozenset(
    {
        "auth.login",
        "auth.login_failed",
        "auth.logout",
        "auth.refresh",
        "auth.refresh_reuse",
        "auth.password_reset",
        "auth.mfa_enabled",
        "auth.mfa_disabled",
        "auth.session_revoked",
        "authz.denied",
        "user.created",
        "user.deactivated",
        "role.updated",
        "tenant.updated",
        "tenant.ownership_transferred",
        "tenant.delete_requested",
        "payment.order_created",
        "payment.captured",
        "payment.refunded",
        "workflow.published",
        "workflow.killed",
        "workflow.executed",
        "ai.task",
        "ai.guard_block",
        "consent.granted",
        "consent.revoked",
        "config.updated",
        "provider.configured",
        "secret.accessed",
        "support.access_granted",
        "support.access_revoked",
        "export.created",
        "export.downloaded",
        "privacy.request",
        "file.downloaded",
        "message.sent",
        "bulk.operation",
    }
)


class AuditRecorder:
    """Writes to the immutable, monthly-partitioned audit log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def record(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: UUID | None = None,
        tenant_id: UUID | None = None,
        actor_id: UUID | None = None,
        actor_type: str = "user",
        actor_label: str | None = None,
        outcome: str = "success",
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        ctx = current_context()
        entry = AuditLog(
            created_at=utcnow(),
            tenant_id=tenant_id or (UUID(ctx["tenant_id"]) if ctx["tenant_id"] else None),
            actor_id=actor_id or (UUID(ctx["user_id"]) if ctx["user_id"] else None),
            actor_type=actor_type or ctx["actor_type"],
            actor_label=actor_label,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=outcome,
            old_values=redact(old_values or {}, mask_pii=True),
            new_values=redact(new_values or {}, mask_pii=True),
            metadata_json=redact(metadata or {}, mask_pii=True),
            ip_address=ip_address,
            user_agent=(user_agent or "")[:500] or None,
            correlation_id=ctx["correlation_id"],
        )
        self._session.add(entry)
        return entry


def diff_for_audit(
    before: dict[str, Any], after: dict[str, Any], *, fields: set[str] | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return only the changed fields, redacted, for a compact audit record."""
    keys = fields or (set(before) | set(after))
    old = {k: before.get(k) for k in keys if before.get(k) != after.get(k)}
    new = {k: after.get(k) for k in keys if before.get(k) != after.get(k)}
    return redact(old, mask_pii=True), redact(new, mask_pii=True)
