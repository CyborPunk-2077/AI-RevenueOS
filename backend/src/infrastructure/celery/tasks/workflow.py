"""Workflow execution tasks.

The engine in `application.workflows.executor` owns the semantics; these tasks are
the durable transport that gets it invoked with the right tenant bound and the kill
switch honoured before any work starts.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.base import airev_task
from infrastructure.logging.setup import get_logger

logger = get_logger("celery.workflow")


@airev_task("critical.execute_workflow", max_attempts=3)
async def execute_workflow(
    context: TaskContext,
    execution_id: str,
    *,
    resume_from: str | list[str] | None = None,
) -> dict[str, Any]:
    return await _execute_workflow_once(context, execution_id, resume_from=resume_from)


async def _execute_workflow_once(
    context: TaskContext,
    execution_id: str,
    *,
    resume_from: str | list[str] | None = None,
) -> dict[str, Any]:
    """Run a pinned workflow version for one execution."""
    tenant_id = context.require_tenant()

    from application.workflows.control import is_killed

    if await is_killed(tenant_id=tenant_id):
        logger.info("execution_skipped_kill_switch", execution_id=execution_id)
        return {"state": "cancelled", "reason": "kill switch engaged"}

    from sqlalchemy import select

    from application.workflows.executor import (
        ExecutionContext,
        ExecutionState,
        WorkflowEngine,
    )
    from infrastructure.database.models.workflows import WorkflowExecution, WorkflowVersion
    from infrastructure.database.session import tenant_session
    from shared.exceptions import NotFound
    from shared.utils.timeutil import utcnow

    async with tenant_session(tenant_id) as session:
        execution = (
            await session.execute(
                select(WorkflowExecution)
                .where(WorkflowExecution.id == UUID(execution_id))
                .with_for_update()
            )
        ).scalar_one_or_none()
        if execution is None:
            raise NotFound("Workflow execution not found.")
        if execution.state in ("completed", "failed", "cancelled"):
            return {"state": execution.state, "duplicate": True}

        version = (
            await session.execute(
                select(WorkflowVersion).where(WorkflowVersion.id == execution.version_id)
            )
        ).scalar_one_or_none()
        if version is None:
            raise NotFound("Pinned workflow version not found.")

        plan_source = dict(version.content)
        pinned_hash = execution.content_hash
        trigger_payload = dict(execution.trigger_payload or {})
        entity = dict((execution.context or {}).get("entity", {}))
        dry_run = bool(execution.is_dry_run)
        correlation = execution.correlation_id
        workflow_id = execution.workflow_id
        version_id = execution.version_id
        execution.state = "running"
        execution.started_at = execution.started_at or utcnow()
        execution.resume_at = None

    from domain.workflows.dsl import compile_workflow

    plan = compile_workflow(plan_source)

    engine = WorkflowEngine(
        action_runner=_run_action,
        kill_check=lambda ctx: is_killed(tenant_id=ctx.tenant_id, workflow_id=ctx.workflow_id),
    )
    result = await engine.execute(
        plan,
        ExecutionContext(
            execution_id=UUID(execution_id),
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            version_id=version_id,
            content_hash=pinned_hash,
            trigger_payload=trigger_payload,
            entity=entity,
            dry_run=dry_run,
            correlation_id=correlation,
        ),
        resume_from=resume_from,
    )

    async with tenant_session(tenant_id) as session:
        execution = (
            await session.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == UUID(execution_id))
            )
        ).scalar_one()
        execution.state = result.state.value
        execution.resume_at = result.resume_at
        execution.error = result.error
        execution.context = {
            **dict(execution.context or {}),
            "waiting_on": result.waiting_on,
            "resume_nodes": result.resume_nodes,
            "nodes": [
                {
                    "node_id": node.node_id,
                    "state": node.state.value,
                    "attempt": node.attempt,
                }
                for node in result.nodes
            ],
        }
        if result.state in (ExecutionState.COMPLETED, ExecutionState.FAILED):
            execution.finished_at = utcnow()
        from application.audit.recorder import AuditRecorder

        AuditRecorder(session).record(
            action="workflow.executed",
            resource_type="workflow_execution",
            resource_id=execution.id,
            tenant_id=tenant_id,
            actor_type="worker",
            outcome=result.state.value,
            new_values={
                "workflow_id": str(execution.workflow_id),
                "version_id": str(execution.version_id),
                "state": result.state.value,
                "is_dry_run": execution.is_dry_run,
            },
        )
        await _persist_nodes(session, tenant_id, UUID(execution_id), plan_source, result.nodes)
        await _persist_approval(
            session,
            tenant_id,
            UUID(execution_id),
            plan_source,
            result.waiting_on,
            correlation,
        )

    payload: dict[str, Any] = result.to_dict()
    return payload


@airev_task("scheduled.resume_execution", max_attempts=3)
async def resume_execution(context: TaskContext, execution_id: str) -> dict[str, Any]:
    return await _resume_execution_once(context, execution_id)


async def _resume_execution_once(context: TaskContext, execution_id: str) -> dict[str, Any]:
    """Wake a suspended execution once its durable delay has elapsed."""
    from sqlalchemy import select

    from infrastructure.database.models.workflows import WorkflowExecution
    from infrastructure.database.session import tenant_session

    tenant_id = context.require_tenant()
    async with tenant_session(tenant_id) as session:
        execution = (
            await session.execute(
                select(WorkflowExecution).where(WorkflowExecution.id == UUID(execution_id))
            )
        ).scalar_one_or_none()
        if execution is None or execution.state != "waiting":
            return {"resumed": False}
        waiting_on = str((execution.context or {}).get("waiting_on") or "")
        if waiting_on:
            from infrastructure.database.models.workflows import WorkflowApproval

            approval = (
                await session.execute(
                    select(WorkflowApproval).where(
                        WorkflowApproval.execution_id == execution.id,
                        WorkflowApproval.node_id == waiting_on,
                    )
                )
            ).scalar_one_or_none()
            if approval is not None and approval.state != "approved":
                return {"resumed": False, "reason": "approval is not approved"}
        resume_from = list((execution.context or {}).get("resume_nodes") or [])
        if not resume_from:
            return {"resumed": False, "reason": "no durable continuation"}

    resumed: dict[str, Any] = await _execute_workflow_once(
        context, execution_id, resume_from=resume_from
    )
    return resumed


async def _persist_nodes(
    session: Any,
    tenant_id: UUID,
    execution_id: UUID,
    plan_source: dict[str, Any],
    nodes: list[Any],
) -> None:
    """Upsert durable node evidence in the execution's state transaction."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from infrastructure.database.models.workflows import WorkflowNodeExecution
    from shared.utils.ids import uuid7
    from shared.utils.timeutil import utcnow

    node_types = {
        str(node.get("id")): str(node.get("type")) for node in plan_source.get("nodes", [])
    }
    for result in nodes:
        values = {
            "id": uuid7(),
            "tenant_id": tenant_id,
            "execution_id": execution_id,
            "node_id": result.node_id,
            "node_type": node_types.get(result.node_id, "unknown"),
            "attempt": result.attempt,
            "state": result.state.value,
            "action_idempotency_key": result.idempotency_key or None,
            "input_snapshot": {},
            "output": result.output,
            "error": result.error,
            "started_at": None,
            "finished_at": utcnow() if result.state.value not in {"pending", "running"} else None,
        }
        await session.execute(
            pg_insert(WorkflowNodeExecution)
            .values(**values)
            .on_conflict_do_update(
                constraint="exec_node_attempt",
                set_={
                    "state": values["state"],
                    "action_idempotency_key": values["action_idempotency_key"],
                    "output": values["output"],
                    "error": values["error"],
                    "finished_at": values["finished_at"],
                    "updated_at": utcnow(),
                },
            )
        )


async def _persist_approval(
    session: Any,
    tenant_id: UUID,
    execution_id: UUID,
    plan_source: dict[str, Any],
    waiting_on: str | None,
    correlation_id: str | None,
) -> None:
    if not waiting_on:
        return
    node = next(
        (item for item in plan_source.get("nodes", []) if str(item.get("id")) == waiting_on),
        None,
    )
    if not isinstance(node, dict) or node.get("type") != "approval":
        return

    from datetime import timedelta

    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from application.audit.recorder import AuditRecorder
    from domain.base import DomainEvent
    from domain.events.catalog import APPROVAL_REQUESTED
    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.models.workflows import WorkflowApproval
    from shared.utils.ids import uuid7
    from shared.utils.timeutil import utcnow

    approval_id = uuid7()
    due_seconds = int(node.get("due_seconds") or 0)
    inserted = await session.execute(
        pg_insert(WorkflowApproval)
        .values(
            id=approval_id,
            tenant_id=tenant_id,
            execution_id=execution_id,
            node_id=waiting_on,
            state="requested",
            strategy=str(node.get("strategy") or "any"),
            quorum=int(node.get("quorum") or 1),
            assignees=[str(value) for value in node.get("assignees", [])],
            decisions=[],
            summary=str(node.get("summary") or "Workflow approval required")[:1000],
            due_at=utcnow() + timedelta(seconds=due_seconds) if due_seconds > 0 else None,
            timeout_path=node.get("timeout_path"),
        )
        .on_conflict_do_nothing(index_elements=["execution_id", "node_id"])
        .returning(WorkflowApproval.id)
    )
    created_id = inserted.scalar_one_or_none()
    if created_id is None:
        return
    AuditRecorder(session).record(
        action="workflow.approval_requested",
        resource_type="workflow_approval",
        resource_id=created_id,
        tenant_id=tenant_id,
        actor_type="workflow",
        new_values={"execution_id": str(execution_id), "node_id": waiting_on},
    )
    event = DomainEvent(
        event_type=APPROVAL_REQUESTED,
        tenant_id=tenant_id,
        resource_type="workflow_approval",
        resource_id=created_id,
        actor_type="workflow",
        correlation_id=correlation_id,
        payload={"execution_id": str(execution_id), "node_id": waiting_on},
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


async def _run_action(
    action: str, inputs: dict[str, Any], ctx: Any, idempotency_key: str
) -> dict[str, Any]:
    """Execute one workflow action under its idempotency key.

    The application dispatcher enforces current publisher permissions, feature
    gates and a durable audit-backed idempotency receipt.
    """
    from domain.workflows.dsl import ACTION_CATALOG

    spec = ACTION_CATALOG.get(action)
    if spec is None:
        from application.workflows.executor import TerminalActionError

        raise TerminalActionError(f"unknown action '{action}'")

    logger.info(
        "workflow_action",
        action=action,
        external_effect=spec.external_effect,
        tenant_id=str(ctx.tenant_id),
    )
    from application.workflows.actions import dispatch_action

    return await dispatch_action(action, inputs, ctx, idempotency_key)
