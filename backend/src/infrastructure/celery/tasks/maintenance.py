"""Nightly maintenance: partitions, retention, dead letters and idempotency reaping."""

from __future__ import annotations

from typing import Any

from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.base import airev_task
from infrastructure.logging.setup import get_logger

logger = get_logger("celery.maintenance")


@airev_task("maintenance.nightly_cleanup", tenant_scoped=False, max_attempts=2)
async def nightly_cleanup(_context: TaskContext) -> dict[str, Any]:
    """Runs at 03:00 UTC: create partitions ahead, then prune expired rows."""
    created = await ensure_future_partitions()
    outbox_removed = await prune_processed_outbox()
    idempotency_removed = await prune_expired_idempotency()
    return {
        "partitions_created": created,
        "outbox_pruned": outbox_removed,
        "idempotency_pruned": idempotency_removed,
    }


async def ensure_future_partitions() -> int:
    """Create next period's partitions before they are needed.

    A row landing in the default partition means this job fell behind, which is why
    partitions are created ahead rather than on demand. New children are created
    WITH row level security: PostgreSQL does not inherit it from the parent.

    Runs with the elevated maintenance credential: the runtime application role
    deliberately cannot create tables.
    """
    from datetime import timedelta

    from sqlalchemy import text

    from infrastructure.database.ddl import PARTITIONED, partition_statements
    from infrastructure.database.session import (
        MaintenanceCredentialMissing,
        maintenance_session,
    )
    from shared.utils.timeutil import utcnow

    horizon = utcnow() + timedelta(days=32)
    created = 0
    try:
        async with maintenance_session() as session:
            for (schema, table), (_column, granularity) in PARTITIONED.items():
                for statement in partition_statements(
                    schema, table, granularity, horizon.date(), periods=2
                ):
                    await session.execute(text(statement))
                    created += 1
    except MaintenanceCredentialMissing as exc:
        # Reported, never silently skipped: a partition gap becomes a default
        # partition write, which is an alertable condition.
        logger.error("partition_maintenance_unavailable", reason=str(exc))
        return 0
    logger.info("partitions_ensured", statements=created)
    return created


async def prune_processed_outbox() -> int:
    """The outbox retains seven days; consumers are idempotent, so replay is safe."""
    from datetime import timedelta

    from sqlalchemy import delete

    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.session import unscoped_session
    from shared.utils.timeutil import utcnow

    cutoff = utcnow() - timedelta(days=7)
    async with unscoped_session() as session:
        result = await session.execute(
            delete(EventOutbox).where(
                EventOutbox.processed_at.is_not(None), EventOutbox.occurred_at < cutoff
            )
        )
    removed = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if removed:
        logger.info("outbox_pruned", removed=removed)
    return removed


async def prune_expired_idempotency() -> int:
    """Idempotency records are retained 24 hours, per the public API contract."""
    from sqlalchemy import delete

    from infrastructure.database.models.audit import IdempotencyRecord
    from infrastructure.database.session import unscoped_session
    from shared.utils.timeutil import utcnow

    async with unscoped_session() as session:
        result = await session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.expires_at <= utcnow())
        )
    removed = int(result.rowcount or 0)  # type: ignore[attr-defined]
    if removed:
        logger.info("idempotency_records_pruned", removed=removed)
    return removed


@airev_task("maintenance.reap_dead_letters", tenant_scoped=False, max_attempts=2)
async def reap_dead_letters(_context: TaskContext) -> dict[str, Any]:
    """Delete dead letters past their 14-day retention."""
    from infrastructure.celery.reliability import reap_expired_dead_letters

    return {"removed": await reap_expired_dead_letters()}


@airev_task("maintenance.replay_dead_letter", tenant_scoped=False, max_attempts=1)
async def replay_dead_letter_task(_context: TaskContext, dead_letter_id: str) -> dict[str, Any]:
    """Operator-initiated replay. Records provenance on the dead letter row."""
    from uuid import UUID

    from infrastructure.celery.reliability import replay_dead_letter

    return await replay_dead_letter(UUID(dead_letter_id))
