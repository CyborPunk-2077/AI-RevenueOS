"""Tenant-authorized workflow action dispatch with durable duplicate recovery.

Every database mutation used here writes an audit row in the same transaction as
its state change.  The audit correlation is a stable hash of execution and node,
so it is also the durable action receipt when Redis is empty or a worker dies after
commit.  A PostgreSQL advisory lock serializes concurrent attempts for that receipt.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from domain.auth.permissions import Scope


@dataclass(frozen=True, slots=True)
class AutomationPrincipal:
    user_id: UUID
    tenant_id: UUID
    tenant_slug: str
    email: str
    name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    scope: Scope
    plan_code: str
    branch_ids: frozenset[str] = frozenset()
    team_ids: frozenset[str] = frozenset()

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            from shared.exceptions import Forbidden

            raise Forbidden(
                "The workflow publisher no longer has permission for this action.",
                details={"required_permission": permission},
            )


AUDIT_ACTIONS: dict[str, tuple[str, ...]] = {
    "lead.create": ("lead.create",),
    "lead.update": ("lead.update",),
    "lead.assign": ("lead.update",),
    "contact.create": ("contact.create",),
    "contact.update": ("contact.update",),
    "deal.create": ("deal.create",),
    "deal.update": ("deal.update",),
    "deal.move_stage": ("deal.stage_change",),
    "task.create": ("task.create",),
    "tag.add": ("contact.update",),
    "tag.remove": ("contact.update",),
    "note.create": ("note.create",),
    "activity.create": ("activity.log",),
    "message.send_whatsapp": ("message.queue",),
    "message.send_email": ("message.queue",),
    "message.send_sms": ("message.queue",),
    "notification.in_app": ("notification.create",),
    "appointment.create": ("appointment.book",),
    "appointment.cancel": ("appointment.cancel",),
    "document.generate": ("document.create",),
    "webhook.call": ("webhook.call",),
    "ai.task": ("ai.task",),
    "analytics.emit": ("analytics.emit",),
}

ACTION_FEATURES = {
    "message.send_whatsapp": "whatsapp",
    "message.send_email": "email",
    "message.send_sms": "sms",
    "appointment.create": "appointments",
    "appointment.cancel": "appointments",
    "document.generate": "documents",
    "document.send": "signatures",
    "payment.create_link": "payments",
    "payment.refund": "payments",
    "webhook.call": "outbound_webhooks",
    "ai.task": "ai_qualification",
}


def action_correlation(idempotency_key: str) -> str:
    """One receipt across retry attempts, without exceeding audit varchar(128)."""
    logical_key = idempotency_key.rsplit(":", 1)[0]
    return "wfa:" + hashlib.sha256(logical_key.encode()).hexdigest()


async def dispatch_action(
    action: str,
    inputs: dict[str, Any],
    ctx: Any,
    idempotency_key: str,
    *,
    settings: Any | None = None,
) -> dict[str, Any]:
    from domain.workflows.dsl import ACTION_CATALOG
    from shared.settings import get_settings

    spec = ACTION_CATALOG[action]
    cfg = settings or get_settings()
    principal = await load_automation_principal(ctx.tenant_id, ctx.workflow_id)
    try:
        principal.require(spec.permission)
    except Exception as exc:
        from application.workflows.executor import TerminalActionError

        raise TerminalActionError(str(exc)) from exc

    feature = ACTION_FEATURES.get(action)
    flag_enabled = (
        bool(getattr(cfg.features, spec.feature_flag, False)) if spec.feature_flag else True
    )
    if feature:
        from domain.tenants.entitlements import check_feature

        decision = check_feature(principal.plan_code, feature, flag_enabled=flag_enabled)
    else:
        decision = None
    if (decision is not None and not decision.allowed) or (spec.feature_flag and not flag_enabled):
        from application.workflows.executor import TerminalActionError

        reason = decision.message if decision is not None else None
        raise TerminalActionError(reason or f"action '{action}' is disabled until activated")

    if action in {"message.send_whatsapp", "message.send_email", "message.send_sms"}:
        configured = False
        if action == "message.send_whatsapp":
            from application.communications.registry import get_whatsapp_adapter

            configured = get_whatsapp_adapter(cfg).is_configured()
        elif action == "message.send_email":
            from application.communications.registry import get_email_adapter

            configured = get_email_adapter(cfg).is_configured()
        if not configured:
            from application.workflows.executor import TerminalActionError

            raise TerminalActionError(
                f"action '{action}' is not configured; no message was delivered"
            )

    expected_audits = AUDIT_ACTIONS.get(action)
    if expected_audits is None:
        from application.workflows.executor import TerminalActionError

        raise TerminalActionError(
            f"action '{action}' is unavailable until its external activation is complete"
        )

    correlation = action_correlation(idempotency_key)
    return await _execute_once(
        action=action,
        inputs=_coerce_inputs(inputs),
        ctx=ctx,
        principal=principal,
        correlation=correlation,
        expected_audits=expected_audits,
    )


async def load_automation_principal(tenant_id: UUID, workflow_id: UUID) -> AutomationPrincipal:
    """Resolve the current publisher and current grants; no permission snapshot."""
    from sqlalchemy import select

    from infrastructure.database.models.tenancy import TeamMember, Tenant
    from infrastructure.database.models.users import (
        Role,
        RolePermission,
        User,
        UserRole,
    )
    from infrastructure.database.models.workflows import WorkflowDefinition
    from infrastructure.database.session import tenant_session
    from shared.exceptions import Forbidden, NotFound

    async with tenant_session(tenant_id) as session:
        workflow = (
            await session.execute(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.id == workflow_id,
                    WorkflowDefinition.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if workflow is None:
            raise NotFound("Workflow not found.")
        if not workflow.is_active or workflow.kill_switch:
            raise Forbidden("This workflow is inactive or killed.")
        actor_id = workflow.updated_by or workflow.created_by
        if actor_id is None:
            raise Forbidden("This workflow has no accountable publisher.")

        user = await session.get(User, actor_id)
        tenant = await session.get(Tenant, tenant_id)
        if user is None or user.status != "active" or user.deleted_at is not None:
            raise Forbidden("The workflow publisher is no longer active.")
        if tenant is None or tenant.status not in {"trial", "active"}:
            raise Forbidden("This tenant is not active.")

        role_rows = (
            await session.execute(
                select(Role.name, Role.default_scope)
                .join(UserRole, UserRole.role_id == Role.id)
                .where(UserRole.user_id == actor_id)
            )
        ).all()
        permission_rows = (
            (
                await session.execute(
                    select(RolePermission.permission_code)
                    .join(UserRole, UserRole.role_id == RolePermission.role_id)
                    .where(UserRole.user_id == actor_id)
                )
            )
            .scalars()
            .all()
        )
        team_ids = (
            (
                await session.execute(
                    select(TeamMember.team_id).where(TeamMember.user_id == actor_id)
                )
            )
            .scalars()
            .all()
        )

    scopes = [Scope(str(row.default_scope)) for row in role_rows]
    scope_order = {Scope.SELF: 0, Scope.TEAM: 1, Scope.BRANCH: 2, Scope.GLOBAL: 3}
    scope = max(scopes, key=scope_order.__getitem__) if scopes else Scope.SELF
    return AutomationPrincipal(
        user_id=user.id,
        tenant_id=tenant_id,
        tenant_slug=tenant.slug,
        email=user.email,
        name=user.full_name,
        roles=tuple(str(row.name) for row in role_rows),
        permissions=frozenset(str(value) for value in permission_rows),
        scope=scope,
        plan_code=tenant.plan_code,
        branch_ids=frozenset({str(user.branch_id)} if user.branch_id else set()),
        team_ids=frozenset(str(value) for value in team_ids),
    )


async def _execute_once(
    *,
    action: str,
    inputs: dict[str, Any],
    ctx: Any,
    principal: AutomationPrincipal,
    correlation: str,
    expected_audits: tuple[str, ...],
) -> dict[str, Any]:
    from sqlalchemy import select, text

    from infrastructure.database.models.audit import AuditLog
    from infrastructure.database.session import tenant_session
    from infrastructure.logging.context import bind_context, reset_context

    async with tenant_session(principal.tenant_id) as receipt_session:
        await receipt_session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": correlation},
        )
        receipt = (
            await receipt_session.execute(
                select(AuditLog)
                .where(
                    AuditLog.correlation_id == correlation,
                    AuditLog.action.in_(expected_audits),
                    AuditLog.outcome == "success",
                )
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if receipt is not None:
            return {
                "action": action,
                "applied": True,
                "duplicate": True,
                "resource_id": str(receipt.resource_id) if receipt.resource_id else None,
            }

        tokens = bind_context(
            correlation_id=correlation,
            tenant_id=str(principal.tenant_id),
            user_id=str(principal.user_id),
            actor_type="workflow",
        )
        try:
            result = await _apply_action(action, inputs, ctx, principal, correlation)
        finally:
            reset_context(tokens)

        receipt = (
            await receipt_session.execute(
                select(AuditLog)
                .where(
                    AuditLog.correlation_id == correlation,
                    AuditLog.action.in_(expected_audits),
                    AuditLog.outcome == "success",
                )
                .order_by(AuditLog.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if receipt is None:
            raise RuntimeError(f"action '{action}' committed no durable audit receipt")
        return {"action": action, "applied": True, "duplicate": False, "result": result}


async def _apply_action(
    action: str,
    inputs: dict[str, Any],
    ctx: Any,
    principal: AutomationPrincipal,
    correlation: str,
) -> dict[str, Any]:
    payload = dict(inputs.get("payload") or inputs)
    entity = dict(getattr(ctx, "entity", {}) or {})

    if action.startswith("lead."):
        from application.leads.service import LeadService

        service = LeadService.for_principal(principal)
        if action == "lead.create":
            return _result(await service.capture(payload))
        lead_id = _target_id(payload, entity, "lead_id")
        changes = _changes(payload, "lead_id")
        if action == "lead.assign":
            changes = {"assignee_id": _required_uuid(payload, "assignee_id")}
        return _result(
            await service.update(lead_id, changes, expected_version=payload.get("expected_version"))
        )

    if action.startswith("contact."):
        from application.crm.service import ContactService

        service = ContactService.for_principal(principal)
        if action == "contact.create":
            return _result(await service.create(payload))
        contact_id = _target_id(payload, entity, "contact_id")
        return _result(
            await service.update(
                contact_id,
                _changes(payload, "contact_id"),
                expected_version=payload.get("expected_version"),
            )
        )

    if action.startswith("deal."):
        from application.crm.deals import DealService

        service = DealService.for_principal(principal)
        if action == "deal.create":
            return _result(await service.create(payload))
        deal_id = _target_id(payload, entity, "deal_id")
        if action == "deal.move_stage":
            return _result(
                await service.move_stage(
                    deal_id,
                    _required_uuid(payload, "target_stage_id"),
                    loss_reason=payload.get("loss_reason"),
                    expected_version=payload.get("expected_version"),
                )
            )
        return _result(
            await service.update(
                deal_id,
                _changes(payload, "deal_id"),
                expected_version=payload.get("expected_version"),
            )
        )

    if action == "task.create":
        from application.crm.tasks import TaskService

        return _result(await TaskService.for_principal(principal).create(payload))

    if action in {"tag.add", "tag.remove"}:
        from application.crm.service import ContactService

        service = ContactService.for_principal(principal)
        contact_id = _target_id(payload, entity, "contact_id")
        contact = await service.get(contact_id)
        tags = {str(tag) for tag in contact.get("tags", [])}
        tag = str(payload.get("tag") or "").strip()
        if not tag:
            from shared.exceptions import ValidationError

            raise ValidationError("A tag is required.")
        tags.add(tag) if action == "tag.add" else tags.discard(tag)
        return _result(await service.update(contact_id, {"tags": sorted(tags)}))

    if action in {"note.create", "activity.create"}:
        from application.crm.timeline import TimelineService

        service = TimelineService.for_principal(principal)
        entity_type = str(payload.get("entity_type") or entity.get("type") or "contact")
        entity_id = _target_id(payload, entity, "entity_id")
        if action == "note.create":
            return _result(await service.add_note(entity_type, entity_id, payload))
        return _result(await service.log_activity(entity_type, entity_id, payload))

    if action.startswith("message.send_"):
        from application.crm.inbox import InboxService

        channel = action.removeprefix("message.send_")
        conversation_id = _target_id(payload, entity, "conversation_id")
        return _result(
            await InboxService.for_principal(principal).send(
                conversation_id, {**payload, "channel": channel}
            )
        )

    if action == "appointment.create":
        from application.crm.appointments import AppointmentService

        return _result(await AppointmentService.for_principal(principal).book(payload))

    if action == "appointment.cancel":
        from application.crm.appointments import AppointmentService

        appointment_id = _target_id(payload, entity, "appointment_id")
        return _result(
            await AppointmentService.for_principal(principal).cancel(
                appointment_id,
                payload.get("reason"),
                expected_version=payload.get("expected_version"),
            )
        )

    if action == "document.generate":
        from application.crm.documents import DocumentService

        return _result(await DocumentService.for_principal(principal).create_document(payload))

    if action == "notification.in_app":
        return await _create_notification(payload, principal, correlation)
    if action == "webhook.call":
        return await _queue_webhook(payload, ctx, principal, correlation)
    if action == "ai.task":
        return await _run_ai(payload, ctx, principal)
    if action == "analytics.emit":
        return await _emit_analytics(payload, ctx, principal, correlation)

    from application.workflows.executor import TerminalActionError

    raise TerminalActionError(f"action '{action}' is not safely available")


async def _create_notification(
    payload: dict[str, Any], principal: AutomationPrincipal, correlation: str
) -> dict[str, Any]:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.operational import Notification
    from infrastructure.database.models.users import User
    from infrastructure.database.session import tenant_session
    from shared.exceptions import ValidationError
    from shared.utils.ids import uuid7

    title = str(payload.get("title") or "").strip()
    if not title:
        raise ValidationError("A notification title is required.")
    user_id = payload.get("user_id") or principal.user_id
    notification_id = uuid7()
    async with tenant_session(principal.tenant_id) as session:
        recipient = (
            await session.execute(
                select(User.id).where(
                    User.id == user_id,
                    User.status == "active",
                    User.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if recipient is None:
            raise ValidationError("Notification recipient not found.")
        result = await session.execute(
            pg_insert(Notification)
            .values(
                id=notification_id,
                tenant_id=principal.tenant_id,
                user_id=user_id,
                notification_type=str(payload.get("notification_type") or "workflow"),
                title=title[:250],
                body=str(payload.get("body") or "")[:1000],
                entity_type=payload.get("entity_type"),
                entity_id=payload.get("entity_id"),
                is_read=False,
                is_actionable=bool(payload.get("action_url")),
                action_url=payload.get("action_url"),
                severity=str(payload.get("severity") or "info"),
                is_security=False,
                underlying_event_key=correlation,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "underlying_event_key"])
            .returning(Notification.id)
        )
        created_id = result.scalar_one_or_none()
        if created_id is not None:
            AuditRecorder(session).record(
                action="notification.create",
                resource_type="notification",
                resource_id=created_id,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                actor_type="workflow",
                new_values={"user_id": str(user_id), "severity": payload.get("severity", "info")},
            )
    return {"id": str(created_id or notification_id), "status": "created"}


async def _queue_webhook(
    payload: dict[str, Any], ctx: Any, principal: AutomationPrincipal, correlation: str
) -> dict[str, Any]:
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.workflows import (
        OutboundWebhookConfig,
        OutboundWebhookDelivery,
    )
    from infrastructure.database.session import tenant_session
    from shared.exceptions import NotFound
    from shared.utils.ids import uuid7
    from shared.utils.timeutil import utcnow

    config_id = _required_uuid(payload, "config_id")
    delivery_id = uuid7()
    async with tenant_session(principal.tenant_id) as session:
        config = (
            await session.execute(
                select(OutboundWebhookConfig).where(
                    OutboundWebhookConfig.id == config_id,
                    OutboundWebhookConfig.is_active.is_(True),
                    OutboundWebhookConfig.disabled_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if config is None:
            raise NotFound("Outbound webhook configuration not found.")
        event_id = uuid7()
        result = await session.execute(
            pg_insert(OutboundWebhookDelivery)
            .values(
                id=delivery_id,
                tenant_id=principal.tenant_id,
                config_id=config.id,
                event_id=event_id,
                event_type="workflow.action",
                idempotency_key=correlation,
                payload={
                    "event_id": str(event_id),
                    "event_type": "workflow.action",
                    "tenant_id": str(principal.tenant_id),
                    "data": dict(payload.get("body") or {}),
                    "workflow": {
                        "id": str(ctx.workflow_id),
                        "execution_id": str(ctx.execution_id),
                    },
                },
                status="pending",
                attempts=0,
                next_attempt_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["config_id", "idempotency_key"])
            .returning(OutboundWebhookDelivery.id)
        )
        created_id = result.scalar_one_or_none()
        if created_id is not None:
            AuditRecorder(session).record(
                action="webhook.call",
                resource_type="outbound_webhook_delivery",
                resource_id=created_id,
                tenant_id=principal.tenant_id,
                actor_id=principal.user_id,
                actor_type="workflow",
                new_values={"config_id": str(config.id), "status": "pending"},
            )
    return {"id": str(created_id or delivery_id), "status": "pending", "delivered": False}


async def _run_ai(
    payload: dict[str, Any], ctx: Any, principal: AutomationPrincipal
) -> dict[str, Any]:
    from application.ai.service import AiService
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.session import tenant_session

    result = await AiService.for_principal(principal).run_task(
        str(payload.get("task") or "generate"),
        str(payload.get("text") or ""),
        options=dict(payload.get("options") or {}),
    )
    async with tenant_session(principal.tenant_id) as session:
        AuditRecorder(session).record(
            action="ai.task",
            resource_type="workflow_execution",
            resource_id=ctx.execution_id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type="workflow",
            outcome="success",
            new_values={"task": payload.get("task", "generate"), "degraded": result["degraded"]},
        )
    return result


async def _emit_analytics(
    payload: dict[str, Any],
    ctx: Any,
    principal: AutomationPrincipal,
    correlation: str,
) -> dict[str, Any]:
    from application.audit.recorder import AuditRecorder
    from domain.base import DomainEvent
    from domain.events.catalog import ANALYTICS_EVENT_EMITTED
    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.session import tenant_session

    event = DomainEvent(
        event_type=ANALYTICS_EVENT_EMITTED,
        tenant_id=principal.tenant_id,
        resource_type=str(payload.get("entity_type") or "workflow_execution"),
        resource_id=payload.get("entity_id") or ctx.execution_id,
        actor_id=principal.user_id,
        actor_type="workflow",
        correlation_id=correlation,
        payload={
            "name": str(payload.get("name") or "workflow.event"),
            "properties": payload.get("properties", {}),
        },
    )
    async with tenant_session(principal.tenant_id) as session:
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
        AuditRecorder(session).record(
            action="analytics.emit",
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type="workflow",
            new_values={
                "event_id": str(event.event_id),
                "name": payload.get("name", "workflow.event"),
            },
        )
    return {"event_id": str(event.event_id), "accepted": True}


def _result(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError("workflow action services must return an object")
    return value


def _coerce_inputs(value: dict[str, Any]) -> dict[str, Any]:
    uuid_keys = {
        "account_id",
        "appointment_id",
        "assignee_id",
        "config_id",
        "contact_id",
        "conversation_id",
        "deal_id",
        "entity_id",
        "file_id",
        "lead_id",
        "organizer_id",
        "payment_id",
        "target_stage_id",
        "task_id",
        "user_id",
    }
    datetime_keys = {"due_at", "end_at", "start_at"}

    def convert(node: Any, key: str | None = None) -> Any:
        if isinstance(node, dict):
            return {k: convert(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [convert(item) for item in node]
        if key in uuid_keys and node is not None and not isinstance(node, UUID):
            return UUID(str(node))
        if key in datetime_keys and isinstance(node, str):
            parsed = datetime.fromisoformat(node.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                from shared.exceptions import ValidationError

                raise ValidationError(f"{key} must include a timezone.")
            return parsed
        return node

    converted = convert(value)
    return dict(converted)


def _target_id(payload: dict[str, Any], entity: dict[str, Any], key: str) -> UUID:
    value = payload.get(key) or payload.get("entity_id") or entity.get("id")
    if value is None:
        from shared.exceptions import ValidationError

        raise ValidationError(f"{key} is required.")
    return value if isinstance(value, UUID) else UUID(str(value))


def _required_uuid(payload: dict[str, Any], key: str) -> UUID:
    value = payload.get(key)
    if value is None:
        from shared.exceptions import ValidationError

        raise ValidationError(f"{key} is required.")
    return value if isinstance(value, UUID) else UUID(str(value))


def _changes(payload: dict[str, Any], identity_key: str) -> dict[str, Any]:
    if isinstance(payload.get("changes"), dict):
        return dict(payload["changes"])
    ignored = {
        identity_key,
        "entity_id",
        "expected_version",
        "payload",
    }
    return {key: value for key, value in payload.items() if key not in ignored}
