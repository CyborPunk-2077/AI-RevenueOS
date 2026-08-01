"""Prometheus metric definitions shared by API, workers and the scheduler."""

from __future__ import annotations

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry(auto_describe=True)

LATENCY_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0)

http_requests = Counter(
    "airev_http_requests_total", "HTTP requests", ["method", "route", "status"], registry=REGISTRY
)
http_latency = Histogram(
    "airev_http_request_seconds",
    "HTTP latency",
    ["method", "route"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
outbox_pending = Gauge("airev_outbox_pending", "Unprocessed outbox rows", registry=REGISTRY)
outbox_dispatched = Counter(
    "airev_outbox_dispatched_total",
    "Dispatched outbox events",
    ["event_type", "outcome"],
    registry=REGISTRY,
)
queue_depth = Gauge("airev_queue_depth", "Celery queue depth", ["queue"], registry=REGISTRY)
queue_age_seconds = Gauge(
    "airev_queue_age_seconds", "Oldest queued task age", ["queue"], registry=REGISTRY
)
dlq_size = Gauge("airev_dlq_size", "Dead letter queue size", ["queue"], registry=REGISTRY)

provider_calls = Counter(
    "airev_provider_calls_total",
    "External provider calls",
    ["provider", "operation", "outcome"],
    registry=REGISTRY,
)
provider_latency = Histogram(
    "airev_provider_seconds",
    "Provider latency",
    ["provider", "operation"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
circuit_state = Gauge(
    "airev_circuit_state", "0 closed 1 half-open 2 open", ["provider"], registry=REGISTRY
)

ai_tokens = Counter(
    "airev_ai_tokens_total", "AI tokens", ["provider", "model", "kind"], registry=REGISTRY
)
ai_cost_micro_inr = Counter(
    "airev_ai_cost_micro_inr_total",
    "AI cost in micro-INR",
    ["provider", "model"],
    registry=REGISTRY,
)
ai_guard_blocks = Counter(
    "airev_ai_guard_blocks_total", "AI guard blocks", ["guard", "reason"], registry=REGISTRY
)

workflow_executions = Counter(
    "airev_workflow_executions_total", "Workflow executions", ["outcome"], registry=REGISTRY
)
workflow_lag_seconds = Histogram(
    "airev_workflow_trigger_lag_seconds",
    "Trigger to execution lag",
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)

# --- worker tier ---------------------------------------------------------
worker_tasks_total = Counter(
    "airev_worker_tasks_total",
    "Worker tasks by outcome",
    ["task", "queue", "outcome"],
    registry=REGISTRY,
)
worker_task_duration = Histogram(
    "airev_worker_task_seconds",
    "Worker task duration",
    ["task", "queue"],
    buckets=LATENCY_BUCKETS,
    registry=REGISTRY,
)
worker_retries_total = Counter(
    "airev_worker_retries_total",
    "Worker retries",
    ["task", "queue", "retry_class"],
    registry=REGISTRY,
)
worker_heartbeat_timestamp = Gauge(
    "airev_worker_heartbeat_timestamp",
    "Unix time of the last worker heartbeat",
    ["pool"],
    registry=REGISTRY,
)

tenant_isolation_violations = Counter(
    "airev_tenant_isolation_violations_total",
    "Queries rejected for missing or mismatched tenant context",
    ["surface"],
    registry=REGISTRY,
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
