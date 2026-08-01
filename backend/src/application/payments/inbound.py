"""Verified Razorpay events are deduplicated then enqueued for asynchronous handling."""

from __future__ import annotations

from typing import Any

from domain.payments.state_machine import assert_transition
from infrastructure.logging.setup import get_logger

logger = get_logger("payments.inbound")


async def enqueue_razorpay_event(
    parsed: dict[str, Any], *, correlation_id: str | None = None
) -> bool:
    from infrastructure.caching.redis import TTL_IDEMPOTENCY, Cache, global_key

    event_id = parsed.get("external_event_id")
    if not event_id:
        return False
    cache = Cache()
    key = global_key("inbound", "razorpay", str(event_id))
    if await cache.get_json(key) is not None:
        return False
    await cache.set_json(key, {"seen": True}, TTL_IDEMPOTENCY)
    logger.info("razorpay_event_enqueued", event=parsed.get("event"), correlation_id=correlation_id)
    return True


def apply_status(current: str, event_status: str | None) -> str:
    """Transitions are validated; an out-of-order webhook is ignored, never applied."""
    if event_status is None:
        return current
    try:
        return assert_transition(current, event_status).value
    except Exception:
        logger.warning("razorpay_out_of_order_event", current=current, incoming=event_status)
        return current
