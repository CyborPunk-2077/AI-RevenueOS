"""The single public response envelope. Every route returns this shape."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from shared.utils.timeutil import iso, utcnow

API_VERSION = "v1"


def _meta(request_id: str | None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "request_id": request_id or str(uuid4()),
        "timestamp": iso(utcnow()),
        "version": API_VERSION,
    }
    if extra:
        meta.update(extra)
    return meta


def success(
    data: Any = None,
    *,
    request_id: str | None = None,
    pagination: dict[str, Any] | None = None,
    meta_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    extra = dict(meta_extra or {})
    if pagination is not None:
        extra["pagination"] = pagination
    return {
        "success": True,
        "data": data if data is not None else {},
        "meta": _meta(request_id, extra),
    }


def failure(
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    return {
        "success": False,
        "error": {"code": code, "message": message, "details": details or {}},
        "meta": _meta(request_id),
    }
