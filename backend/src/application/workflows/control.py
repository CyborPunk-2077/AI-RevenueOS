"""Kill switches take effect in under five seconds at tenant, workflow and global scope."""

from __future__ import annotations

from typing import Any
from uuid import UUID

KILL_TTL_SECONDS = 86_400


async def engage_kill_switch(
    *, tenant_id: UUID, workflow_id: UUID | None = None, actor_id: UUID | None = None
) -> dict[str, Any]:
    from infrastructure.caching.redis import Cache, tenant_key

    scope = "workflow" if workflow_id else "tenant"
    key = tenant_key(str(tenant_id), "kill", scope, str(workflow_id or "all"))
    if workflow_id is not None:
        from sqlalchemy import select

        from application.audit.recorder import AuditRecorder
        from domain.base import DomainEvent
        from infrastructure.database.models.workflows import WorkflowDefinition
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.exceptions import NotFound
        from shared.utils.timeutil import utcnow

        async with SqlAlchemyUnitOfWork(tenant_id) as uow:
            workflow = (
                await uow.session.execute(
                    select(WorkflowDefinition)
                    .where(
                        WorkflowDefinition.id == workflow_id,
                        WorkflowDefinition.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if workflow is None:
                raise NotFound("Workflow not found.")
            workflow.kill_switch = True
            workflow.paused_at = utcnow()
            workflow.updated_by = actor_id
            workflow.version += 1
            AuditRecorder(uow.session).record(
                action="workflow.killed",
                resource_type="workflow",
                resource_id=workflow_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                new_values={"kill_switch": True, "scope": "workflow"},
            )
            uow.collect(
                DomainEvent(
                    event_type="workflow.killed",
                    tenant_id=tenant_id,
                    resource_type="workflow",
                    resource_id=workflow_id,
                    actor_id=actor_id,
                    payload={"kill_switch": True},
                )
            )
    await Cache().set_json(key, {"engaged": True, "by": str(actor_id)}, KILL_TTL_SECONDS)
    return {"scope": scope, "engaged": True, "effective_within_seconds": 5}


async def is_killed(*, tenant_id: UUID, workflow_id: UUID | None = None) -> bool:
    """Global, tenant and workflow scopes are checked cheapest-first and short-circuit."""
    from infrastructure.caching.redis import Cache, global_key, tenant_key

    cache = Cache()
    scopes = [
        global_key("kill", "all"),
        tenant_key(str(tenant_id), "kill", "tenant", "all"),
    ]
    if workflow_id:
        scopes.append(tenant_key(str(tenant_id), "kill", "workflow", str(workflow_id)))

    for scope in scopes:
        if await cache.get_json(scope) is not None:
            return True
    if workflow_id is not None:
        from sqlalchemy import select

        from infrastructure.database.models.workflows import WorkflowDefinition
        from infrastructure.database.session import tenant_session

        async with tenant_session(tenant_id) as session:
            persisted = (
                await session.execute(
                    select(WorkflowDefinition.kill_switch).where(
                        WorkflowDefinition.id == workflow_id,
                        WorkflowDefinition.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
        if persisted is True:
            key = tenant_key(str(tenant_id), "kill", "workflow", str(workflow_id))
            await cache.set_json(key, {"engaged": True, "by": "persisted"}, KILL_TTL_SECONDS)
            return True
    return False


async def release_kill_switch(*, tenant_id: UUID, workflow_id: UUID | None = None) -> None:
    from infrastructure.caching.redis import Cache, tenant_key

    scope = "workflow" if workflow_id else "tenant"
    if workflow_id is not None:
        from sqlalchemy import select

        from application.audit.recorder import AuditRecorder
        from domain.base import DomainEvent
        from infrastructure.database.models.workflows import WorkflowDefinition
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.exceptions import NotFound

        async with SqlAlchemyUnitOfWork(tenant_id) as uow:
            workflow = (
                await uow.session.execute(
                    select(WorkflowDefinition)
                    .where(
                        WorkflowDefinition.id == workflow_id,
                        WorkflowDefinition.deleted_at.is_(None),
                    )
                    .with_for_update()
                )
            ).scalar_one_or_none()
            if workflow is None:
                raise NotFound("Workflow not found.")
            workflow.kill_switch = False
            workflow.paused_at = None
            workflow.version += 1
            AuditRecorder(uow.session).record(
                action="workflow.kill_released",
                resource_type="workflow",
                resource_id=workflow_id,
                tenant_id=tenant_id,
                actor_type="system",
                new_values={"kill_switch": False, "scope": "workflow"},
            )
            uow.collect(
                DomainEvent(
                    event_type="workflow.kill_released",
                    tenant_id=tenant_id,
                    resource_type="workflow",
                    resource_id=workflow_id,
                    actor_type="system",
                    payload={"kill_switch": False},
                )
            )
    await Cache().delete(tenant_key(str(tenant_id), "kill", scope, str(workflow_id or "all")))
