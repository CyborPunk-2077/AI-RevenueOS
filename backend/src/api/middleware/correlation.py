"""Correlation, timing and structured access logging for every request."""

from __future__ import annotations

import time
from uuid import uuid4

from opentelemetry.propagate import extract
from opentelemetry.trace import SpanKind
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from infrastructure.logging.context import bind_context, reset_context
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import set_attributes, start_span

logger = get_logger("api.access")
_SAFE_ID_MAX = 128


class CorrelationMiddleware(BaseHTTPMiddleware):
    """Correlation id, access log and the server span for one request.

    Incoming `traceparent` headers are ignored unless `trust_incoming_context` is
    set. A public endpoint will otherwise let any caller choose the trace id its
    request is filed under, which is a cheap way to pollute or correlate against
    someone else's trace. Behind a trusted ingress the flag is safe and gives an
    end-to-end trace from the BFF onwards.
    """

    def __init__(self, app: ASGIApp, *, trust_incoming_context: bool = False) -> None:
        super().__init__(app)
        self._trust_incoming_context = trust_incoming_context

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        correlation_id = (
            supplied[:_SAFE_ID_MAX] if supplied.isascii() and supplied else str(uuid4())
        )
        request.state.correlation_id = correlation_id
        tokens = bind_context(correlation_id=correlation_id)
        parent = extract(dict(request.headers)) if self._trust_incoming_context else None
        started = time.perf_counter()
        status = 500
        try:
            # The span name and route attribute use the matched template, never the
            # raw path: `/v1/leads/{lead_id}` carries no identifier, `/v1/leads/018f...`
            # does, and high-cardinality span names are useless anyway.
            with start_span(
                f"{request.method} {request.url.path}",
                kind=SpanKind.SERVER,
                context=parent,
                **{"http.request.method": request.method, "correlation.id": correlation_id},
            ) as span:
                response = await call_next(request)
                status = response.status_code
                route = request.scope.get("route")
                template = getattr(route, "path", None)
                if template:
                    if not template.startswith("/v1") and request.url.path.startswith("/v1"):
                        is_abs = template.startswith("/")
                        template = f"/v1{template}" if is_abs else f"/v1/{template}"
                    span.update_name(f"{request.method} {template}")
                set_attributes(
                    **{"http.route": template or "", "http.response.status_code": status}
                )
                response.headers["X-Request-ID"] = correlation_id
                return response
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            logger.info(
                "http_request",
                method=request.method,
                path=request.url.path,
                status=status,
                duration_ms=duration_ms,
            )
            reset_context(tokens)
