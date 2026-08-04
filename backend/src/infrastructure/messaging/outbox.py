"""Transactional outbox poller.

FOR UPDATE SKIP LOCKED, batch 100, 500 ms cadence, at-least-once delivery.
Consumers must be idempotent; the poller never guarantees exactly-once.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from opentelemetry.trace import SpanKind
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from infrastructure.logging.setup import get_logger
from infrastructure.monitoring.metrics import outbox_dispatched, outbox_pending
from infrastructure.observability.tracing import start_span
from shared.utils.timeutil import utcnow

logger = get_logger("infra.outbox")

BATCH_SIZE = 100
POLL_INTERVAL_SECONDS = 0.5
MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 2

Handler = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class DispatchStats:
    claimed: int = 0
    dispatched: int = 0
    failed: int = 0
    dead_lettered: int = 0


CLAIM_SQL = text(
    """
    SELECT id, occurred_at, event_id, event_type, tenant_id, resource_type, resource_id,
           payload, correlation_id, attempts
    FROM audit.event_outbox
    WHERE processed_at IS NULL
      AND (available_at IS NULL OR available_at <= now())
    ORDER BY occurred_at
    FOR UPDATE SKIP LOCKED
    LIMIT :limit
    """
)


class OutboxDispatcher:
    """Polls the outbox and fans events out to registered handlers."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        self._factory = session_factory
        self._batch = batch_size
        self._handlers: dict[str, list[Handler]] = {}
        self._wildcard: list[Handler] = []
        self._stop = asyncio.Event()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        if event_type == "*":
            self._wildcard.append(handler)
        else:
            self._handlers.setdefault(event_type, []).append(handler)

    def handlers_for(self, event_type: str) -> list[Handler]:
        return [*self._handlers.get(event_type, []), *self._wildcard]

    async def run_once(self) -> DispatchStats:
        stats = DispatchStats()
        async with self._factory() as session:
            async with session.begin():
                rows = (await session.execute(CLAIM_SQL, {"limit": self._batch})).mappings().all()
                stats.claimed = len(rows)
                for row in rows:
                    await self._dispatch_row(session, dict(row), stats)
            await self._refresh_pending_gauge(session)
        return stats

    async def _dispatch_row(
        self, session: AsyncSession, row: dict[str, Any], stats: DispatchStats
    ) -> None:
        event_type = row["event_type"]
        handlers = self.handlers_for(event_type)
        tenant_id = row.get("tenant_id")
        try:
            with start_span(
                f"outbox dispatch {event_type}",
                kind=SpanKind.PRODUCER,
                attributes={
                    "outbox.event_type": event_type,
                    "messaging.operation": "publish",
                    "tenant.id": str(tenant_id) if tenant_id else None,
                },
            ):
                for handler in handlers:
                    await handler(row["payload"])
        except Exception as exc:
            attempts = int(row["attempts"]) + 1
            terminal = attempts >= MAX_ATTEMPTS
            stats.failed += 1
            if terminal:
                stats.dead_lettered += 1
            delay = timedelta(seconds=BACKOFF_BASE_SECONDS ** min(attempts, 6))
            await session.execute(
                text(
                    "UPDATE audit.event_outbox SET attempts = :a, last_error = :e,"
                    " available_at = :av, processed_at = :p"
                    " WHERE id = :id AND occurred_at = :o"
                ),
                {
                    "a": attempts,
                    "e": f"{type(exc).__name__}: {exc}"[:2000],
                    "av": utcnow() + delay,
                    "p": utcnow() if terminal else None,
                    "id": row["id"],
                    "o": row["occurred_at"],
                },
            )
            outbox_dispatched.labels(
                event_type=event_type, outcome="dead_letter" if terminal else "retry"
            ).inc()
            logger.warning(
                "outbox_dispatch_failed",
                event_type=event_type,
                attempts=attempts,
                terminal=terminal,
                error=type(exc).__name__,
            )
            return

        await session.execute(
            text(
                "UPDATE audit.event_outbox SET processed_at = now()"
                " WHERE id = :id AND occurred_at = :o"
            ),
            {"id": row["id"], "o": row["occurred_at"]},
        )
        stats.dispatched += 1
        outbox_dispatched.labels(event_type=event_type, outcome="success").inc()

    async def _refresh_pending_gauge(self, session: AsyncSession) -> None:
        pending = (
            await session.execute(
                text("SELECT count(*) FROM audit.event_outbox WHERE processed_at IS NULL")
            )
        ).scalar_one()
        outbox_pending.set(float(pending))

    async def run_forever(self, interval: float = POLL_INTERVAL_SECONDS) -> None:
        logger.info("outbox_poller_started", batch_size=self._batch, interval=interval)
        while not self._stop.is_set():
            try:
                stats = await self.run_once()
                if stats.claimed == 0:
                    await asyncio.sleep(interval)
            except Exception:
                logger.exception("outbox_poller_cycle_failed")
                await asyncio.sleep(interval * 4)

    def stop(self) -> None:
        self._stop.set()
