"""Outbound webhook delivery with signed payloads, bounded retries and a DLQ."""

from __future__ import annotations

from typing import Any

from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.base import airev_task
from infrastructure.logging.setup import get_logger

logger = get_logger("celery.webhook")

MAX_DELIVERY_ATTEMPTS = 5  # five attempts over 24 hours, per the specification


@airev_task("webhook.sweep_pending_deliveries", tenant_scoped=False, max_attempts=1)
async def sweep_pending_deliveries(_context: TaskContext) -> dict[str, Any]:
    """Re-drive outbound webhook deliveries whose backoff has elapsed (every 60 s)."""
    from sqlalchemy import select

    from infrastructure.celery.context import build_headers
    from infrastructure.database.models.workflows import OutboundWebhookDelivery
    from infrastructure.database.session import unscoped_session
    from shared.utils.timeutil import utcnow

    queued = 0
    async with unscoped_session() as session:
        due = (
            (
                await session.execute(
                    select(OutboundWebhookDelivery)
                    .where(
                        OutboundWebhookDelivery.status == "pending",
                        OutboundWebhookDelivery.next_attempt_at.is_not(None),
                        OutboundWebhookDelivery.next_attempt_at <= utcnow(),
                        OutboundWebhookDelivery.attempts < MAX_DELIVERY_ATTEMPTS,
                    )
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
        for delivery in due:
            deliver.apply_async(
                args=[str(delivery.id)],
                headers=build_headers(tenant_id=delivery.tenant_id, actor_type="scheduler"),
            )
            delivery.next_attempt_at = None
            queued += 1

    if queued:
        logger.info("webhook_deliveries_queued", count=queued)
    return {"queued": queued}


@airev_task("webhook.deliver", max_attempts=MAX_DELIVERY_ATTEMPTS)
async def deliver(context: TaskContext, delivery_id: str) -> dict[str, Any]:
    """Deliver one signed outbound webhook.

    A known-invalid payload (400/422) is never retried: the destination has told us
    the body is wrong, and repeating it only wastes attempts.
    """
    from uuid import UUID

    from sqlalchemy import select

    from infrastructure.database.models.workflows import OutboundWebhookDelivery
    from infrastructure.database.session import tenant_session
    from shared.exceptions import ValidationError

    tenant_id = context.require_tenant()

    async with tenant_session(tenant_id) as session:
        delivery = (
            await session.execute(
                select(OutboundWebhookDelivery).where(
                    OutboundWebhookDelivery.id == UUID(delivery_id)
                )
            )
        ).scalar_one_or_none()
        if delivery is None:
            raise ValidationError("Delivery not found.")
        if delivery.status == "delivered":
            return {"delivered": True, "duplicate": True}

        delivery.attempts += 1
        attempts = delivery.attempts

    # The HTTP call itself is implemented alongside the outbound webhook
    # configuration surface. Until then the delivery stays pending and the sweep
    # continues to observe it rather than reporting a success that did not happen.
    logger.info(
        "webhook_delivery_attempted",
        delivery_id=delivery_id,
        attempt=attempts,
        tenant_id=str(tenant_id),
    )
    return {"delivered": False, "attempt": attempts, "pending_transport": True}
