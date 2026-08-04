"""OpenTelemetry tracing that cannot carry tenant payloads or secrets.

Three deliberate constraints shape this module.

*No auto-instrumentation.* The `opentelemetry-instrumentation-*` packages attach
spans to FastAPI, SQLAlchemy and httpx automatically, and record full request
targets, SQL statement text and header values while doing it. That is precisely
the data classified P3/P4 in the specification, so spans here are opened by hand
at the boundaries that matter.

*An attribute allow-list.* `safe_attributes` drops any key that is not explicitly
listed, and re-checks every surviving key against the same secret/PII key sets the
log redactor uses. Values must be scalars; strings are scrubbed and truncated.
A caller cannot leak by accident, only by editing this file.

*No exception recording.* `Span.record_exception` writes `str(exc)` and a
stacktrace into the span. Exception messages routinely quote the offending value -
an email address, a row, a token prefix - so failures are recorded as the
exception *type* plus an error status, and nothing else. The message stays in the
redacted structured log, which knows how to handle it.

Tracing is fail-closed: without both `OTEL_ENABLED` and an exporter endpoint the
tracer provider is never installed and every span becomes a cheap no-op.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, Final

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, SpanKind, StatusCode, Tracer

from infrastructure.logging.redaction import _EMAIL, PII_KEYS, SECRET_KEYS, scrub_text

_LOG = logging.getLogger("infrastructure.observability")

TRACER_NAME: Final = "airevenueos"
MAX_ATTRIBUTE_CHARS: Final = 256

#: The only attribute keys that may reach a span. Anything else is dropped.
#: Identifiers are opaque UUIDs and correlate a trace with the structured logs and
#: audit trail; free text, payloads, queries and credentials have no entry here.
ALLOWED_ATTRIBUTES: Final = frozenset(
    {
        # correlation
        "correlation.id",
        "tenant.id",
        "user.id",
        "actor.type",
        # http server
        "http.request.method",
        "http.route",
        "http.response.status_code",
        # outbound providers
        "provider.name",
        "provider.operation",
        "provider.attempt",
        "provider.status_code",
        "provider.outcome",
        # background work
        "messaging.operation",
        "messaging.destination.name",
        "task.name",
        "task.attempt",
        "task.outcome",
        # persistence and the outbox
        "db.operation",
        "db.rows_affected",
        "outbox.event_type",
        "outbox.batch_size",
        # ai gateway: shape and cost, never prompt or completion text
        "ai.task",
        "ai.provider",
        "ai.model",
        "ai.tokens_input",
        "ai.tokens_output",
        "ai.cached",
        # generic outcome vocabulary
        "entity.type",
        "event.type",
        "workflow.id",
        "outcome",
        "error.type",
    }
)

_FORBIDDEN_FRAGMENTS: Final = frozenset(
    {k.lower() for k in SECRET_KEYS} | {k.lower() for k in PII_KEYS}
)

_provider_installed = False


def safe_attributes(attributes: Mapping[str, Any]) -> dict[str, str | bool | int | float]:
    """Reduce caller-supplied attributes to the subset that is safe to export."""
    safe: dict[str, str | bool | int | float] = {}
    for key, value in attributes.items():
        if key not in ALLOWED_ATTRIBUTES:
            continue
        # Defence in depth: an allow-list entry that later collides with a secret or
        # PII key name must still not export a value.
        leaf = key.rsplit(".", 1)[-1].lower()
        if leaf in _FORBIDDEN_FRAGMENTS or key.lower() in _FORBIDDEN_FRAGMENTS:
            continue
        if value is None or isinstance(value, bool | int | float):
            if value is not None:
                safe[key] = value
            continue
        if isinstance(value, str):
            if key in ("tenant.id", "user.id", "workflow.id", "correlation.id"):
                safe[key] = value
            else:
                safe[key] = _EMAIL.sub("[EMAIL]", scrub_text(value))[:MAX_ATTRIBUTE_CHARS]
            continue
        # Mappings, sequences and arbitrary objects are exactly how payloads leak.
    return safe


def configure_tracing(
    *,
    enabled: bool,
    endpoint: str | None,
    service_name: str,
    release: str,
    environment: str,
    sample_ratio: float = 0.05,
    export_timeout_ms: int = 5_000,
) -> bool:
    """Install the tracer provider. Returns whether spans will actually be exported.

    Idempotent, and safe to call when the SDK is present but unconfigured: without
    an endpoint no provider is installed, so `trace.get_tracer` keeps returning the
    API's no-op implementation.
    """
    global _provider_installed
    if _provider_installed:
        return True
    if not enabled or not endpoint:
        return False

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": release,
            "deployment.environment": environment,
        }
    )
    provider = TracerProvider(
        resource=resource, sampler=ParentBased(TraceIdRatioBased(sample_ratio))
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, timeout=max(1, export_timeout_ms // 1000))
        )
    )
    trace.set_tracer_provider(provider)
    _provider_installed = True
    _LOG.info("tracing_configured")
    return True


def shutdown_tracing(timeout_ms: int = 5_000) -> None:
    """Flush pending spans on shutdown. Never raises into the caller's shutdown path."""
    global _provider_installed
    provider = trace.get_tracer_provider()
    shutdown = getattr(provider, "shutdown", None)
    force_flush = getattr(provider, "force_flush", None)
    try:
        if callable(force_flush):
            force_flush(timeout_ms)
        if callable(shutdown):
            shutdown()
    except Exception:  # pragma: no cover - shutdown must not mask the real error
        _LOG.warning("tracing_shutdown_failed", exc_info=False)
    finally:
        _provider_installed = False


def tracing_enabled() -> bool:
    return _provider_installed


def tracer() -> Tracer:
    return trace.get_tracer(TRACER_NAME)


def current_trace_id() -> str | None:
    """The active trace id as 32 hex characters, for correlating logs with traces."""
    context = trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


def set_attributes(**attributes: Any) -> None:
    """Add allow-listed attributes to whatever span is currently active."""
    span = trace.get_current_span()
    if not span.is_recording():
        return
    for key, value in safe_attributes(attributes).items():
        span.set_attribute(key, value)


@contextmanager
def start_span(
    name: str,
    *,
    kind: SpanKind = SpanKind.INTERNAL,
    context: Context | None = None,
    **attributes: Any,
) -> Iterator[Span]:
    """Open a span whose attributes are filtered and whose errors carry no message."""
    with tracer().start_as_current_span(
        name,
        kind=kind,
        context=context,
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        for key, value in safe_attributes(attributes).items():
            span.set_attribute(key, value)
        try:
            yield span
        except BaseException as exc:
            _record_failure(span, exc)
            raise


def _record_failure(span: Span, exc: BaseException) -> None:
    """Record that a span failed, and the exception class - never its message."""
    if not span.is_recording():
        return
    span.set_attribute("error.type", type(exc).__name__)
    span.set_status(StatusCode.ERROR)

