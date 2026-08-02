"""Durable workflow publication with immutable versions and audit evidence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from domain.base import DomainEvent
from domain.workflows.dsl import DslValidationError, compile_workflow
from shared.exceptions import ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow


async def publish_workflow(
    *, document: dict[str, Any], changelog: str, tenant_id: UUID, actor_id: UUID
) -> dict[str, Any]:
    try:
        plan = compile_workflow(document)
    except DslValidationError as exc:
        raise ValidationError(
            "The workflow document failed validation.",
            details={"problems": exc.problems},
        ) from exc

    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.workflows import WorkflowDefinition, WorkflowVersion
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    name = str(document["name"]).strip()[:200]
    category = str(document.get("category", "custom"))
    async with SqlAlchemyUnitOfWork(tenant_id) as uow:
        definition = (
            await uow.session.execute(
                select(WorkflowDefinition)
                .where(
                    WorkflowDefinition.tenant_id == tenant_id,
                    WorkflowDefinition.name == name,
                    WorkflowDefinition.deleted_at.is_(None),
                )
                .with_for_update()
            )
        ).scalar_one_or_none()

        if definition is not None and definition.active_version_id is not None:
            active = (
                await uow.session.execute(
                    select(WorkflowVersion).where(
                        WorkflowVersion.id == definition.active_version_id
                    )
                )
            ).scalar_one_or_none()
            if active is not None and active.content_hash == plan["content_hash"]:
                return _published_response(definition, active, plan, changelog, duplicate=True)

        if definition is None:
            workflow_id = uuid7()
            definition = WorkflowDefinition(
                id=workflow_id,
                tenant_id=tenant_id,
                name=name,
                description=str(document.get("description", ""))[:2000],
                category=category,
                is_active=True,
                global_policy=plan["global_policy"],
                source="builder",
                created_by=actor_id,
                updated_by=actor_id,
                version=1,
            )
            uow.session.add(definition)
            version_number = 1
        else:
            workflow_id = definition.id
            version_number = (
                int(
                    (
                        await uow.session.execute(
                            select(func.coalesce(func.max(WorkflowVersion.version), 0)).where(
                                WorkflowVersion.workflow_id == workflow_id
                            )
                        )
                    ).scalar_one()
                )
                + 1
            )
            definition.description = str(document.get("description", definition.description))[:2000]
            definition.category = category
            definition.global_policy = plan["global_policy"]
            definition.is_active = True
            definition.updated_by = actor_id
            definition.version += 1

        version = WorkflowVersion(
            id=uuid7(),
            tenant_id=tenant_id,
            workflow_id=workflow_id,
            version=version_number,
            content=document,
            content_hash=plan["content_hash"],
            parent_version_id=definition.active_version_id,
            status="published",
            published_at=utcnow(),
            validation_report={"valid": True, "problems": [], "changelog": changelog[:1000]},
            created_by=actor_id,
        )
        uow.session.add(version)
        definition.active_version_id = version.id

        AuditRecorder(uow.session).record(
            action="workflow.published",
            resource_type="workflow",
            resource_id=workflow_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={
                "version": version_number,
                "content_hash": plan["content_hash"],
                "status": "published",
            },
        )
        uow.collect(
            DomainEvent(
                event_type="workflow.published",
                tenant_id=tenant_id,
                resource_type="workflow",
                resource_id=workflow_id,
                actor_id=actor_id,
                payload={"version_id": str(version.id), "version": version_number},
            )
        )

    return _published_response(definition, version, plan, changelog, duplicate=False)


def _published_response(
    definition: Any,
    version: Any,
    plan: dict[str, Any],
    changelog: str,
    *,
    duplicate: bool,
) -> dict[str, Any]:
    return {
        "workflow_id": str(definition.id),
        "version_id": str(version.id),
        "version": int(version.version),
        "content_hash": plan["content_hash"],
        "entry_nodes": plan["entry_nodes"],
        "external_effect_nodes": plan["external_effect_nodes"],
        "global_policy": plan["global_policy"],
        "status": "published",
        "changelog": changelog,
        "duplicate": duplicate,
    }
