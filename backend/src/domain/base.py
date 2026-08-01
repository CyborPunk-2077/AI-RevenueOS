"""Pure domain primitives. No FastAPI, SQLAlchemy, Redis, network or I/O here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar
from uuid import UUID

from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow


class DomainError(Exception):
    """Base for rule violations detected inside the domain layer."""

    code: ClassVar[str] = "DOMAIN_RULE_VIOLATION"


class InvalidTransition(DomainError):
    code = "INVALID_TRANSITION"


class PolicyViolation(DomainError):
    code = "POLICY_VIOLATION"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """Emitted by aggregates and persisted to the outbox in the same transaction."""

    event_type: str
    tenant_id: UUID
    resource_type: str
    resource_id: UUID
    payload: dict[str, Any] = field(default_factory=dict)
    actor_id: UUID | None = None
    actor_type: str = "user"
    correlation_id: str | None = None
    event_id: UUID = field(default_factory=uuid7)
    occurred_at: datetime = field(default_factory=utcnow)
    schema_version: str = "1.0"

    def to_outbox_payload(self) -> dict[str, Any]:
        return {
            "event_id": str(self.event_id),
            "event_type": self.event_type,
            "tenant_id": str(self.tenant_id),
            "timestamp": self.occurred_at.isoformat(),
            "version": self.schema_version,
            "resource": {"type": self.resource_type, "id": str(self.resource_id)},
            "actor": {"id": str(self.actor_id) if self.actor_id else None, "type": self.actor_type},
            "correlation_id": self.correlation_id,
            "data": self.payload,
        }


class AggregateRoot:
    """Collects domain events for transactional publication."""

    def __init__(self) -> None:
        self._events: list[DomainEvent] = []

    def record(self, event: DomainEvent) -> None:
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events

    @property
    def pending_events(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events)
