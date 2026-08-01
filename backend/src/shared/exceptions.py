"""Typed application exceptions with a stable public error code."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base for every deliberately raised application error."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500
    default_message = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)


class ValidationError(AppError):
    code = "VALIDATION_ERROR"
    http_status = 422
    default_message = "The request payload failed validation."


class Unauthenticated(AppError):
    code = "UNAUTHENTICATED"
    http_status = 401
    default_message = "Authentication is required."


class TokenExpired(AppError):
    code = "TOKEN_EXPIRED"
    http_status = 401
    default_message = "The access token has expired."


class Forbidden(AppError):
    code = "FORBIDDEN"
    http_status = 403
    default_message = "You do not have permission to perform this action."


class NotFound(AppError):
    code = "NOT_FOUND"
    http_status = 404
    default_message = "The requested resource was not found."


class Conflict(AppError):
    code = "CONFLICT"
    http_status = 409
    default_message = "The request conflicts with the current resource state."


class PreconditionFailed(AppError):
    code = "PRECONDITION_FAILED"
    http_status = 412
    default_message = "The resource was modified by someone else."


class RateLimited(AppError):
    code = "RATE_LIMITED"
    http_status = 429
    default_message = "Too many requests."


class FeatureNotAvailable(AppError):
    code = "FEATURE_NOT_AVAILABLE"
    http_status = 403
    default_message = "This feature is not available on the current plan."


class QuotaExceeded(AppError):
    code = "QUOTA_EXCEEDED"
    http_status = 429
    default_message = "The plan quota for this resource has been exhausted."


class ProviderUnavailable(AppError):
    code = "PROVIDER_UNAVAILABLE"
    http_status = 503
    default_message = "An upstream provider is unavailable. The action was queued or degraded."


class IdempotencyConflict(AppError):
    code = "IDEMPOTENCY_CONFLICT"
    http_status = 409
    default_message = "This idempotency key was already used with a different payload."


class TenantContextMissing(AppError):
    code = "FORBIDDEN"
    http_status = 403
    default_message = "No tenant context is bound to this operation."


ERROR_CODES = [
    "VALIDATION_ERROR",
    "UNAUTHENTICATED",
    "TOKEN_EXPIRED",
    "FORBIDDEN",
    "NOT_FOUND",
    "CONFLICT",
    "RATE_LIMITED",
    "FEATURE_NOT_AVAILABLE",
    "QUOTA_EXCEEDED",
    "PROVIDER_UNAVAILABLE",
    "IDEMPOTENCY_CONFLICT",
    "PRECONDITION_FAILED",
    "INTERNAL_ERROR",
]
