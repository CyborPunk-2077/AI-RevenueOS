"""Inbound channel events are verified, deduplicated and then actually recorded.

The dedupe here is the fast path: a Redis key per provider event id, which stops
Meta's retry storm before it reaches the database at all. It is not the only
guard - `whatsapp_ingest` checks the provider's message id against the messages
table too, because a cache that a restart empties is not where correctness should
live.

Processing happens in the request. That is a deliberate exception to "enqueue,
never process inline", and it is bounded: a handful of indexed queries and three
inserts, well inside the two seconds Meta allows before it retries. The
alternative - acknowledging and deferring - buys throughput this product does not
need yet, and costs the thing it does need, which is that a founder who sends a
test message can refresh the screen and see it.
"""

from __future__ import annotations

from typing import Any

from infrastructure.logging.setup import get_logger

logger = get_logger("communications.inbound")


async def enqueue_whatsapp_events(
    events: list[dict[str, Any]], *, correlation_id: str | None = None
) -> int:
    """Record inbound messages and delivery receipts. Returns how many were accepted.

    A duplicate is silently dropped, which is what a webhook retry deserves: Meta
    resends when our acknowledgement was slow, not because anything changed.
    """
    from application.communications.whatsapp_ingest import (
        ingest_inbound_message,
        ingest_status_update,
    )
    from infrastructure.caching.redis import TTL_IDEMPOTENCY, Cache, global_key

    cache = Cache()
    accepted = 0

    for event in events:
        external_id = event.get("external_id")
        kind = str(event.get("kind"))
        if not external_id:
            continue

        # The key has to separate the *states* of one message, not just its id.
        #
        # A single outbound message produces `sent`, then `delivered`, then
        # `read`, all carrying the same provider message id and all of kind
        # `status_update`. Keying on (id, kind) alone made them one event: the
        # first was recorded and the rest were silently dropped as duplicates, so
        # a message that genuinely reached somebody's phone sat in Sangam forever
        # saying only "sent". Observed in the live test - three callbacks arrived,
        # one was kept.
        state = str(event.get("status") or "") if kind == "status_update" else ""
        key = global_key("inbound", "whatsapp", str(external_id), kind, state)
        if await cache.get_json(key) is not None:
            continue

        if kind == "inbound_message":
            result = await ingest_inbound_message(event)
        elif kind == "status_update":
            result = await ingest_status_update(event)
        else:
            continue

        if not result.accepted:
            # Not cached. An event refused because no workspace owns that business
            # number must be retryable once the channel is configured, rather than
            # permanently swallowed by an idempotency key.
            logger.info("whatsapp_event_not_recorded", kind=kind, reason=result.reason)
            continue

        await cache.set_json(key, {"seen": True}, TTL_IDEMPOTENCY)
        accepted += 1
        logger.info("whatsapp_event_recorded", kind=kind, correlation_id=correlation_id)

    return accepted


async def enqueue_email_events(events: list[dict[str, Any]]) -> int:
    return len([e for e in events if e.get("external_id")])
