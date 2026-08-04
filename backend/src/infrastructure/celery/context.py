"""Tenant-safe context propagation across the process boundary.

A Celery task runs in a different process from the request that enqueued it, so the
tenant, correlation and actor identity must travel with the message. They travel in
the message **headers**, not the payload: headers are set by the producer and cannot
be rewritten by task code, and a task body that is replayed from a dead letter keeps
its original provenance.

Every tenant-scoped task refuses to run without a bound tenant. Failing closed here
is what stops a worker from silently operating with no RLS predicate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from opentelemetry.propagate import inject

from infrastructure.logging.context import bind_context, reset_context
from infrastructure.monitoring.metrics import tenant_isolation_violations

HEADER_TENANT = "airev_tenant_id"
HEADER_CORRELATION = "airev_correlation_id"
HEADER_ACTOR = "airev_actor_id"
HEADER_ACTOR_TYPE = "airev_actor_type"


class MissingTenantContext(RuntimeError):
    """Raised when a tenant-scoped task is dispatched without a tenant header."""


@dataclass(frozen=True, slots=True)
class TaskContext:
    tenant_id: UUID | None
    correlation_id: str | None
    actor_id: UUID | None
    actor_type: str

    def require_tenant(self) -> UUID:
        if self.tenant_id is None:
            tenant_isolation_violations.labels(surface="worker").inc()
            raise MissingTenantContext(
                "this task is tenant scoped but was dispatched without a tenant header"
            )
        return self.tenant_id

    def as_headers(self) -> dict[str, Any]:
        return {
            HEADER_TENANT: str(self.tenant_id) if self.tenant_id else None,
            HEADER_CORRELATION: self.correlation_id,
            HEADER_ACTOR: str(self.actor_id) if self.actor_id else None,
            HEADER_ACTOR_TYPE: self.actor_type,
        }


def build_headers(
    *,
    tenant_id: UUID | str | None = None,
    correlation_id: str | None = None,
    actor_id: UUID | str | None = None,
    actor_type: str = "system",
) -> dict[str, Any]:
    """Headers to attach when enqueuing. Producers should always call this."""
    if tenant_id is not None:
        UUID(str(tenant_id))  # reject anything that is not a UUID at enqueue time
    headers: dict[str, Any] = {
        HEADER_TENANT: str(tenant_id) if tenant_id else None,
        HEADER_CORRELATION: correlation_id,
        HEADER_ACTOR: str(actor_id) if actor_id else None,
        HEADER_ACTOR_TYPE: actor_type,
    }
    # W3C trace context, so the worker span joins the trace that enqueued the task.
    # Writes nothing when no span is active, which is the default.
    inject(headers)
    return headers


def headers_from_request(request: Any) -> TaskContext:
    """Read the context a producer attached, tolerating a header-less message."""
    raw: dict[str, Any] = {}
    for source in (getattr(request, "headers", None), getattr(request, "__dict__", None)):
        if isinstance(source, dict):
            raw.update({k: v for k, v in source.items() if k.startswith("airev_")})

    tenant_raw = raw.get(HEADER_TENANT)
    actor_raw = raw.get(HEADER_ACTOR)
    return TaskContext(
        tenant_id=UUID(str(tenant_raw)) if tenant_raw else None,
        correlation_id=raw.get(HEADER_CORRELATION),
        actor_id=UUID(str(actor_raw)) if actor_raw else None,
        actor_type=str(raw.get(HEADER_ACTOR_TYPE) or "system"),
    )


def current_context_from(request: Any) -> TaskContext:
    return headers_from_request(request)


class bound_context:  # noqa: N801 - used as a context manager, not a type
    """Bind task context to structlog and the tenant contextvar for the task's life."""

    def __init__(self, context: TaskContext) -> None:
        self._context = context
        self._tokens: Any = None

    def __enter__(self) -> TaskContext:
        self._tokens = bind_context(
            correlation_id=self._context.correlation_id,
            tenant_id=str(self._context.tenant_id) if self._context.tenant_id else None,
            user_id=str(self._context.actor_id) if self._context.actor_id else None,
            actor_type=self._context.actor_type,
        )
        return self._context

    def __exit__(self, *exc: Any) -> None:
        if self._tokens is not None:
            reset_context(self._tokens)
            self._tokens = None
