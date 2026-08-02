"""Outbound webhook delivery with signed payloads, bounded retries and a DLQ."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any

from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.base import airev_task
from infrastructure.logging.setup import get_logger

logger = get_logger("celery.webhook")

MAX_DELIVERY_ATTEMPTS = 5  # five attempts over 24 hours, per the specification
RETRY_DELAYS_SECONDS = (60, 900, 3600, 21_600)


@airev_task("webhook.sweep_pending_deliveries", tenant_scoped=False, max_attempts=1)
async def sweep_pending_deliveries(_context: TaskContext) -> dict[str, Any]:
    """Re-drive outbound webhook deliveries whose backoff has elapsed (every 60 s)."""
    from sqlalchemy import select

    from infrastructure.celery.context import build_headers
    from infrastructure.database.models.workflows import OutboundWebhookDelivery
    from infrastructure.database.session import platform_session
    from shared.utils.timeutil import utcnow

    queued = 0
    async with platform_session("webhook_delivery_sweep") as session:
        due = (
            (
                await session.execute(
                    select(OutboundWebhookDelivery)
                    .where(
                        OutboundWebhookDelivery.status.in_(("pending", "processing")),
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
    return await _deliver_once(context, delivery_id)


async def _deliver_once(
    context: TaskContext,
    delivery_id: str,
    *,
    sender: Callable[..., Awaitable[Any]] | None = None,
) -> dict[str, Any]:
    """Claim, deliver and durably classify a single attempt."""
    from uuid import UUID

    from sqlalchemy import select

    from application.audit.recorder import AuditRecorder
    from domain.base import DomainEvent
    from domain.events.catalog import SYSTEM_INTEGRATION_DISCONNECTED
    from infrastructure.auth.encryption import EnvelopeEncryptor
    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.models.workflows import (
        OutboundWebhookConfig,
        OutboundWebhookDelivery,
    )
    from infrastructure.database.session import tenant_session
    from infrastructure.integrations.webhook import WebhookResult, send_webhook
    from shared.exceptions import ValidationError
    from shared.settings import get_settings
    from shared.utils.timeutil import utcnow

    tenant_id = context.require_tenant()

    async with tenant_session(tenant_id) as session:
        delivery = (
            await session.execute(
                select(OutboundWebhookDelivery)
                .where(OutboundWebhookDelivery.id == UUID(delivery_id))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if delivery is None:
            raise ValidationError("Delivery not found.")
        if delivery.status == "delivered":
            return {"delivered": True, "duplicate": True}
        if (
            delivery.status == "processing"
            and delivery.next_attempt_at is not None
            and delivery.next_attempt_at > utcnow()
        ):
            return {"delivered": False, "in_progress": True}

        config = (
            await session.execute(
                select(OutboundWebhookConfig).where(OutboundWebhookConfig.id == delivery.config_id)
            )
        ).scalar_one_or_none()
        if config is None or not config.is_active or config.disabled_at is not None:
            delivery.status = "failed"
            delivery.next_attempt_at = None
            delivery.response_excerpt = "webhook configuration is inactive"
            return {"delivered": False, "terminal": True, "reason": "inactive_config"}

        delivery.attempts += 1
        attempts = delivery.attempts
        delivery.status = "processing"
        delivery.next_attempt_at = utcnow() + timedelta(minutes=2)
        url = config.url
        payload = dict(delivery.payload)
        idempotency_key = delivery.idempotency_key
        encrypted_secret = config.signing_secret_encrypted

    master_key = get_settings().encryption_master_key
    if not master_key:
        result = WebhookResult(False, False, error="ENCRYPTION_KEY_NOT_CONFIGURED")
    else:
        try:
            secret = EnvelopeEncryptor(master_key).decrypt_str(
                encrypted_secret, tenant_id=str(tenant_id)
            )
            transport = sender or send_webhook
            result = await transport(
                url=url,
                payload=payload,
                secret=secret,
                idempotency_key=idempotency_key,
            )
        except ValueError as exc:
            result = WebhookResult(False, True, error=f"INVALID_DESTINATION: {exc}")
        except Exception as exc:
            # Provider/network failures remain pending; validation/config failures
            # above are terminal and are never retried.
            result = WebhookResult(False, False, error=type(exc).__name__)

    async with tenant_session(tenant_id) as session:
        delivery = (
            await session.execute(
                select(OutboundWebhookDelivery)
                .where(OutboundWebhookDelivery.id == UUID(delivery_id))
                .with_for_update()
            )
        ).scalar_one()
        if delivery.status == "delivered":
            return {"delivered": True, "duplicate": True}
        if delivery.attempts != attempts:
            return {"delivered": False, "stale_attempt": True}
        config = (
            await session.execute(
                select(OutboundWebhookConfig)
                .where(OutboundWebhookConfig.id == delivery.config_id)
                .with_for_update()
            )
        ).scalar_one()
        delivery.response_status = result.status_code
        delivery.response_excerpt = (result.response_excerpt or result.error or "")[:1000]
        terminal = result.terminal or attempts >= MAX_DELIVERY_ATTEMPTS
        if result.delivered:
            delivery.status = "delivered"
            delivery.delivered_at = utcnow()
            delivery.next_attempt_at = None
            config.failure_count = 0
        else:
            config.failure_count += 1
            delivery.status = "failed" if terminal else "pending"
            delivery.next_attempt_at = (
                None
                if terminal
                else utcnow() + timedelta(seconds=RETRY_DELAYS_SECONDS[attempts - 1])
            )
            if config.failure_count >= 10 and config.is_active:
                config.is_active = False
                config.disabled_at = utcnow()
                AuditRecorder(session).record(
                    action="config.updated",
                    resource_type="outbound_webhook_config",
                    resource_id=config.id,
                    tenant_id=tenant_id,
                    actor_type="worker",
                    old_values={"is_active": True},
                    new_values={"is_active": False},
                    metadata={"reason": "delivery_failure_threshold"},
                )
                event = DomainEvent(
                    event_type=SYSTEM_INTEGRATION_DISCONNECTED,
                    tenant_id=tenant_id,
                    resource_type="outbound_webhook_config",
                    resource_id=config.id,
                    actor_type="worker",
                    correlation_id=context.correlation_id,
                    payload={
                        "provider": "outbound_webhook",
                        "reason": "delivery_failure_threshold",
                    },
                )
                session.add(
                    EventOutbox(
                        occurred_at=event.occurred_at,
                        event_id=event.event_id,
                        event_type=event.event_type,
                        tenant_id=event.tenant_id,
                        resource_type=event.resource_type,
                        resource_id=event.resource_id,
                        payload=event.to_outbox_payload(),
                        correlation_id=event.correlation_id,
                        attempts=0,
                    )
                )

    logger.info(
        "webhook_delivery_attempted",
        delivery_id=delivery_id,
        attempt=attempts,
        tenant_id=str(tenant_id),
        delivered=result.delivered,
        terminal=terminal,
    )
    return {
        "delivered": result.delivered,
        "attempt": attempts,
        "terminal": terminal,
        "status_code": result.status_code,
    }
