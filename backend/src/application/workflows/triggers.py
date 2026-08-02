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
    """Match one durable event and create each workflow execution exactly once."""
    from uuid import UUID

    from sqlalchemy import select

    from domain.tenants.entitlements import Feature, check_feature
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.database.models.workflows import WorkflowDefinition, WorkflowVersion
    from infrastructure.database.session import tenant_session
    from shared.settings import get_settings

    event_type = str(payload.get("event_type") or "")
    if event_type not in ALL_EVENT_TYPES:
        logger.warning("unknown_event_type", event_type=event_type)
        return
    try:
        tenant_id = UUID(str(payload["tenant_id"]))
        event_id = UUID(str(payload["event_id"]))
    except (KeyError, TypeError, ValueError):
        logger.warning("workflow_trigger_invalid_event", event_type=event_type)
        return

    cfg = get_settings()
    async with tenant_session(tenant_id) as session:
        tenant = await session.get(Tenant, tenant_id)
        if tenant is None:
            return
        decision = check_feature(
            tenant.plan_code,
            Feature.WORKFLOWS,
            flag_enabled=cfg.features.workflows_enabled,
        )
        if not decision.allowed:
            logger.info("workflow_trigger_disabled", tenant_id=str(tenant_id))
            return
        rows = (
            await session.execute(
                select(WorkflowDefinition, WorkflowVersion)
                .join(
                    WorkflowVersion,
                    WorkflowVersion.id == WorkflowDefinition.active_version_id,
                )
                .where(
                    WorkflowDefinition.is_active.is_(True),
                    WorkflowDefinition.kill_switch.is_(False),
                    WorkflowDefinition.paused_at.is_(None),
                    WorkflowDefinition.deleted_at.is_(None),
                    WorkflowVersion.status == "published",
                )
            )
        ).all()

    queued = 0
    for definition, version in rows:
        document = dict(version.content or {})
        if not _matches_trigger(dict(document.get("trigger") or {}), payload):
            continue
        if await _create_triggered_execution(
            tenant_id=tenant_id,
            event_id=event_id,
            payload=payload,
            definition=definition,
            version=version,
        ):
            queued += 1
    logger.info(
        "workflow_triggers_queued",
        event_type=event_type,
        tenant_id=str(tenant_id),
        event_id=str(event_id),
        execution_count=queued,
    )


def _matches_trigger(trigger: dict[str, Any], payload: dict[str, Any]) -> bool:
    event_type = str(payload.get("event_type") or "")
    trigger_type = str(trigger.get("type") or "")
    explicit = trigger.get("event_types") or trigger.get("event_type")
    if isinstance(explicit, str) and explicit != event_type:
        return False
    if isinstance(explicit, list) and event_type not in {str(value) for value in explicit}:
        return False

    resource = dict(payload.get("resource") or {})
    entity_type = str(resource.get("type") or "")
    configured_entity = str(trigger.get("entity") or "")
    if configured_entity and configured_entity != entity_type:
        return False
    if trigger_type == "entity.created":
        matched = event_type.endswith(".created") or event_type in {
            "lead.created",
            "contact.created",
        }
    elif trigger_type == "entity.updated":
        matched = event_type.endswith(".updated")
    elif trigger_type == "entity.field_changed":
        raw_changed = dict(payload.get("data") or {}).get("changed", [])
        if isinstance(raw_changed, str):
            changed = {raw_changed}
        elif isinstance(raw_changed, list):
            changed = {str(value) for value in raw_changed}
        else:
            changed = set()
        matched = event_type.endswith(".updated") and (
            not trigger.get("field") or str(trigger["field"]) in changed
        )
    elif trigger_type == "deal.stage_changed":
        matched = event_type == "opportunity.stage_changed"
    elif trigger_type == "message.inbound":
        matched = event_type == "conversation.message_received"
    elif trigger_type == "payment.event":
        matched = event_type.startswith("payment.")
    elif trigger_type == "appointment.event":
        matched = event_type.startswith("appointment.")
    elif trigger_type == "document.event":
        matched = event_type.startswith("document.")
    elif trigger_type == "approval.event":
        matched = event_type.startswith("approval.")
    else:
        # Manual, schedules, custom webhooks and aggregate thresholds enter
        # through their own authenticated/durable surfaces, not domain fan-out.
        matched = False
    return matched


async def _create_triggered_execution(
    *,
    tenant_id: Any,
    event_id: Any,
    payload: dict[str, Any],
    definition: Any,
    version: Any,
) -> bool:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from application.workflows.executor import execution_idempotency_key
    from domain.base import DomainEvent
    from domain.events.catalog import WORKFLOW_EXECUTION_STARTED
    from infrastructure.celery.context import build_headers
    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.models.workflows import WorkflowExecution
    from infrastructure.database.session import tenant_session
    from shared.utils.ids import uuid7

    key = execution_idempotency_key(
        workflow_id=definition.id,
        version_id=version.id,
        trigger_event_id=event_id,
    )
    execution_id = uuid7()
    resource = dict(payload.get("resource") or {})
    entity = {
        **dict(payload.get("data") or {}),
        "id": resource.get("id"),
        "type": resource.get("type"),
    }
    created = False
    async with tenant_session(tenant_id) as session:
        inserted = await session.execute(
            pg_insert(WorkflowExecution)
            .values(
                id=execution_id,
                tenant_id=tenant_id,
                workflow_id=definition.id,
                version_id=version.id,
                content_hash=version.content_hash,
                trigger_type=str(dict(version.content or {}).get("trigger", {}).get("type")),
                trigger_event_id=event_id,
                trigger_payload=payload,
                context={"entity": entity},
                state="pending",
                idempotency_key=key,
                correlation_id=payload.get("correlation_id"),
            )
            .on_conflict_do_nothing(index_elements=["tenant_id", "idempotency_key"])
            .returning(WorkflowExecution.id)
        )
        actual_id = inserted.scalar_one_or_none()
        if actual_id is not None:
            created = True
            event = DomainEvent(
                event_type=WORKFLOW_EXECUTION_STARTED,
                tenant_id=tenant_id,
                resource_type="workflow_execution",
                resource_id=actual_id,
                actor_type="workflow",
                correlation_id=payload.get("correlation_id"),
                payload={
                    "workflow_id": str(definition.id),
                    "version_id": str(version.id),
                    "trigger_event_id": str(event_id),
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
        else:
            existing = (
                await session.execute(
                    select(WorkflowExecution).where(WorkflowExecution.idempotency_key == key)
                )
            ).scalar_one()
            actual_id = existing.id
            created = existing.state == "pending"

    if created:
        from infrastructure.celery.tasks.workflow import execute_workflow

        execute_workflow.apply_async(
            args=[str(actual_id)],
            headers=build_headers(
                tenant_id=tenant_id,
                correlation_id=payload.get("correlation_id"),
                actor_type="workflow",
            ),
        )
    return created


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
