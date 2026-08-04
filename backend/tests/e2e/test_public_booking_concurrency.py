"""Public slot claims remain atomic under real PostgreSQL concurrency."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from shared.exceptions import Conflict
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

pytestmark = pytest.mark.postgres


async def test_concurrent_public_claims_commit_one_booking_lock_and_audit(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.appointments.booking import claim_public_slot

    tenant_id, other_tenant = seeded_tenants
    resource_id = uuid7()
    start_at = utcnow() + timedelta(days=30)
    end_at = start_at + timedelta(minutes=45)
    contenders = 8
    body = {
        "tenant_id": str(tenant_id),
        "resource_id": str(resource_id),
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "title": "Private customer name",
        "intake": {"email": "private@example.com", "phone": "+91 99999 99999"},
    }

    results = await asyncio.gather(
        *(claim_public_slot(body) for _ in range(contenders)),
        return_exceptions=True,
    )
    successes = [result for result in results if isinstance(result, dict)]
    conflicts = [result for result in results if isinstance(result, Conflict)]

    assert len(successes) == 1
    assert len(conflicts) == contenders - 1
    assert len(successes) + len(conflicts) == contenders
    appointment_id = UUID(successes[0]["appointment_id"])

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        appointments = (
            await session.execute(
                text(
                    "SELECT count(*) FROM app.appointments "
                    "WHERE resource_id = :resource_id AND start_at = :start_at"
                ),
                {"resource_id": resource_id, "start_at": start_at},
            )
        ).scalar_one()
        locks = (
            await session.execute(
                text(
                    "SELECT count(*) FROM app.slot_locks "
                    "WHERE resource_id = :resource_id AND start_at = :start_at"
                ),
                {"resource_id": resource_id, "start_at": start_at},
            )
        ).scalar_one()
        audit = (
            await session.execute(
                text(
                    "SELECT actor_id, actor_type, actor_label, new_values, metadata_json "
                    "FROM audit.audit_logs WHERE resource_id = :resource_id "
                    "AND action = 'appointment.create'"
                ),
                {"resource_id": appointment_id},
            )
        ).one()

    assert appointments == 1
    assert locks == 1
    assert audit.actor_id is None
    assert (audit.actor_type, audit.actor_label) == ("anonymous", "public_booking")
    assert audit.new_values["status"] == "scheduled"
    serialized_audit = json.dumps({"new_values": audit.new_values, "metadata": audit.metadata_json})
    assert "Private customer name" not in serialized_audit
    assert "private@example.com" not in serialized_audit
    assert "+91 99999 99999" not in serialized_audit

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(other_tenant)},
        )
        hidden = (
            await session.execute(
                text("SELECT count(*) FROM audit.audit_logs WHERE resource_id = :resource_id"),
                {"resource_id": appointment_id},
            )
        ).scalar_one()

    assert hidden == 0
