"""Tracing must be fail-closed, and must not carry tenant data or secrets.

The interesting assertions here are negative: given a caller who hands the tracer
an email address, a bearer token or a whole request payload, nothing recognisable
may survive onto the span. A span attribute is not redacted downstream the way a
log line is, so the filter in `safe_attributes` is the only thing standing between
a careless `set_attributes(**row)` and P3/P4 data sitting in a collector.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from infrastructure.celery.context import build_headers
from infrastructure.observability import tracing


@pytest.fixture
def exported(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    """Record spans in memory. Nothing here ever opens a socket."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "tracer", lambda: provider.get_tracer(tracing.TRACER_NAME))
    yield exporter
    provider.shutdown()


def only(exporter: InMemorySpanExporter) -> ReadableSpan:
    spans = exporter.get_finished_spans()
    assert len(spans) == 1, f"expected exactly one span, got {len(spans)}"
    return spans[0]


class TestFailClosed:
    def test_disabled_by_default(self) -> None:
        assert (
            tracing.configure_tracing(
                enabled=False,
                endpoint="http://collector:4318/v1/traces",
                service_name="api",
                release="0.24.0",
                environment="local",
            )
            is False
        )
        assert tracing.tracing_enabled() is False

    def test_enabled_without_an_endpoint_exports_nothing(self) -> None:
        assert (
            tracing.configure_tracing(
                enabled=True,
                endpoint=None,
                service_name="api",
                release="0.24.0",
                environment="local",
            )
            is False
        )
        assert tracing.tracing_enabled() is False

    def test_spans_are_harmless_when_tracing_is_off(self) -> None:
        """An unconfigured process still runs the instrumented code paths."""
        with tracing.start_span("task noop", **{"task.name": "noop"}):
            tracing.set_attributes(**{"outcome": "ok"})
        assert tracing.current_trace_id() is None


class TestAttributeFilter:
    def test_unlisted_keys_are_dropped(self) -> None:
        safe = tracing.safe_attributes(
            {"http.route": "/v1/leads/{lead_id}", "sql": "SELECT * FROM app.leads"}
        )
        assert safe == {"http.route": "/v1/leads/{lead_id}"}

    @pytest.mark.parametrize(
        "attributes",
        [
            {"password": "hunter2"},
            {"authorization": "Bearer abc.def.ghi"},
            {"jwt_private_key": "-----BEGIN PRIVATE KEY-----"},
            {"email": "asha@example.in"},
            {"phone": "+919812345678"},
        ],
    )
    def test_secret_and_pii_keys_never_survive(self, attributes: dict[str, Any]) -> None:
        assert tracing.safe_attributes(attributes) == {}

    def test_structured_values_are_dropped_whole(self) -> None:
        """A payload smuggled in under an allowed key is still a payload."""
        assert tracing.safe_attributes({"outcome": {"email": "asha@example.in"}}) == {}
        assert tracing.safe_attributes({"outcome": ["asha@example.in"]}) == {}

    def test_free_text_is_scrubbed_and_truncated(self) -> None:
        safe = tracing.safe_attributes({"outcome": "mailed asha@example.in about ABCDE1234F"})
        value = safe["outcome"]
        assert isinstance(value, str)
        assert "asha@example.in" not in value
        assert "ABCDE1234F" not in value

        long = tracing.safe_attributes({"outcome": "x" * 5_000})["outcome"]
        assert isinstance(long, str) and len(long) == tracing.MAX_ATTRIBUTE_CHARS

    def test_identifiers_are_kept_because_operations_needs_them(self) -> None:
        tenant = "01890000-0000-7000-8000-00000000000a"
        safe = tracing.safe_attributes({"tenant.id": tenant, "http.response.status_code": 201})
        assert safe == {"tenant.id": tenant, "http.response.status_code": 201}

    def test_none_is_omitted_rather_than_exported_as_a_string(self) -> None:
        assert tracing.safe_attributes({"tenant.id": None}) == {}


class TestSpanRecording:
    def test_allowed_attributes_reach_the_span(self, exported: InMemorySpanExporter) -> None:
        with tracing.start_span(
            "GET /v1/leads",
            kind=SpanKind.SERVER,
            **{"http.request.method": "GET", "http.route": "/v1/leads", "secret": "s3cr3t"},
        ):
            tracing.set_attributes(**{"http.response.status_code": 200})

        span = only(exported)
        assert span.name == "GET /v1/leads"
        assert span.kind is SpanKind.SERVER
        assert dict(span.attributes or {}) == {
            "http.request.method": "GET",
            "http.route": "/v1/leads",
            "http.response.status_code": 200,
        }

    def test_failure_records_the_type_and_never_the_message(
        self, exported: InMemorySpanExporter
    ) -> None:
        """Exception messages quote the offending value; the span must not."""

        class DuplicateContact(ValueError):
            pass

        with pytest.raises(DuplicateContact):
            with tracing.start_span("contact create", **{"entity.type": "contact"}):
                raise DuplicateContact("asha@example.in already exists in tenant 0189...")

        span = only(exported)
        assert (span.attributes or {}).get("error.type") == "DuplicateContact"
        assert span.status.status_code is trace.StatusCode.ERROR
        assert span.status.description is None
        assert len(span.events) == 0

        rendered = str(span.to_json())
        assert "asha@example.in" not in rendered
        assert "already exists" not in rendered

    def test_trace_id_is_exposed_for_log_correlation(self, exported: InMemorySpanExporter) -> None:
        with tracing.start_span("task noop"):
            trace_id = tracing.current_trace_id()
            assert trace_id is not None and len(trace_id) == 32
            assert int(trace_id, 16) != 0
        assert trace_id == format(only(exported).context.trace_id, "032x")


class TestPropagation:
    def test_enqueueing_inside_a_span_carries_the_trace_to_the_worker(
        self, exported: InMemorySpanExporter
    ) -> None:
        with tracing.start_span("POST /v1/leads", kind=SpanKind.SERVER):
            headers = build_headers(correlation_id="corr-1", actor_type="system")
            traceparent = headers.get("traceparent")

        assert isinstance(traceparent, str)
        assert format(only(exported).context.trace_id, "032x") in traceparent

    def test_enqueueing_without_a_span_adds_no_trace_headers(self) -> None:
        """Tracing off must not change what a producer puts on the wire."""
        assert "traceparent" not in build_headers(correlation_id="corr-1")
