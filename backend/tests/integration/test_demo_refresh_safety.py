"""A demo refresh must not be able to delete real data. Ever again.

These exist because it did. The founders' prospect "Claida" was created and worked
in the demo workspace, and a refresh that deleted by `tenant_id` destroyed it. The
assertions below are that incident, written down: each one fails if the refresh
regains the ability to touch a row the seed did not create.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from application.tenants.demo_data import (
    delete_recorded_rows,
    empty_manifest,
    load_manifest,
    record_manifest,
)
from infrastructure.database.session import admin_session
from shared.utils.ids import uuid7

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

# These use the configured database through `admin_session` rather than the
# ephemeral fixture, in two tenants they create and remove themselves. The
# scenario is worthless against a schema that does not match the real one: the
# whole claim is about what a delete can reach in production-shaped tables.

DEMO_TENANT = UUID("01890000-0000-7000-8000-0000000d3300")
OTHER_TENANT = UUID("01890000-0000-7000-8000-0000000d3301")


async def _tenant(session: Any, tenant_id: UUID, slug: str) -> None:
    await session.execute(
        text(
            "INSERT INTO app.tenants (id, name, slug, plan_code, status, timezone, currency,"
            " locale, settings, branding, business_hours, holidays, billing_address,"
            " onboarding_state, legal_hold, version, created_at, updated_at)"
            " VALUES (:id, :slug, :slug, 'growth', 'active', 'Asia/Kolkata', 'INR', 'en-IN',"
            " '{}', '{}', '{}', '[]', '{}', '{}', false, 1, now(), now())"
            " ON CONFLICT (id) DO NOTHING"
        ),
        {"id": tenant_id, "slug": slug},
    )


async def _lead(session: Any, tenant_id: UUID, name: str, *, demo: bool) -> UUID:
    lead_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO app.leads (id, tenant_id, first_name, source, capture, utm,"
            " reasoning, status, version, created_at, updated_at)"
            " VALUES (:id, :t, :name, 'manual', CAST(:capture AS jsonb), '{}', '{}', 'new', 1,"
            " now(), now())"
        ),
        {
            "id": lead_id,
            "t": tenant_id,
            "name": name,
            "capture": '{"demo_data": true}' if demo else "{}",
        },
    )
    return lead_id


async def _task(session: Any, tenant_id: UUID, lead_id: UUID, title: str) -> UUID:
    task_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO app.tasks (id, tenant_id, title, entity_type, entity_id, priority,"
            " status, is_next_action, source, version, created_at, updated_at)"
            " VALUES (:id, :t, :title, 'lead', :lead, 'normal', 'open', false, 'manual', 1,"
            " now(), now())"
        ),
        {"id": task_id, "t": tenant_id, "title": title, "lead": lead_id},
    )
    return task_id


async def _note(session: Any, tenant_id: UUID, lead_id: UUID, body: str) -> UUID:
    note_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO app.notes (id, tenant_id, entity_type, entity_id, body, is_pinned,"
            " version, created_at, updated_at)"
            " VALUES (:id, :t, 'lead', :lead, :body, false, 1, now(), now())"
        ),
        {"id": note_id, "t": tenant_id, "lead": lead_id, "body": body},
    )
    return note_id


async def _exists(session: Any, table: str, row_id: UUID) -> bool:
    found = await session.execute(
        text(f"SELECT 1 FROM app.{table} WHERE id = :id"),  # noqa: S608 - fixed literals
        {"id": row_id},
    )
    return found.scalar_one_or_none() is not None


@pytest.fixture
async def db() -> Any:
    """The real database, as the owner role, so both tenants are writable."""
    async with admin_session() as session:
        yield session
        # Remove only the tenants this file invented, children first.
        for table in ("tasks", "notes", "leads"):
            await session.execute(
                text(f"DELETE FROM app.{table} WHERE tenant_id = ANY(:ids)"),  # noqa: S608
                {"ids": [DEMO_TENANT, OTHER_TENANT]},
            )
        await session.execute(
            text("DELETE FROM app.tenants WHERE id = ANY(:ids)"),
            {"ids": [DEMO_TENANT, OTHER_TENANT]},
        )


@pytest.fixture
async def workspace(db: Any) -> dict[str, Any]:
    """A demo workspace holding sample rows, founder rows and an unmarked row."""
    await _tenant(db, DEMO_TENANT, "demo-safety")
    await _tenant(db, OTHER_TENANT, "other-safety")

    sample = await _lead(db, DEMO_TENANT, "Sample Prospect", demo=True)
    sample_task = await _task(db, DEMO_TENANT, sample, "sample follow-up")

    founder = await _lead(db, DEMO_TENANT, "Claida", demo=False)
    founder_task = await _task(db, DEMO_TENANT, founder, "dealing")
    founder_note = await _note(db, DEMO_TENANT, founder, "spoke to the owner")

    imported = await _lead(db, DEMO_TENANT, "Imported Business", demo=False)
    # No marker either way: the state a row is in when nobody has said anything
    # about it. It must be treated as real.
    ambiguous = await _lead(db, DEMO_TENANT, "Unmarked Business", demo=False)
    neighbour = await _lead(db, OTHER_TENANT, "Another Tenant", demo=True)

    manifest = empty_manifest()
    manifest["leads"] = [str(sample)]
    manifest["tasks"] = [str(sample_task)]
    await record_manifest(db, DEMO_TENANT, manifest)

    return {
        "sample": sample,
        "sample_task": sample_task,
        "founder": founder,
        "founder_task": founder_task,
        "founder_note": founder_note,
        "imported": imported,
        "ambiguous": ambiguous,
        "neighbour": neighbour,
    }


async def test_sample_records_are_refreshed(db: Any, workspace: dict[str, Any]) -> None:
    removed = await delete_recorded_rows(db, DEMO_TENANT)

    assert removed["leads"] == 1
    assert not await _exists(db, "leads", workspace["sample"])
    assert not await _exists(db, "tasks", workspace["sample_task"])


async def test_the_founder_created_prospect_survives(db: Any, workspace: dict[str, Any]) -> None:
    """The exact record the old refresh destroyed."""
    await delete_recorded_rows(db, DEMO_TENANT)

    assert await _exists(db, "leads", workspace["founder"])


async def test_founder_notes_and_tasks_survive(db: Any, workspace: dict[str, Any]) -> None:
    await delete_recorded_rows(db, DEMO_TENANT)

    assert await _exists(db, "tasks", workspace["founder_task"])
    assert await _exists(db, "notes", workspace["founder_note"])


async def test_an_imported_business_survives(db: Any, workspace: dict[str, Any]) -> None:
    await delete_recorded_rows(db, DEMO_TENANT)

    assert await _exists(db, "leads", workspace["imported"])


async def test_an_unmarked_record_is_preserved_not_deleted(
    db: Any, workspace: dict[str, Any]
) -> None:
    """Absence of a marker means "unknown", and unknown must never mean "delete"."""
    await delete_recorded_rows(db, DEMO_TENANT)

    assert await _exists(db, "leads", workspace["ambiguous"])


async def test_another_tenants_rows_are_untouched(db: Any, workspace: dict[str, Any]) -> None:
    await delete_recorded_rows(db, DEMO_TENANT)

    assert await _exists(db, "leads", workspace["neighbour"])


async def test_a_manifest_naming_a_foreign_row_cannot_reach_it(
    db: Any, workspace: dict[str, Any]
) -> None:
    """Belt and braces: the tenant predicate holds even if the manifest is wrong."""
    manifest = await load_manifest(db, DEMO_TENANT)
    manifest["leads"] = [str(workspace["neighbour"])]
    await record_manifest(db, DEMO_TENANT, manifest)

    await delete_recorded_rows(db, DEMO_TENANT)

    assert await _exists(db, "leads", workspace["neighbour"])


async def test_an_empty_manifest_deletes_nothing(db: Any, workspace: dict[str, Any]) -> None:
    """A workspace the seed never touched must survive a refresh completely."""
    await record_manifest(db, DEMO_TENANT, empty_manifest())

    removed = await delete_recorded_rows(db, DEMO_TENANT)

    assert removed == {}
    assert await _exists(db, "leads", workspace["sample"])
    assert await _exists(db, "leads", workspace["founder"])
