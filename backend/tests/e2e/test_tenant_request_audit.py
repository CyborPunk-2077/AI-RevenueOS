"""Tenant governance requests commit state, audit and outbox in one transaction."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text

from shared.utils.ids import uuid7

pytestmark = pytest.mark.postgres


async def test_export_and_deletion_requests_are_durable_audited_and_isolated(
    wired_engine, seeded_tenants, session_factory
) -> None:
    from application.tenants.requests import request_tenant_deletion, request_tenant_export

    tenant_id, other_tenant = seeded_tenants
    actor_id = uuid7()
    exported = await request_tenant_export(tenant_id=tenant_id, actor_id=actor_id)
    deleted = await request_tenant_deletion(tenant_id=tenant_id, actor_id=actor_id)
    export_id = UUID(exported["request_id"])
    delete_id = UUID(deleted["request_id"])

    assert exported["status"] == "received"
    assert exported["download_available"] is False
    assert deleted["status"] == "received"

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        requests = (
            await session.execute(
                text(
                    "SELECT id, request_type, status FROM audit.privacy_requests "
                    "WHERE id IN (:export_id, :delete_id) ORDER BY request_type"
                ),
                {"export_id": export_id, "delete_id": delete_id},
            )
        ).all()
        audit_actions = set(
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit.audit_logs "
                        "WHERE resource_id IN (:export_id, :delete_id, :tenant_id) "
                        "AND action IN ('privacy.request', 'tenant.delete_requested')"
                    ),
                    {
                        "export_id": export_id,
                        "delete_id": delete_id,
                        "tenant_id": tenant_id,
                    },
                )
            ).scalars()
        )
        events = set(
            (
                await session.execute(
                    text(
                        "SELECT event_type FROM audit.event_outbox "
                        "WHERE resource_id IN (:export_id, :tenant_id) "
                        "AND event_type IN ('privacy.requested', 'tenant.delete_requested')"
                    ),
                    {"export_id": export_id, "tenant_id": tenant_id},
                )
            ).scalars()
        )

    assert {(row.request_type, row.status) for row in requests} == {
        ("delete", "received"),
        ("export", "received"),
    }
    assert audit_actions == {"privacy.request", "tenant.delete_requested"}
    assert events == {"privacy.requested", "tenant.delete_requested"}

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(other_tenant)},
        )
        hidden = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.privacy_requests "
                    "WHERE id IN (:export_id, :delete_id)"
                ),
                {"export_id": export_id, "delete_id": delete_id},
            )
        ).scalar_one()

    assert hidden == 0
