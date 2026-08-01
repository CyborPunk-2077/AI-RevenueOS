"""Shared primitive type aliases used across every layer."""

from __future__ import annotations

from typing import Any, NewType
from uuid import UUID

TenantId = NewType("TenantId", UUID)
UserId = NewType("UserId", UUID)
CorrelationId = NewType("CorrelationId", str)

JSONValue = Any
JSONObject = dict[str, Any]

__all__ = ["CorrelationId", "JSONObject", "JSONValue", "TenantId", "UserId"]
