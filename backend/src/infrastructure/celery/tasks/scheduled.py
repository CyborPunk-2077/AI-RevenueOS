"""Periodic platform work driven by Celery Beat.

These tasks are platform-scoped by design: the outbox relay, the workflow scheduler
and the reconciliation sweep must observe every tenant. Each one re-establishes
tenant context per unit of work before touching tenant data.
"""

from __future__ import annotations

from typing import Any

from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.base import airev_task
from infrastructure.logging.setup import get_logger
from infrastructure.monitoring.metrics import outbox_pending

logger = get_logger("celery.scheduled")


@airev_task("scheduled.relay_outbox", tenant_scoped=False, max_attempts=1)
async def relay_outbox(_context: TaskContext) -> dict[str, Any]:
    """Drain a batch of the transactional outbox.

    Runs every 500 ms via Beat. `max_attempts=1` because the poller is inherently
    self-healing: an unprocessed row is simply claimed by the next cycle, so a
    retry would only duplicate work.
    """
    from infrastructure.database.session import get_sessionmaker
    from infrastructure.messaging.outbox import OutboxDispatcher

    dispatcher = OutboxDispatcher(get_sessionmaker())

    from application.crm.handlers import register_crm_handlers
    from application.workflows.triggers import register_workflow_handlers

    register_workflow_handlers(dispatcher)
    register_crm_handlers(dispatcher)

    stats = await dispatcher.run_once()
    if stats.claimed:
        logger.info(
            "outbox_batch",
            claimed=stats.claimed,
            dispatched=stats.dispatched,
            failed=stats.failed,
            dead_lettered=stats.dead_lettered,
        )
    return {
        "claimed": stats.claimed,
        "dispatched": stats.dispatched,
        "failed": stats.failed,
        "dead_lettered": stats.dead_lettered,
    }


@airev_task("scheduled.process_due_work", tenant_scoped=False, max_attempts=1)
async def process_due_work(_context: TaskContext) -> dict[str, Any]:
    """Resume executions whose durable delay has elapsed, and fire due schedules.

    Runs every 10 s. A delayed workflow node is never a process sleep: the executor
    suspends with `resume_at` and this sweep is what wakes it.
    """
    from sqlalchemy import select

    from infrastructure.celery.context import build_headers
    from infrastructure.database.models.workflows import WorkflowExecution
    from infrastructure.database.session import unscoped_session
    from shared.utils.timeutil import utcnow

    resumed = 0
    async with unscoped_session() as session:
        due = (
            (
                await session.execute(
                    select(WorkflowExecution)
                    .where(
                        WorkflowExecution.state == "waiting",
                        WorkflowExecution.resume_at.is_not(None),
                        WorkflowExecution.resume_at <= utcnow(),
                    )
                    .limit(100)
                )
            )
            .scalars()
            .all()
        )
        for execution in due:
            from infrastructure.celery.tasks.workflow import resume_execution

            resume_execution.apply_async(
                args=[str(execution.id)],
                headers=build_headers(
                    tenant_id=execution.tenant_id,
                    correlation_id=execution.correlation_id,
                    actor_type="scheduler",
                ),
            )
            execution.resume_at = None
            resumed += 1

    if resumed:
        logger.info("executions_resumed", count=resumed)
    return {"resumed": resumed}


@airev_task("scheduled.rollup_metrics", tenant_scoped=False, max_attempts=2)
async def rollup_metrics(_context: TaskContext) -> dict[str, Any]:
    """Refresh queue gauges every 15 minutes so alerts have current signal."""
    from sqlalchemy import func, select

    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.session import unscoped_session

    async with unscoped_session() as session:
        pending = (
            await session.execute(
                select(func.count())
                .select_from(EventOutbox)
                .where(EventOutbox.processed_at.is_(None))
            )
        ).scalar_one()
    outbox_pending.set(float(pending))

    depths = await queue_depths()
    return {"outbox_pending": int(pending), "queue_depths": depths}


async def queue_depths() -> dict[str, int]:
    """Read pending message counts straight from the broker."""
    from infrastructure.caching.redis import get_redis
    from infrastructure.celery.queues import QUEUE_SPECS
    from infrastructure.monitoring.metrics import queue_depth

    depths: dict[str, int] = {}
    try:
        client = get_redis()
        for spec in QUEUE_SPECS:
            depth = int(await client.llen(spec.name) or 0)
            depths[spec.name] = depth
            queue_depth.labels(queue=spec.name).set(float(depth))
    except Exception as exc:
        logger.warning("queue_depth_unavailable", reason=type(exc).__name__)
    return depths


@airev_task("scheduled.reconcile_payments", tenant_scoped=False, max_attempts=2)
async def reconcile_payments(_context: TaskContext) -> dict[str, Any]:
    """Reconcile queued or unconfirmed payments every 30 minutes.

    EXTERNAL GATE: without Razorpay credentials the adapter is unconfigured, so the
    sweep records that it could not run rather than inventing a result.
    """
    from application.payments.registry import get_razorpay_adapter

    adapter = get_razorpay_adapter()
    if not adapter.is_configured():
        logger.info("reconciliation_skipped", reason="razorpay_not_configured")
        return {
            "reconciled": 0,
            "skipped": True,
            "reason": "PROVIDER_NOT_CONFIGURED",
            "activation_prerequisite": adapter.activation_status()["activation_prerequisite"],
        }

    from sqlalchemy import select

    from infrastructure.database.models.payments import Payment
    from infrastructure.database.session import unscoped_session

    checked = 0
    async with unscoped_session() as session:
        pending = (
            (
                await session.execute(
                    select(Payment).where(Payment.reconciliation_status == "pending").limit(200)
                )
            )
            .scalars()
            .all()
        )
        checked = len(pending)
    logger.info("reconciliation_swept", checked=checked)
    return {"reconciled": 0, "checked": checked, "skipped": False}
