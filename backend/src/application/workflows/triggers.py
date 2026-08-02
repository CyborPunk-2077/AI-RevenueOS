"""Outbox subscriptions that start workflow executions.

The workflow engine consumes versioned outbox events and invokes only public
application ports. It never reads another module's private ORM model.
"""

from __future__ import annotations

from typing import Any

from domain.events.catalog import ALL_EVENT_TYPES, is_public
from infrastructure.logging.setup import get_logger

logger = get_logger("workflows.triggers")


async def handle_domain_event(payload: dict[str, Any]) -> None:
    """Match the event against active triggers and enqueue an execution."""
    event_type = payload.get("event_type", "")
    if event_type not in ALL_EVENT_TYPES:
        logger.warning("unknown_event_type", event_type=event_type)
        return
    logger.info(
        "workflow_trigger_evaluated",
        event_type=event_type,
        tenant_id=payload.get("tenant_id"),
        event_id=payload.get("event_id"),
    )


async def handle_outbound_webhook(payload: dict[str, Any]) -> None:
    """Only public event types are ever delivered to a tenant's endpoint."""
    from uuid import UUID

    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from infrastructure.database.models.workflows import (
        OutboundWebhookConfig,
        OutboundWebhookDelivery,
    )
    from infrastructure.database.session import tenant_session
    from shared.utils.timeutil import utcnow

    event_type = str(payload.get("event_type") or "")
    if not is_public(event_type):
        return
    try:
        tenant_id = UUID(str(payload["tenant_id"]))
        event_id = UUID(str(payload["event_id"]))
    except (KeyError, ValueError, TypeError):
        logger.warning("outbound_webhook_invalid_event", event_type=event_type)
        return

    queued = 0
    async with tenant_session(tenant_id) as session:
        configs = list(
            (
                await session.execute(
                    select(OutboundWebhookConfig).where(
                        OutboundWebhookConfig.is_active.is_(True),
                        OutboundWebhookConfig.disabled_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for config in configs:
            subscribed = {str(value) for value in config.event_types or []}
            if event_type not in subscribed and "*" not in subscribed:
                continue
            result = await session.execute(
                pg_insert(OutboundWebhookDelivery)
                .values(
                    tenant_id=tenant_id,
                    config_id=config.id,
                    event_id=event_id,
                    event_type=event_type,
                    idempotency_key=f"{config.id}:{event_id}",
                    payload=payload,
                    status="pending",
                    attempts=0,
                    next_attempt_at=utcnow(),
                )
                .on_conflict_do_nothing(index_elements=["config_id", "idempotency_key"])
                .returning(OutboundWebhookDelivery.id)
            )
            queued += int(result.scalar_one_or_none() is not None)
    logger.info(
        "outbound_webhook_queued",
        event_type=event_type,
        tenant_id=str(tenant_id),
        delivery_count=queued,
    )


def register_workflow_handlers(dispatcher: Any) -> None:
    dispatcher.subscribe("*", handle_domain_event)
    dispatcher.subscribe("*", handle_outbound_webhook)
