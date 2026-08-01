"""Workflow execution tasks.

The engine in `application.workflows.executor` owns the semantics; these tasks are
the durable transport that gets it invoked with the right tenant bound and the kill
switch honoured before any work starts.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from infrastructure.celery.context import TaskContext
from infrastructure.celery.reliability import action_key, claim_once
from infrastructure.celery.tasks.base import airev_task
from infrastructure.logging.setup import get_logger

logger = get_logger("celery.workflow")


@airev_task("critical.execute_workflow", max_attempts=3)
async def execute_workflow(
    context: TaskContext, execution_id: str, *, resume_from: str | None = None
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
                select(WorkflowExecution).where(WorkflowExecution.id == UUID(execution_id))
            )
        ).scalar_one_or_none()
        if execution is None:
            raise NotFound("Workflow execution not found.")
        if execution.state in ("completed", "cancelled"):
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
        if result.state in (ExecutionState.COMPLETED, ExecutionState.FAILED):
            execution.finished_at = utcnow()

    payload: dict[str, Any] = result.to_dict()
    return payload


@airev_task("scheduled.resume_execution", max_attempts=3)
async def resume_execution(context: TaskContext, execution_id: str) -> dict[str, Any]:
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
        node_ids = [
            n.get("node_id")
            for n in (execution.context or {}).get("nodes", [])
            if n.get("state") == "pending"
        ]
        resume_from = node_ids[0] if node_ids else None

    resumed: dict[str, Any] = await execute_workflow(context, execution_id, resume_from=resume_from)
    return resumed


async def _run_action(
    action: str, inputs: dict[str, Any], ctx: Any, idempotency_key: str
) -> dict[str, Any]:
    """Execute one workflow action under its idempotency key.

    An external effect is claimed before it is performed, so a redelivered message
    cannot contact the same customer twice.
    """
    from domain.workflows.dsl import ACTION_CATALOG

    spec = ACTION_CATALOG.get(action)
    if spec is None:
        from application.workflows.executor import TerminalActionError

        raise TerminalActionError(f"unknown action '{action}'")

    if spec.external_effect:
        key = action_key(ctx.execution_id, idempotency_key.split(":")[1], 1)
        if not await claim_once(key):
            logger.info("action_skipped_duplicate", action=action, key=key.identity)
            return {"skipped": True, "reason": "already performed"}

    logger.info(
        "workflow_action",
        action=action,
        external_effect=spec.external_effect,
        tenant_id=str(ctx.tenant_id),
    )
    # Concrete action handlers are wired per module as those services land. The
    # dispatch table, permission, feature gate, retry class and idempotency key are
    # already declared on the action spec.
    return {"action": action, "applied": False, "pending_handler": True}
