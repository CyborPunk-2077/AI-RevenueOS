"""Queue topology.

The concurrency, priority and timeout figures come directly from the Workflow
Engine specification. `application.workflows.executor.QUEUES` is the domain-facing
copy of the same table; `test_queue_table_matches_the_domain_constant` asserts the
two never drift.
"""

from __future__ import annotations

from dataclasses import dataclass

from kombu import Exchange, Queue

# Celery/Redis priority is 0..9 where a LOWER number is delivered first. The
# specification uses 1..10 where a HIGHER number is more urgent, so the two must be
# translated rather than copied.
MAX_SPEC_PRIORITY = 10


@dataclass(frozen=True, slots=True)
class QueueSpec:
    name: str
    concurrency: int
    spec_priority: int
    timeout_seconds: int
    description: str

    @property
    def broker_priority(self) -> int:
        """Translate spec priority (10 = most urgent) to Redis priority (0 = first)."""
        return max(0, min(9, MAX_SPEC_PRIORITY - self.spec_priority))

    @property
    def soft_timeout_seconds(self) -> int:
        """Soft limit fires first so a task can clean up before it is killed."""
        return max(1, int(self.timeout_seconds * 0.8))


QUEUE_SPECS: tuple[QueueSpec, ...] = (
    QueueSpec("workflow-critical", 20, 10, 30, "payment, inbound, urgent message"),
    QueueSpec("workflow-standard", 50, 7, 300, "lifecycle actions"),
    QueueSpec("workflow-bulk", 30, 4, 900, "bulk operations"),
    QueueSpec("workflow-scheduled", 10, 5, 300, "timers and cron"),
    QueueSpec("workflow-webhook", 15, 6, 60, "outbound webhooks"),
    QueueSpec("workflow-ai", 10, 8, 120, "AI actions"),
    QueueSpec("workflow-notification", 20, 8, 60, "notifications"),
    QueueSpec("workflow-maintenance", 5, 1, 600, "cleanup and recovery"),
)

BY_NAME: dict[str, QueueSpec] = {q.name: q for q in QUEUE_SPECS}

DEFAULT_QUEUE = "workflow-standard"

# Worker pools are isolated by workload so a slow AI call cannot starve payments.
WORKER_POOLS: dict[str, tuple[str, ...]] = {
    "comms": ("workflow-critical", "workflow-notification", "workflow-webhook"),
    "ai": ("workflow-ai",),
    "general": ("workflow-standard", "workflow-scheduled"),
    "bulk": ("workflow-bulk", "workflow-maintenance"),
}

_exchange = Exchange("airevenueos", type="direct", durable=True)

CELERY_QUEUES: tuple[Queue, ...] = tuple(
    Queue(
        spec.name,
        _exchange,
        routing_key=spec.name,
        queue_arguments={"x-max-priority": 9},
    )
    for spec in QUEUE_SPECS
)


def queue_for(task_name: str) -> str:
    """Route a task to its queue by declared prefix; unknown tasks take the default."""
    for spec in QUEUE_SPECS:
        prefix = spec.name.removeprefix("workflow-")
        if task_name.startswith(f"{prefix}."):
            return spec.name
    return DEFAULT_QUEUE


def route_task(
    name: str,
    args: object = None,
    kwargs: object = None,
    options: dict[str, object] | None = None,
    task: object = None,
    **_: object,
) -> dict[str, object]:
    """Celery `task_routes` callable: queue plus its broker priority."""
    explicit = (options or {}).get("queue")
    queue = str(explicit) if explicit else queue_for(name)
    spec = BY_NAME.get(queue, BY_NAME[DEFAULT_QUEUE])
    return {
        "queue": spec.name,
        "routing_key": spec.name,
        "priority": spec.broker_priority,
    }
