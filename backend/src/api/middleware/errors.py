"""Maps every exception to the public failure envelope. Internals never leak."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.app.envelope import failure
from infrastructure.logging.setup import get_logger
from shared.exceptions import AppError

logger = get_logger("api.errors")

_HTTP_CODE_MAP = {
    400: "VALIDATION_ERROR",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "VALIDATION_ERROR",
    409: "CONFLICT",
    412: "PRECONDITION_FAILED",
    413: "VALIDATION_ERROR",
    415: "VALIDATION_ERROR",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    503: "PROVIDER_UNAVAILABLE",
}


def _rid(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        if exc.http_status >= 500:
            logger.error("app_error", code=exc.code, message=exc.message, details=exc.details)
        else:
            logger.info("app_error", code=exc.code, message=exc.message)
        headers = {}
        if exc.code == "RATE_LIMITED" and "retry_after" in exc.details:
            headers["Retry-After"] = str(exc.details["retry_after"])
        return JSONResponse(
            status_code=exc.http_status,
            content=failure(exc.code, exc.message, details=exc.details, request_id=_rid(request)),
            headers=headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ())[1:]) or "body",
                "reason": err.get("msg", "invalid"),
                "type": err.get("type", "value_error"),
            }
            for err in exc.errors()[:50]
        ]
        return JSONResponse(
            status_code=422,
            content=failure(
                "VALIDATION_ERROR",
                "The request payload failed validation.",
                details={"fields": fields},
                request_id=_rid(request),
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODE_MAP.get(exc.status_code, "INTERNAL_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request could not be completed."
        return JSONResponse(
            status_code=exc.status_code,
            content=failure(code, message, request_id=_rid(request)),
            headers=getattr(exc, "headers", None) or {},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content=failure(
                "INTERNAL_ERROR", "An unexpected error occurred.", request_id=_rid(request)
            ),
        )
