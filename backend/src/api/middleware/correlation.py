"""Correlation, timing and structured access logging for every request."""

from __future__ import annotations

import time
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from infrastructure.logging.context import bind_context, reset_context
from infrastructure.logging.setup import get_logger

logger = get_logger("api.access")
_SAFE_ID_MAX = 128


class CorrelationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied = request.headers.get("X-Request-ID", "")
        correlation_id = (
            supplied[:_SAFE_ID_MAX] if supplied.isascii() and supplied else str(uuid4())
        )
        request.state.correlation_id = correlation_id
        tokens = bind_context(correlation_id=correlation_id)
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
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
