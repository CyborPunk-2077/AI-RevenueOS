"""Worker health, usable by Compose, ECS and the readiness endpoint.

Liveness asks whether this process can still reach its broker. Readiness adds the
database, because a worker that cannot reach PostgreSQL will fail every task it
accepts and should not be handed work.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from infrastructure.logging.setup import get_logger
from infrastructure.monitoring.metrics import worker_heartbeat_timestamp

logger = get_logger("celery.health")

HEARTBEAT_STALE_SECONDS = 60


@dataclass(slots=True)
class WorkerHealth:
    pool: str
    broker_ok: bool = False
    database_ok: bool = False
    queues: tuple[str, ...] = ()
    checked_at: float = field(default_factory=time.time)

    @property
    def alive(self) -> bool:
        return self.broker_ok

    @property
    def ready(self) -> bool:
        return self.broker_ok and self.database_ok

    def to_dict(self) -> dict[str, Any]:
        return {
            "pool": self.pool,
            "status": "ready" if self.ready else ("alive" if self.alive else "down"),
            "broker": "up" if self.broker_ok else "down",
            "database": "up" if self.database_ok else "down",
            "queues": list(self.queues),
            "checked_at": self.checked_at,
        }


async def check_worker(pool: str = "general") -> WorkerHealth:
    from infrastructure.caching.redis import get_redis
    from infrastructure.celery.queues import WORKER_POOLS
    from infrastructure.database.session import ping as database_ping

    health = WorkerHealth(pool=pool, queues=WORKER_POOLS.get(pool, ()))

    try:
        await get_redis().ping()
        health.broker_ok = True
    except Exception as exc:
        logger.warning("worker_broker_down", reason=type(exc).__name__)

    try:
        await database_ping()
        health.database_ok = True
    except Exception as exc:
        logger.warning("worker_database_down", reason=type(exc).__name__)

    if health.alive:
        worker_heartbeat_timestamp.labels(pool=pool).set(time.time())
    return health


def inspect_active_workers(timeout: float = 2.0) -> dict[str, Any]:
    """Ask the broker which workers are currently registered."""
    from infrastructure.celery.app import app

    try:
        replies = app.control.inspect(timeout=timeout).ping() or {}
    except Exception as exc:
        return {"workers": [], "error": type(exc).__name__}
    return {"workers": sorted(replies), "count": len(replies)}


def heartbeat_is_stale(last_seen: float, *, now: float | None = None) -> bool:
    return ((now or time.time()) - last_seen) > HEARTBEAT_STALE_SECONDS
