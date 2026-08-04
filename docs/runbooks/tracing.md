# Runbook: distributed tracing

Tracing is OpenTelemetry, exported over OTLP/HTTP. It is **off** in every
environment until switched on, and no collector has been deployed or verified.

## Turning it on

| Variable | Meaning |
|---|---|
| `OTEL_ENABLED` | Master switch. `false` by default. |
| `OTEL_EXPORTER_ENDPOINT` | OTLP HTTP traces endpoint, e.g. `http://otel-collector:4318/v1/traces`. |
| `OTEL_SAMPLE_RATIO` | Head sampling ratio, parent-based. `0.05` by default. |
| `OTEL_EXPORT_TIMEOUT_MS` | Exporter timeout. `5000` by default. |
| `OTEL_TRUST_INCOMING_TRACE_CONTEXT` | Accept `traceparent` from callers. `false` by default. |

Both `OTEL_ENABLED=true` **and** an endpoint are required; either alone exports
nothing and leaves the no-op tracer installed. There is no code path in which a
missing collector degrades request handling — spans are dropped by the batch
processor, not retried into the request path.

Only enable `OTEL_TRUST_INCOMING_TRACE_CONTEXT` behind an ingress that strips or
overwrites client-supplied `traceparent` headers. Public endpoints
(`/v1/public/*`, `/v1/webhooks/inbound/*`) are reachable by anyone, and a caller
who chooses the trace id can file requests under someone else's trace or flood a
single one.

## What is instrumented

| Span | Kind | Where |
|---|---|---|
| `METHOD /route/{template}` | server | `api/middleware/correlation.py` |
| `task <name>` | consumer | `infrastructure/celery/tasks/base.py` |
| `outbox dispatch <event_type>` | producer | `infrastructure/messaging/outbox.py` |
| `ai complete` | client | `infrastructure/ai/gateway.py` |
| `webhook send` | client | `infrastructure/integrations/webhook.py` |

Trace context propagates from an HTTP request to the worker through the Celery
message headers written by `build_headers`, so a task span joins the trace of the
request that enqueued it. With tracing off, `build_headers` writes no extra keys.

## What a span may contain, and why

Spans carry an allow-list of attributes only; see `ALLOWED_ATTRIBUTES` in
`infrastructure/observability/tracing.py`. Identifiers (tenant, user, correlation)
are opaque UUIDs and are kept because an operator cannot triage without them.
Everything else must be a scalar, is scrubbed with the same redactor the logs use,
and is truncated.

Three things are deliberately absent:

- **Auto-instrumentation.** The `opentelemetry-instrumentation-*` packages record
  full request targets, SQL statement text and headers. Spans here are opened by
  hand instead.
- **Exception messages.** `Span.record_exception` writes `str(exc)` and a
  stacktrace. Messages quote the offending value, so failures record the exception
  *type* and an error status only. The message stays in the redacted log.
- **URLs and query strings.** The route template is recorded, never the resolved
  path or the query string; tenant webhook URLs routinely embed a token.

Adding an attribute means editing the allow-list, which is the intended friction.
`backend/tests/unit/test_tracing.py` and
`backend/tests/contract/test_tracing_surface.py` fail if that filter weakens.

## Correlating with logs

Every structured log line emitted inside a span carries `trace_id`, alongside the
existing `correlation_id`, `tenant_id` and `user_id`. To move from an alert to a
trace: take `trace_id` from the log line and open it in the collector's backend.

## Before claiming this in production

A deployed collector, a retention and access decision for trace data (traces are
operational telemetry but still tenant-attributable), and a sampling review under
real load. None of these exist yet — see `docs/RELEASE-BLOCKERS.md`.
