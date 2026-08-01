"""Idempotency-Key handling for externally repeatable creates. Retained 24 hours."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from fastapi import Header, Request

from infrastructure.caching.redis import TTL_IDEMPOTENCY, Cache, tenant_key
from shared.exceptions import IdempotencyConflict

MAX_KEY_LENGTH = 200


@dataclass(frozen=True, slots=True)
class IdempotencyContext:
    key: str | None
    scope: str
    request_hash: str
    tenant_id: str

    @property
    def active(self) -> bool:
        return self.key is not None

    def cache_key(self) -> str:
        return tenant_key(self.tenant_id, "idem", self.scope, self.key or "")


def hash_request(payload: Any) -> str:
    from shared.utils.text import canonical_json

    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


async def check_and_reserve(
    ctx: IdempotencyContext, cache: Cache | None = None
) -> dict[str, Any] | None:
    """Return a stored response for a repeat, or reserve the key for a first attempt."""
    if not ctx.active:
        return None
    store = cache or Cache()
    existing = await store.get_json(ctx.cache_key())
    if existing is None:
        await store.set_json(
            ctx.cache_key(),
            {"state": "in_progress", "request_hash": ctx.request_hash},
            TTL_IDEMPOTENCY,
        )
        return None
    if existing.get("request_hash") != ctx.request_hash:
        raise IdempotencyConflict(
            "This idempotency key was already used with a different payload.",
            details={"scope": ctx.scope},
        )
    if existing.get("state") == "in_progress":
        raise IdempotencyConflict(
            "A request with this idempotency key is still being processed.",
            details={"scope": ctx.scope, "retry_after": 2},
        )
    return dict(existing.get("response") or {})


async def store_response(
    ctx: IdempotencyContext, status: int, body: dict[str, Any], cache: Cache | None = None
) -> None:
    if not ctx.active:
        return
    await (cache or Cache()).set_json(
        ctx.cache_key(),
        {
            "state": "completed",
            "request_hash": ctx.request_hash,
            "response": {"status": status, "body": body},
        },
        TTL_IDEMPOTENCY,
    )


async def idempotency(
    request: Request,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> IdempotencyContext:
    principal = getattr(request.state, "principal", None)
    tenant_id = str(getattr(principal, "tenant_id", "public"))
    key = (idempotency_key or "").strip()[:MAX_KEY_LENGTH] or None
    try:
        payload = await request.json() if request.method in ("POST", "PUT", "PATCH") else {}
    except Exception:
        payload = {}
    return IdempotencyContext(
        key=key,
        scope=f"{request.method}:{request.url.path}",
        request_hash=hash_request(payload),
        tenant_id=tenant_id,
    )


def parse_if_match(if_match: str | None = Header(default=None, alias="If-Match")) -> int | None:
    """Optimistic concurrency: a mismatch is a 412, never a silent overwrite."""
    if not if_match:
        return None
    cleaned = if_match.strip().removeprefix("W/").strip('"')
    return int(cleaned) if cleaned.isdigit() else None
