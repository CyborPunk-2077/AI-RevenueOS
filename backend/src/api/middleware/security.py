"""Security headers, body limits and CSRF enforcement for unsafe requests."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from api.app.envelope import failure

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, hsts: bool = False) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"
            )
        return response


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized JSON bodies before they are buffered."""

    def __init__(self, app: object, *, max_bytes: int) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._max = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in UNSAFE_METHODS:
            declared = request.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self._max:
                return JSONResponse(
                    status_code=413,
                    content=failure(
                        "VALIDATION_ERROR",
                        "Request body exceeds the permitted size.",
                        details={"max_bytes": self._max},
                    ),
                )
        return await call_next(request)


class OriginEnforcementMiddleware(BaseHTTPMiddleware):
    """Strict Origin/Referer fallback for unsafe cross-origin requests."""

    def __init__(
        self, app: object, *, allowed_origins: list[str], exempt_prefixes: tuple[str, ...] = ()
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._allowed = set(allowed_origins)
        self._exempt = exempt_prefixes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method in UNSAFE_METHODS and not request.url.path.startswith(self._exempt):
            origin = request.headers.get("origin")
            if origin is not None and (origin == "null" or origin not in self._allowed):
                return JSONResponse(
                    status_code=403,
                    content=failure("FORBIDDEN", "Origin is not permitted."),
                )
        return await call_next(request)
