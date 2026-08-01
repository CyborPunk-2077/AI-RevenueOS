"""Cursor and page pagination primitives shared by every list endpoint."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50
MIN_PAGE_SIZE = 1


def clamp_page_size(value: int | None) -> int:
    if value is None:
        return DEFAULT_PAGE_SIZE
    return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, value))


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> dict[str, Any]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    except Exception as exc:
        raise ValueError("Malformed pagination cursor") from exc
    if not isinstance(data, dict):
        raise ValueError("Malformed pagination cursor")
    return data


@dataclass(slots=True)
class Page:
    items: list[Any] = field(default_factory=list)
    total: int | None = None
    next_cursor: str | None = None
    prev_cursor: str | None = None
    page_size: int = DEFAULT_PAGE_SIZE

    def meta(self) -> dict[str, Any]:
        return {
            "page_size": self.page_size,
            "total": self.total,
            "next_cursor": self.next_cursor,
            "prev_cursor": self.prev_cursor,
            "has_more": self.next_cursor is not None,
        }
