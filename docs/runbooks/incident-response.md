# Runbook: incident response

## Severity

| Severity | Definition | Response | Escalation |
|---|---|---|---|
| P1 | Cross-tenant exposure, data loss, total outage, payment corruption | Immediate | On-call, then engineering lead within 15 minutes |
| P2 | Degraded core journey, provider outage, AI error rate above 2% | 30 minutes | On-call |
| P3 | Single-tenant issue with a workaround | Next business day | Support |

**Any suspected cross-tenant exposure is P1 regardless of blast radius.**

## First five minutes

1. Acknowledge in PagerDuty and open an incident channel.
2. Check `GET /health/readiness` - it distinguishes live, ready and dependency degraded.
3. Check the dashboard: API P50/P95/P99, queue depth and age, DLQ size,
   `airev_circuit_state`, database and Redis capacity.
4. Decide: mitigate first, diagnose second.

## Mitigations, in order of preference

| Symptom | Mitigation |
|---|---|
| A provider is failing | The circuit breaker opens automatically. Confirm degradation is visible to users; no action if queues are draining. |
| Automation is misbehaving | Engage the kill switch: `POST /v1/workflows/{id}/kill` (workflow) or the tenant-scope switch. Effective in under five seconds. |
| A feature is causing errors | Turn the feature flag off. No deployment required. |
| A tenant is saturating shared capacity | Per-tenant throttles apply before shared exhaustion. Tighten the tenant bucket if needed. |
| A bad release | Roll back to the previous ECS task definition. Migrations are backward compatible, so no database rollback is needed. |
| Redis is unavailable | Cache reads bypass and correctness is unaffected. Workers pause safely. Do not fail over the database. |
| PostgreSQL is unavailable | The API returns a controlled 503. Multi-AZ failover targets 15 minutes. |

## Suspected cross-tenant exposure

1. Declare P1 immediately.
2. Preserve evidence: capture the correlation id, the audit log rows and the
   request path. Do not delete anything.
3. Determine scope from `audit.audit_logs` using the correlation id, then the actor
   and resource identifiers.
4. If confirmed, disable the affected code path with a feature flag and begin the
   DPDP breach assessment. The qualifying-breach process has a 72-hour clock.
5. Add a regression test that fails against the vulnerable code before shipping a fix.

## Payment discrepancy

1. Never edit `app.payments` by hand: it is append-only and trigger enforced.
2. Run reconciliation for the affected window and inspect
   `reconciliation_runs.discrepancies`.
3. Compare against the provider dashboard using `external_payment_id`.
4. Corrections are new rows (a refund or a compensating transition), never a rewrite.

## After the incident

Write a blameless postmortem within five business days covering: timeline with
correlation ids, contributing causes, detection gap, the regression test added and
the alert added or tuned.
