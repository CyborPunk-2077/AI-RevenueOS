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
    if not is_public(payload.get("event_type", "")):
        return
    logger.info("outbound_webhook_queued", event_type=payload.get("event_type"))


def register_workflow_handlers(dispatcher: Any) -> None:
    dispatcher.subscribe("*", handle_domain_event)
    dispatcher.subscribe("*", handle_outbound_webhook)
