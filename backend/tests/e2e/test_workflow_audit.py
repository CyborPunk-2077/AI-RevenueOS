"""Workflow publication and kill controls survive cache loss and remain auditable."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from shared.utils.ids import uuid7

pytestmark = pytest.mark.postgres

WORKFLOW = {
    "name": "Audited welcome flow",
    "category": "lead_nurture",
    "trigger": {"type": "entity.created", "entity": "lead"},
    "nodes": [{"id": "n1", "type": "action", "action": "tag.add", "inputs": {"tag": "new"}}],
    "edges": [],
}


async def test_publication_is_idempotent_and_kill_switch_survives_redis_flush(
    wired_engine, seeded_tenants, session_factory
) -> None:
    from application.workflows.control import engage_kill_switch, is_killed, release_kill_switch
    from application.workflows.service import publish_workflow
    from infrastructure.caching.redis import get_redis

    tenant_id, other_tenant = seeded_tenants
    actor_id = uuid7()
    document = {**WORKFLOW, "name": f"{WORKFLOW['name']} {uuid7()}"}
    first = await publish_workflow(
        document=document, changelog="initial", tenant_id=tenant_id, actor_id=actor_id
    )
    duplicate = await publish_workflow(
        document=document, changelog="retry", tenant_id=tenant_id, actor_id=actor_id
    )
    workflow_id = UUID(first["workflow_id"])

    assert duplicate["workflow_id"] == first["workflow_id"]
    assert duplicate["version_id"] == first["version_id"]
    assert duplicate["duplicate"] is True

    killed = await engage_kill_switch(
        tenant_id=tenant_id, workflow_id=workflow_id, actor_id=actor_id
    )
    assert killed["engaged"] is True
    await get_redis().flushall()
    assert await is_killed(tenant_id=tenant_id, workflow_id=workflow_id) is True

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        counts = (
            await session.execute(
                text(
                    "SELECT "
                    "(SELECT count(*) FROM app.workflow_definitions WHERE id = :workflow_id), "
                    "(SELECT count(*) FROM app.workflow_versions "
                    " WHERE workflow_id = :workflow_id), "
                    "(SELECT count(*) FROM audit.audit_logs WHERE resource_id = :workflow_id "
                    " AND action = 'workflow.published'), "
                    "(SELECT count(*) FROM audit.event_outbox WHERE resource_id = :workflow_id "
                    " AND event_type = 'workflow.published')"
                ),
                {"workflow_id": workflow_id},
            )
        ).one()
        kill_switch = (
            await session.execute(
                text("SELECT kill_switch FROM app.workflow_definitions WHERE id = :workflow_id"),
                {"workflow_id": workflow_id},
            )
        ).scalar_one()
        kill_audit = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.audit_logs WHERE resource_id = :workflow_id "
                    "AND action = 'workflow.killed'"
                ),
                {"workflow_id": workflow_id},
            )
        ).scalar_one()

    assert tuple(counts) == (1, 1, 1, 1)
    assert kill_switch is True
    assert kill_audit == 1

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(other_tenant)},
        )
        hidden = (
            await session.execute(
                text("SELECT count(*) FROM app.workflow_definitions WHERE id = :workflow_id"),
                {"workflow_id": workflow_id},
            )
        ).scalar_one()
    assert hidden == 0

    await release_kill_switch(tenant_id=tenant_id, workflow_id=workflow_id)
    assert await is_killed(tenant_id=tenant_id, workflow_id=workflow_id) is False
