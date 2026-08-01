"""Celery application: the composition root for every worker.

Configuration follows the Workflow Engine specification exactly: JSON serialisation,
`acks_late`, reject on worker loss, prefetch 1, hard 600s / soft 480s unless the
queue's own action limit is stricter, and a 14-day dead-letter retention.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from celery import Celery, Task
from celery.signals import (
    setup_logging,
    task_failure,
    task_postrun,
    task_prerun,
    task_retry,
)

from infrastructure.celery.context import (
    TaskContext,
    bound_context,
    headers_from_request,
)
from infrastructure.celery.queues import (
    BY_NAME,
    CELERY_QUEUES,
    DEFAULT_QUEUE,
    route_task,
)
from infrastructure.logging.setup import configure_logging, get_logger
from infrastructure.monitoring.metrics import (
    worker_tasks_total,
)
from shared.settings import Settings, get_settings

logger = get_logger("celery.app")

# Global ceilings. A queue with a stricter action limit narrows them further.
GLOBAL_HARD_TIMEOUT_SECONDS = 600
GLOBAL_SOFT_TIMEOUT_SECONDS = 480
DEAD_LETTER_RETENTION_DAYS = 14


def build_app(settings: Settings | None = None) -> Celery:
    cfg = settings or get_settings()
    celery_app = Celery("airevenueos")

    celery_app.conf.update(
        broker_url=cfg.redis_url,
        # Results are operational telemetry only. PostgreSQL remains the durable
        # source of truth; nothing reads business state back from the result store.
        result_backend=cfg.redis_url,
        result_expires=3600,
        # --- serialisation: JSON only, never pickle ---------------------------
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        # --- delivery guarantees ---------------------------------------------
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_acks_on_failure_or_timeout=False,
        worker_prefetch_multiplier=1,
        task_track_started=True,
        # --- timeouts ---------------------------------------------------------
        task_time_limit=GLOBAL_HARD_TIMEOUT_SECONDS,
        task_soft_time_limit=GLOBAL_SOFT_TIMEOUT_SECONDS,
        # --- routing ----------------------------------------------------------
        task_queues=list(CELERY_QUEUES),
        task_default_queue=DEFAULT_QUEUE,
        task_default_exchange="airevenueos",
        task_default_routing_key=DEFAULT_QUEUE,
        task_routes=(route_task,),
        broker_transport_options={
            "queue_order_strategy": "priority",
            "priority_steps": list(range(10)),
            "sep": ":",
            # A task that is not acked within its visibility window returns to the
            # queue. Sized to the longest queue timeout so a slow bulk job is not
            # redelivered while it is still running.
            "visibility_timeout": 1200,
        },
        broker_connection_retry_on_startup=True,
        # --- scheduling -------------------------------------------------------
        timezone="UTC",
        enable_utc=True,
        beat_schedule=beat_schedule(),
        # --- worker behaviour -------------------------------------------------
        worker_hijack_root_logger=False,
        worker_max_tasks_per_child=500,
        worker_send_task_events=True,
        task_send_sent_event=True,
    )
    celery_app.Task = TenantTask  # type: ignore[misc]
    return celery_app


def beat_schedule() -> dict[str, dict[str, Any]]:
    """Periodic work, at the cadences the specification fixes."""
    from celery.schedules import crontab

    return {
        "outbox-relay": {
            "task": "scheduled.relay_outbox",
            "schedule": 0.5,  # 500 ms target cadence
            "options": {"queue": "workflow-scheduled", "expires": 5},
        },
        "workflow-scheduler": {
            "task": "scheduled.process_due_work",
            "schedule": 10.0,
            "options": {"queue": "workflow-scheduled", "expires": 30},
        },
        "webhook-sweep": {
            "task": "webhook.sweep_pending_deliveries",
            "schedule": 60.0,
            "options": {"queue": "workflow-webhook", "expires": 120},
        },
        "metrics-rollup": {
            "task": "scheduled.rollup_metrics",
            "schedule": 900.0,  # 15 minutes
            "options": {"queue": "workflow-scheduled"},
        },
        "payment-reconciliation": {
            "task": "scheduled.reconcile_payments",
            "schedule": 1800.0,  # 30 minutes
            "options": {"queue": "workflow-scheduled"},
        },
        "maintenance-cleanup": {
            "task": "maintenance.nightly_cleanup",
            "schedule": crontab(hour=3, minute=0),  # 03:00 UTC
            "options": {"queue": "workflow-maintenance"},
        },
        "dead-letter-reaper": {
            "task": "maintenance.reap_dead_letters",
            "schedule": crontab(hour=3, minute=30),
            "options": {"queue": "workflow-maintenance"},
        },
    }


class TenantTask(Task):
    """Base task: context propagation, per-queue timeouts and a shared event loop.

    Subclasses set `tenant_scoped = True` (the default) to refuse execution without
    a tenant header. Genuinely platform-wide work sets it to `False` explicitly, so
    the unscoped case is always a deliberate, reviewable decision.
    """

    tenant_scoped: bool = True
    # Thread local, not a class attribute: a Celery worker may execute tasks on
    # several threads, and an event loop (and the SQLAlchemy pool bound to it)
    # must never be shared across them.
    _loop_store = threading.local()

    @property
    def context(self) -> TaskContext:
        return headers_from_request(self.request)

    def apply_async(self, *args: Any, **kwargs: Any) -> Any:
        """Narrow the global timeout to the queue's limit when one is stricter."""
        queue = kwargs.get("queue") or route_task(self.name).get("queue")
        spec = BY_NAME.get(str(queue))
        if spec is not None:
            kwargs.setdefault("time_limit", min(GLOBAL_HARD_TIMEOUT_SECONDS, spec.timeout_seconds))
            kwargs.setdefault(
                "soft_time_limit",
                min(GLOBAL_SOFT_TIMEOUT_SECONDS, spec.soft_timeout_seconds),
            )
        return super().apply_async(*args, **kwargs)

    def run_async(self, coro: Any) -> Any:
        """Run a coroutine on a loop owned by this worker thread.

        A fresh `asyncio.run` per task would discard the SQLAlchemy connection pool
        every time; a long-lived per-thread loop keeps pooling effective while
        keeping each thread's connections on the loop that created them. Sharing one
        loop across threads produces "attached to a different loop" errors under a
        threaded worker pool.
        """
        loop: asyncio.AbstractEventLoop | None = getattr(TenantTask._loop_store, "loop", None)
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            TenantTask._loop_store.loop = loop
        return loop.run_until_complete(coro)


app = build_app()


# --- observability signals ------------------------------------------------


@setup_logging.connect
def _configure_worker_logging(**_: Any) -> None:
    cfg = get_settings()
    configure_logging(level=cfg.log_level, json_output=cfg.log_json, service="worker")


@task_prerun.connect
def _on_prerun(task_id: str | None = None, task: Any = None, **_: Any) -> None:
    context = headers_from_request(getattr(task, "request", None))
    binder = bound_context(context)
    binder.__enter__()
    task._airev_binder = binder
    logger.info(
        "task_started",
        task=getattr(task, "name", "unknown"),
        task_id=task_id,
        queue=getattr(getattr(task, "request", None), "delivery_info", {}).get("routing_key"),
    )


@task_postrun.connect
def _on_postrun(
    task_id: str | None = None, task: Any = None, state: str | None = None, **_: Any
) -> None:
    queue = getattr(getattr(task, "request", None), "delivery_info", {}).get(
        "routing_key", "unknown"
    )
    worker_tasks_total.labels(
        task=getattr(task, "name", "unknown"), queue=queue, outcome=(state or "unknown").lower()
    ).inc()
    logger.info(
        "task_finished", task=getattr(task, "name", "unknown"), task_id=task_id, state=state
    )
    binder = getattr(task, "_airev_binder", None)
    if binder is not None:
        binder.__exit__(None, None, None)
        task._airev_binder = None


@task_retry.connect
def _on_retry(request: Any = None, reason: Any = None, **_: Any) -> None:
    logger.warning(
        "task_retry",
        task=getattr(request, "task", "unknown"),
        reason=str(reason)[:300],
        retries=getattr(request, "retries", 0),
    )


@task_failure.connect
def _on_failure(
    task_id: str | None = None,
    exception: BaseException | None = None,
    sender: Any = None,
    **_: Any,
) -> None:
    logger.error(
        "task_failed",
        task=getattr(sender, "name", "unknown"),
        task_id=task_id,
        error=type(exception).__name__ if exception else "unknown",
    )


def autodiscover() -> None:
    """Import task modules so they register on the app."""
    from infrastructure.celery import tasks  # noqa: F401


autodiscover()
