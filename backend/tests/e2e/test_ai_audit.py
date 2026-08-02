"""AI usage and its mandatory audit row commit together on real PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.postgres


async def test_ai_usage_commits_a_compact_tenant_scoped_audit_row(
    wired_engine, seeded_tenants, session_factory
) -> None:
    from application.ai.registry import _record_usage
    from shared.utils.ids import uuid7

    tenant_id, other_tenant = seeded_tenants
    user_id = uuid7()
    request_id = f"ai-audit-{uuid4()}"
    await _record_usage(
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "task": "qualify_lead",
            "provider": "openai",
            "model": "test-model",
            "input_tokens": 120,
            "output_tokens": 30,
            "cache_tokens": 0,
            "cost_micro_inr": 4500,
            "latency_ms": 125,
            "request_id": request_id,
            "outcome": "success",
            "degraded": False,
        }
    )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        usage = (
            await session.execute(
                text(
                    "SELECT id, input_tokens, output_tokens FROM app.ai_usage_records "
                    "WHERE request_id = :request_id"
                ),
                {"request_id": request_id},
            )
        ).one()
        audit = (
            await session.execute(
                text(
                    "SELECT action, resource_id, new_values FROM audit.audit_logs "
                    "WHERE resource_id = :rid"
                ),
                {"rid": usage.id},
            )
        ).one()

    assert (usage.input_tokens, usage.output_tokens) == (120, 30)
    assert audit.action == "ai.task"
    assert audit.resource_id == usage.id
    assert audit.new_values["cost_micro_inr"] == 4500

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(other_tenant)},
        )
        hidden = (
            await session.execute(
                text("SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid"),
                {"rid": usage.id},
            )
        ).scalar_one()

    assert hidden == 0
