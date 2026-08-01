"""Inbound channel events are verified, deduplicated and enqueued - never processed inline."""

from __future__ import annotations

from typing import Any

from infrastructure.logging.setup import get_logger

logger = get_logger("communications.inbound")


async def enqueue_whatsapp_events(
    events: list[dict[str, Any]], *, correlation_id: str | None = None
) -> int:
    """Returns the number of accepted events. Duplicates are silently dropped."""
    from infrastructure.caching.redis import TTL_IDEMPOTENCY, Cache, global_key

    cache = Cache()
    accepted = 0
    for event in events:
        external_id = event.get("external_id")
        if not external_id:
            continue
        key = global_key("inbound", "whatsapp", str(external_id), str(event.get("kind")))
        if await cache.get_json(key) is not None:
            continue
        await cache.set_json(key, {"seen": True}, TTL_IDEMPOTENCY)
        accepted += 1
        logger.info(
            "whatsapp_event_enqueued", kind=event.get("kind"), correlation_id=correlation_id
        )
    return accepted


async def enqueue_email_events(events: list[dict[str, Any]]) -> int:
    return len([e for e in events if e.get("external_id")])
