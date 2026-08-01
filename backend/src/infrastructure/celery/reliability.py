"""Retry classification, idempotency and dead lettering.

Three rules carry the weight here:

1. A validation, permission or terminal business failure is **never** retried.
   Retrying them burns the queue and, for external effects, risks duplicate
   customer contact.
2. Idempotency is layered: an inbound event id in Redis for 24h, an execution key
   derived from the original event, and an action key of `execution:node:attempt`
   backed by a database natural constraint.
3. When retries are exhausted the payload lands in `app.dead_letters` with 14-day
   retention so it can be inspected and replayed, rather than vanishing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from infrastructure.integrations.retry import (
    BackoffPolicy,
    RetryClass,
    backoff_delay,
    should_retry,
)
from infrastructure.logging.setup import get_logger
from infrastructure.monitoring.metrics import dlq_size, worker_retries_total
from shared.exceptions import (
    Conflict,
    Forbidden,
    NotFound,
    PreconditionFailed,
    QuotaExceeded,
    Unauthenticated,
    ValidationError,
)
from shared.utils.timeutil import utcnow

logger = get_logger("celery.reliability")

DEAD_LETTER_RETENTION_DAYS = 14
IDEMPOTENCY_TTL_SECONDS = 86_400  # 24 hours
DEFAULT_MAX_ATTEMPTS = 3

# Exceptions that represent a settled decision. Retrying cannot change the outcome.
TERMINAL_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ValidationError,
    Unauthenticated,
    Forbidden,
    NotFound,
    Conflict,
    PreconditionFailed,
    QuotaExceeded,
    TypeError,
    ValueError,
    KeyError,
    AttributeError,
)


def classify_exception(exc: BaseException) -> RetryClass:
    """Map a raised exception to a retry class."""
    # Domain rule violations are terminal by definition.
    from domain.base import DomainError
    from infrastructure.integrations.circuit import CircuitOpen
    from shared.exceptions import ProviderUnavailable, RateLimited

    if isinstance(exc, RateLimited):
        return RetryClass.RATE_LIMITED
    if isinstance(exc, (ProviderUnavailable, CircuitOpen, ConnectionError, TimeoutError)):
        return RetryClass.PROVIDER
    if isinstance(exc, DomainError):
        return RetryClass.TERMINAL
    if isinstance(exc, TERMINAL_EXCEPTIONS):
        return RetryClass.TERMINAL
    return RetryClass.TRANSIENT


def is_retryable(exc: BaseException, attempt: int, max_attempts: int) -> bool:
    return should_retry(classify_exception(exc), attempt, max_attempts)


def retry_delay(exc: BaseException, attempt: int, policy: BackoffPolicy | None = None) -> float:
    """Exponential backoff with jitter; a rate limit waits at least its reset."""
    from shared.exceptions import RateLimited

    delay = backoff_delay(attempt, policy)
    if isinstance(exc, RateLimited):
        suggested = float(exc.details.get("retry_after", 0) or 0)
        return max(delay, suggested)
    return delay


# --- idempotency ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
    """`scope:identity` - the scope keeps unrelated producers from colliding."""

    scope: str
    identity: str

    def redis_key(self) -> str:
        from infrastructure.caching.redis import global_key

        return global_key("idem", self.scope, self.identity)


def inbound_key(provider: str, event_id: str) -> IdempotencyKey:
    return IdempotencyKey(f"inbound:{provider}", event_id)


def execution_key(
    workflow_id: UUID | str, version_id: UUID | str, event_id: UUID | str
) -> IdempotencyKey:
    return IdempotencyKey("execution", f"{workflow_id}:{version_id}:{event_id}")


def action_key(execution_id: UUID | str, node_id: str, attempt: int) -> IdempotencyKey:
    return IdempotencyKey("action", f"{execution_id}:{node_id}:{attempt}")


async def claim_once(key: IdempotencyKey, *, ttl: int = IDEMPOTENCY_TTL_SECONDS) -> bool:
    """Atomically claim a key. Returns False when it was already claimed.

    Uses SET NX so two workers racing on the same message cannot both proceed.
    A Redis outage fails **open** (returns True): correctness then rests on the
    database natural constraint at the action site, which is the durable layer.
    """
    from infrastructure.caching.redis import get_redis

    try:
        claimed = await get_redis().set(key.redis_key(), "1", nx=True, ex=ttl)
    except Exception as exc:
        logger.warning("idempotency_unavailable", scope=key.scope, reason=type(exc).__name__)
        return True
    return bool(claimed)


async def release_claim(key: IdempotencyKey) -> None:
    """Release a claim so a failed attempt can be retried."""
    from infrastructure.caching.redis import get_redis

    try:
        await get_redis().delete(key.redis_key())
    except Exception:
        return


# --- dead lettering -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DeadLetterRecord:
    queue: str
    task_name: str
    payload: dict[str, Any]
    error: str
    attempts: int
    tenant_id: UUID | None = None


async def write_dead_letter(record: DeadLetterRecord) -> UUID:
    """Persist an exhausted task. Durable, tenant-tagged and replayable.

    A tenant-owned dead letter is written under that tenant's context so the row
    satisfies row level security; a platform task writes an unscoped row with a
    NULL tenant. Row level security enforces the distinction rather than trusting
    the caller to get it right.
    """
    from infrastructure.database.models.workflows import DeadLetter
    from infrastructure.database.session import tenant_session, unscoped_session
    from shared.utils.ids import uuid7

    dead_letter_id = uuid7()
    opener = tenant_session(record.tenant_id) if record.tenant_id else unscoped_session()
    async with opener as session:
        session.add(
            DeadLetter(
                id=dead_letter_id,
                tenant_id=record.tenant_id,
                queue=record.queue,
                task_name=record.task_name,
                payload=record.payload,
                error=record.error[:4000],
                attempts=record.attempts,
                expires_at=utcnow() + timedelta(days=DEAD_LETTER_RETENTION_DAYS),
            )
        )
    logger.error(
        "task_dead_lettered",
        task=record.task_name,
        queue=record.queue,
        attempts=record.attempts,
        tenant_id=str(record.tenant_id) if record.tenant_id else None,
    )
    dlq_size.labels(queue=record.queue).inc()
    return dead_letter_id


async def replay_dead_letter(dead_letter_id: UUID) -> dict[str, Any]:
    """Re-enqueue a dead letter, preserving its original tenant context.

    The replay is recorded on the row so a duplicated external effect can always be
    traced back to the operator action that caused it.
    """
    from sqlalchemy import select

    from infrastructure.celery.app import app
    from infrastructure.celery.context import build_headers
    from infrastructure.database.models.workflows import DeadLetter
    from infrastructure.database.session import platform_session

    async with platform_session("dead letter replay") as session:
        row = (
            await session.execute(select(DeadLetter).where(DeadLetter.id == dead_letter_id))
        ).scalar_one_or_none()
        if row is None:
            raise NotFound("Dead letter not found.")
        if row.replayed_at is not None:
            return {"replayed": False, "reason": "already replayed"}

        payload = dict(row.payload or {})
        app.send_task(
            row.task_name,
            args=payload.get("args", []),
            kwargs=payload.get("kwargs", {}),
            queue=row.queue,
            headers=build_headers(
                tenant_id=row.tenant_id,
                correlation_id=payload.get("correlation_id"),
                actor_type="replay",
            ),
        )
        row.replayed_at = utcnow()

    logger.info("dead_letter_replayed", dead_letter_id=str(dead_letter_id), task=row.task_name)
    return {"replayed": True, "task": row.task_name, "queue": row.queue}


async def reap_expired_dead_letters() -> int:
    """Delete dead letters past their 14-day retention."""
    from sqlalchemy import delete

    from infrastructure.database.models.workflows import DeadLetter
    from infrastructure.database.session import platform_session

    async with platform_session("dead letter retention sweep") as session:
        result = await session.execute(delete(DeadLetter).where(DeadLetter.expires_at <= utcnow()))
    removed = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if removed:
        logger.info("dead_letters_reaped", removed=removed)
    return removed


def record_retry(task_name: str, queue: str, retry_class: RetryClass) -> None:
    worker_retries_total.labels(task=task_name, queue=queue, retry_class=retry_class.value).inc()
