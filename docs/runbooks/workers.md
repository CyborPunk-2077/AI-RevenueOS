# Runbook: the worker tier

## Topology

Four pools, isolated by workload so a slow AI call cannot starve payments.

| Pool | Queues | Concurrency |
|---|---|---|
| `comms` | workflow-critical, workflow-notification, workflow-webhook | 20 |
| `ai` | workflow-ai | 10 |
| `general` | workflow-standard, workflow-scheduled | 50 |
| `bulk` | workflow-bulk, workflow-maintenance | 30 |

| Queue | Concurrency | Priority | Timeout |
|---|---:|---:|---:|
| workflow-critical | 20 | 10 | 30s |
| workflow-standard | 50 | 7 | 300s |
| workflow-bulk | 30 | 4 | 900s |
| workflow-scheduled | 10 | 5 | 300s |
| workflow-webhook | 15 | 6 | 60s |
| workflow-ai | 10 | 8 | 120s |
| workflow-notification | 20 | 8 | 60s |
| workflow-maintenance | 5 | 1 | 600s |

Priority is inverted for the broker: spec priority 10 (most urgent) becomes Redis
priority 0 (delivered first). `test_priority_translation_inverts_for_the_broker`
pins this, because getting it backwards would silently deprioritise payments.

## Running locally

```bash
make up                       # postgres, redis, api, 4 worker pools, beat, web
make migrate seed             # schema + reference data (admin credential)
make worker pool=comms        # run one pool in the foreground
make beat                     # run the scheduler
make worker-health pool=ai    # probe: exit 0 = ready
make queues                   # depths, pools, live workers
make dlq                      # recent dead letters
make test-workers             # 34 tests on real Postgres + Redis + Celery
```

## Three database roles

The separation is enforced by PostgreSQL, not by convention.

| Role | May | May not |
|---|---|---|
| `airevenueos_app` | DML on tenant tables | create/drop tables; write reference data |
| `airevenueos_maintenance` | partition DDL, retention sweeps | bypass RLS (`NOBYPASSRLS`) |
| migration/admin | schema, reference data | — deploy-time only |

`MAINTENANCE_DATABASE_URL` is what the partition job uses. **If it is unset,
partition maintenance is skipped and logged as `partition_maintenance_unavailable`
— it does not fail silently.** A missing partition means writes land in the default
partition, which is an alertable condition.

## Scheduled work

| Task | Cadence | Purpose |
|---|---|---|
| `scheduled.relay_outbox` | 500 ms | drain the transactional outbox |
| `scheduled.process_due_work` | 10 s | resume executions whose durable delay elapsed |
| `webhook.sweep_pending_deliveries` | 60 s | re-drive outbound webhooks past backoff |
| `scheduled.rollup_metrics` | 15 m | refresh queue and outbox gauges |
| `scheduled.reconcile_payments` | 30 m | reconcile unconfirmed payments |
| `maintenance.nightly_cleanup` | 03:00 UTC | partitions ahead, prune outbox and idempotency |
| `maintenance.reap_dead_letters` | 03:30 UTC | delete dead letters past 14 days |

Run exactly **one** Beat instance. Two schedulers double every periodic task.

## Retry policy

Classification decides whether a failure is retried at all:

| Class | Examples | Retried |
|---|---|---|
| `TERMINAL` | ValidationError, Forbidden, NotFound, Conflict, domain rule violations, TypeError | **never** |
| `PROVIDER` | ProviderUnavailable, CircuitOpen, ConnectionError, TimeoutError | yes, exponential + jitter |
| `RATE_LIMITED` | RateLimited | yes, at least the suggested reset |
| `TRANSIENT` | anything unclassified | yes, exponential + jitter |

Retrying a terminal failure burns the queue and, for an external effect, risks
duplicate customer contact. When attempts are exhausted the task is written to
`app.dead_letters` with its tenant, payload, error and attempt count.

## Dead letters

```bash
make dlq                                                  # list
python src/scripts/queue_status.py --replay <uuid>        # re-enqueue once
```

Replay preserves the original tenant context and stamps `replayed_at`, so a
duplicated external effect can always be traced to the operator action that caused
it. A dead letter replays **once**; a second attempt is refused.

Reading dead letters across tenants requires `app.platform_context`, which
`platform_session()` binds while logging the reason. This is deliberately narrower
than a `BYPASSRLS` role, which would disable policies on every table it touched.

## Idempotency

Three layers, because any one of them can fail:

1. **Inbound** — provider event id claimed in Redis for 24h with atomic `SET NX`.
2. **Execution** — key derived from the original trigger event, so a redelivered
   trigger cannot start a second run.
3. **Action** — `execution:node:attempt`, backed by a database natural constraint.

Redis claims **fail open**: if the broker is unreachable the work proceeds and
correctness rests on the database constraint, which is the durable layer. Blocking
on a cache outage would be worse than a rare duplicate an idempotent consumer absorbs.

## Diagnosis

| Symptom | Check | Likely cause |
|---|---|---|
| Queue depth climbing | `make queues` | no worker for that pool, or concurrency too low |
| Tasks fail instantly with a tenant error | logs for `tenant_isolation_violations` | producer omitted `build_headers(tenant_id=...)` |
| "attached to a different loop" | worker logs | an event loop shared across threads — the loop is thread-local by design; a regression here is a defect |
| Dead letters accumulating | `make dlq` | inspect `error`; terminal classes indicate a producer bug, not a transient fault |
| Partition maintenance silent | grep `partition_maintenance_unavailable` | `MAINTENANCE_DATABASE_URL` unset |
| Reconciliation always skipped | task result `PROVIDER_NOT_CONFIGURED` | Razorpay not activated — expected until that gate clears |

## Metrics

`airev_worker_tasks_total{task,queue,outcome}`,
`airev_worker_task_seconds{task,queue}`,
`airev_worker_retries_total{task,queue,retry_class}`,
`airev_worker_heartbeat_timestamp{pool}`,
`airev_queue_depth{queue}`, `airev_dlq_size{queue}`,
`airev_outbox_pending`, `airev_tenant_isolation_violations{surface}`.

Alert rules are **not yet defined** — see P1-3 in `docs/RELEASE-BLOCKERS.md`.
At minimum, alert on: `tenant_isolation_violations` above zero (P1, always),
queue age, DLQ growth rate, and a heartbeat older than 60 s.
