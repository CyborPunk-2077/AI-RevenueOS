from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from application.workflows.actions import action_correlation
from application.workflows.executor import TerminalActionError
from domain.workflows.dsl import compile_workflow
from infrastructure.celery.context import TaskContext
from infrastructure.celery.tasks.workflow import (
    _execute_workflow_once,
    _resume_execution_once,
    _run_action,
)
from infrastructure.database.models.audit import AuditLog, EventOutbox
from infrastructure.database.models.crm import Task
from infrastructure.database.models.leads import Lead
from infrastructure.database.models.users import (
    Role,
    RolePermission,
    User,
    UserRole,
)
from infrastructure.database.models.workflows import (
    WorkflowDefinition,
    WorkflowExecution,
    WorkflowNodeExecution,
    WorkflowVersion,
)
from infrastructure.database.session import tenant_session
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow


async def _authority(tenant_id: Any, *permissions: str) -> tuple[Any, Any]:
    user_id, role_id, workflow_id = uuid7(), uuid7(), uuid7()
    suffix = uuid4().hex
    async with tenant_session(tenant_id) as session:
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=f"workflow-{suffix}@example.test",
                full_name="Workflow Publisher",
                status="active",
                email_verified_at=utcnow(),
                is_owner=False,
                version=1,
            )
        )
        session.add(
            Role(
                id=role_id,
                tenant_id=tenant_id,
                name=f"workflow-{suffix}",
                description="workflow action test role",
                is_system=False,
                default_scope="global",
                version=1,
            )
        )
        session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role_id))
        for permission in permissions:
            session.add(
                RolePermission(
                    tenant_id=tenant_id,
                    role_id=role_id,
                    permission_code=permission,
                )
            )
        session.add(
            WorkflowDefinition(
                id=workflow_id,
                tenant_id=tenant_id,
                name=f"Workflow {suffix}",
                category="custom",
                is_active=True,
                kill_switch=False,
                created_by=user_id,
                updated_by=user_id,
                version=1,
            )
        )
    return workflow_id, user_id


def _context(tenant_id: Any, workflow_id: Any) -> Any:
    return SimpleNamespace(
        tenant_id=tenant_id,
        workflow_id=workflow_id,
        execution_id=uuid7(),
        entity={},
    )


@pytest.mark.postgres
async def test_lead_action_is_tenant_authorized_audited_and_durable_duplicate(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    workflow_id, _ = await _authority(tenant_a, "lead:create")
    ctx = _context(tenant_a, workflow_id)
    email = f"workflow-lead-{uuid4().hex}@example.test"
    first_key = f"{ctx.execution_id}:create-lead:1"

    first = await _run_action(
        "lead.create",
        {"first_name": "Workflow", "email": email, "source": "workflow"},
        ctx,
        first_key,
    )
    second = await _run_action(
        "lead.create",
        {"first_name": "Workflow", "email": email, "source": "workflow"},
        ctx,
        f"{ctx.execution_id}:create-lead:2",
    )

    assert first["applied"] is True and first["duplicate"] is False
    assert second["applied"] is True and second["duplicate"] is True
    assert second["resource_id"] == first["result"]["id"]
    correlation = action_correlation(first_key)
    async with tenant_session(tenant_a) as session:
        lead_count = await session.scalar(
            select(func.count()).select_from(Lead).where(Lead.email == email)
        )
        audit_count = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.correlation_id == correlation)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(EventOutbox)
            .where(EventOutbox.resource_id == first["result"]["id"])
        )
        assert lead_count == audit_count == outbox_count == 1
    async with tenant_session(tenant_b) as session:
        assert (
            await session.scalar(select(func.count()).select_from(Lead).where(Lead.email == email))
            == 0
        )


@pytest.mark.postgres
async def test_current_permission_and_provider_feature_gates_fail_closed(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    workflow_id, _ = await _authority(tenant_a, "lead:read", "message:send")
    ctx = _context(tenant_a, workflow_id)

    with pytest.raises(TerminalActionError, match="no longer has permission"):
        await _run_action(
            "lead.create",
            {"first_name": "Denied", "email": f"denied-{uuid4().hex}@example.test"},
            ctx,
            f"{ctx.execution_id}:denied:1",
        )
    with pytest.raises(TerminalActionError, match="not yet activated"):
        await _run_action(
            "message.send_whatsapp",
            {"conversation_id": str(uuid4()), "content": "not sent"},
            ctx,
            f"{ctx.execution_id}:message:1",
        )


@pytest.mark.postgres
async def test_analytics_action_commits_audit_and_outbox_once(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    workflow_id, _ = await _authority(tenant_a, "analytics:read")
    ctx = _context(tenant_a, workflow_id)
    first_key = f"{ctx.execution_id}:metric:1"

    first = await _run_action(
        "analytics.emit",
        {"name": "qualification.completed", "properties": {"score": 92}},
        ctx,
        first_key,
    )
    duplicate = await _run_action(
        "analytics.emit",
        {"name": "qualification.completed", "properties": {"score": 92}},
        ctx,
        f"{ctx.execution_id}:metric:2",
    )

    assert first["result"]["accepted"] is True
    assert duplicate["duplicate"] is True
    correlation = action_correlation(first_key)
    async with tenant_session(tenant_a) as session:
        audit_count = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.correlation_id == correlation)
        )
        outbox_count = await session.scalar(
            select(func.count())
            .select_from(EventOutbox)
            .where(EventOutbox.event_type == "analytics.event_emitted")
            .where(EventOutbox.correlation_id == correlation)
        )
        assert audit_count == outbox_count == 1


@pytest.mark.postgres
async def test_delay_resumes_from_durable_successors_and_persists_nodes(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    workflow_id, _ = await _authority(tenant_a, "task:create")
    title = f"Resumed task {uuid4().hex}"
    document = {
        "name": f"Durable delay {uuid4().hex}",
        "category": "custom",
        "trigger": {"type": "manual"},
        "nodes": [
            {"id": "wait", "type": "delay", "delay_seconds": 1},
            {
                "id": "create-task",
                "type": "action",
                "action": "task.create",
                "inputs": {"title": title},
            },
        ],
        "edges": [{"source": "wait", "target": "create-task"}],
    }
    plan = compile_workflow(document)
    version_id, execution_id = uuid7(), uuid7()
    async with tenant_session(tenant_a) as session:
        definition = await session.get(WorkflowDefinition, workflow_id)
        assert definition is not None
        definition.active_version_id = version_id
        session.add(
            WorkflowVersion(
                id=version_id,
                tenant_id=tenant_a,
                workflow_id=workflow_id,
                version=1,
                content=document,
                content_hash=plan["content_hash"],
                status="published",
                published_at=utcnow(),
                created_by=definition.created_by,
            )
        )
        session.add(
            WorkflowExecution(
                id=execution_id,
                tenant_id=tenant_a,
                workflow_id=workflow_id,
                version_id=version_id,
                content_hash=plan["content_hash"],
                trigger_type="manual",
                trigger_payload={},
                context={},
                state="pending",
                idempotency_key=f"manual:{execution_id}",
            )
        )

    context = TaskContext(tenant_a, "delay-test", None, "scheduler")
    waiting = await _execute_workflow_once(context, str(execution_id))
    assert waiting["state"] == "waiting"
    assert waiting["resume_nodes"] == ["create-task"]
    async with tenant_session(tenant_a) as session:
        execution = await session.get(WorkflowExecution, execution_id)
        assert execution is not None
        assert execution.context["resume_nodes"] == ["create-task"]
        assert execution.resume_at is not None
        execution.resume_at = utcnow() - timedelta(seconds=1)

    completed = await _resume_execution_once(context, str(execution_id))
    duplicate = await _resume_execution_once(context, str(execution_id))
    assert completed["state"] == "completed"
    assert duplicate == {"resumed": False}
    async with tenant_session(tenant_a) as session:
        task_count = await session.scalar(
            select(func.count()).select_from(Task).where(Task.title == title)
        )
        nodes = list(
            (
                await session.execute(
                    select(WorkflowNodeExecution).where(
                        WorkflowNodeExecution.execution_id == execution_id
                    )
                )
            ).scalars()
        )
        assert task_count == 1
        assert {(node.node_id, node.state) for node in nodes} == {
            ("wait", "completed"),
            ("create-task", "completed"),
        }
