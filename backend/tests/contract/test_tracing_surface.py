"""The server span at the HTTP edge: template routes, no query strings, no borrowed traces."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from infrastructure.observability import tracing

pytestmark = pytest.mark.contract

FOREIGN_TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
FOREIGN_TRACEPARENT = f"00-{FOREIGN_TRACE_ID}-00f067aa0ba902b7-01"


@pytest.fixture
def exported(monkeypatch: pytest.MonkeyPatch) -> Iterator[InMemorySpanExporter]:
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(tracing, "tracer", lambda: provider.get_tracer(tracing.TRACER_NAME))
    yield exporter
    provider.shutdown()


def server_span(exporter: InMemorySpanExporter) -> ReadableSpan:
    spans = [s for s in exporter.get_finished_spans() if s.kind is SpanKind.SERVER]
    assert len(spans) == 1, f"expected one server span, got {len(spans)}"
    return spans[0]


def _denied_request(client: TestClient, viewer_headers: dict[str, str]) -> Any:
    """A request that is refused at the permission check, so it never reaches the database."""
    return client.post(
        "/v1/leads?email=asha@example.in&token=sk-live-abcdef",
        headers=viewer_headers,
        json={"first_name": "Asha", "email": "asha@example.in"},
    )


class TestServerSpan:
    def test_span_names_the_route_template_not_the_url(
        self, client: TestClient, viewer_headers: dict[str, str], exported: InMemorySpanExporter
    ) -> None:
        assert _denied_request(client, viewer_headers).status_code == 403

        span = server_span(exported)
        attributes = dict(span.attributes or {})
        assert span.name == "POST /v1/leads"
        assert attributes["http.route"] == "/v1/leads"
        assert attributes["http.request.method"] == "POST"
        assert attributes["http.response.status_code"] == 403

    def test_no_part_of_the_query_string_or_body_reaches_the_span(
        self, client: TestClient, viewer_headers: dict[str, str], exported: InMemorySpanExporter
    ) -> None:
        """Query strings carry tokens and addresses; a span must not become a copy of one."""
        _denied_request(client, viewer_headers)

        rendered = server_span(exported).to_json()
        assert "asha@example.in" not in rendered
        assert "sk-live-abcdef" not in rendered
        assert "Bearer" not in rendered

    def test_the_correlation_id_ties_the_span_to_the_logs(
        self, client: TestClient, viewer_headers: dict[str, str], exported: InMemorySpanExporter
    ) -> None:
        response = _denied_request(client, viewer_headers)
        correlation_id = response.headers["X-Request-ID"]

        assert dict(server_span(exported).attributes or {})["correlation.id"] == correlation_id

    def test_a_client_supplied_traceparent_is_ignored_by_default(
        self, client: TestClient, viewer_headers: dict[str, str], exported: InMemorySpanExporter
    ) -> None:
        """Trusting `traceparent` from the open internet lets a caller pick its own trace id."""
        client.post(
            "/v1/leads",
            headers={**viewer_headers, "traceparent": FOREIGN_TRACEPARENT},
            json={"first_name": "Asha", "email": "asha@example.in"},
        )

        assert format(server_span(exported).context.trace_id, "032x") != FOREIGN_TRACE_ID
