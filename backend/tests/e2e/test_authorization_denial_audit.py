"""Authenticated authorization denials become tenant-scoped audit evidence."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from shared.exceptions import Forbidden
from shared.utils.ids import uuid7

pytestmark = pytest.mark.postgres


async def test_denial_audit_is_compact_and_tenant_isolated(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.audit.denials import audit_authorization_denial

    tenant_id, other_tenant = seeded_tenants
    user_id = uuid7()
    principal = SimpleNamespace(
        tenant_id=tenant_id,
        user_id=user_id,
        actor_type="user",
    )
    request = SimpleNamespace(
        state=SimpleNamespace(principal=principal),
        method="POST",
        url=SimpleNamespace(path="/v1/leads"),
    )
    await audit_authorization_denial(
        request,
        Forbidden(details={"required_permission": "lead:create"}),
    )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        row = (
            await session.execute(
                text(
                    "SELECT actor_id, outcome, metadata_json FROM audit.audit_logs "
                    "WHERE actor_id = :user_id AND action = 'authz.denied' "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"user_id": user_id},
            )
        ).one()

    assert row.actor_id == user_id
    assert row.outcome == "denied"
    assert row.metadata_json == {
        "method": "POST",
        "path": "/v1/leads",
        "required_permission": "lead:create",
    }

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(other_tenant)},
        )
        hidden = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.audit_logs "
                    "WHERE actor_id = :user_id AND action = 'authz.denied'"
                ),
                {"user_id": user_id},
            )
        ).scalar_one()

    assert hidden == 0
