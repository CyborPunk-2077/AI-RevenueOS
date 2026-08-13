"""Merge, disqualify and restore against real PostgreSQL."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from application.leads import lifecycle_ops
from infrastructure.database.models.leads import Lead, LeadSourceEvent
from infrastructure.database.session import tenant_session
from shared.exceptions import Conflict, NotFound, ValidationError
from shared.utils.ids import uuid7

pytestmark = pytest.mark.postgres


async def _lead(tenant_id: UUID, **over: Any) -> UUID:
    lead_id = uuid7()
    values: dict[str, Any] = {
        "id": lead_id,
        "tenant_id": tenant_id,
        "first_name": "Asha",
        "email": f"asha-{uuid4().hex[:8]}@example.in",
        "source": "web_form",
        "status": "new",
        "version": 1,
    }
    values.update(over)
    async with tenant_session(tenant_id) as session:
        session.add(Lead(**values))
    return lead_id


async def _get(tenant_id: UUID, lead_id: UUID) -> Lead:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one()


class TestMerge:
    async def test_the_loser_is_kept_and_points_at_the_survivor(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """A bookmarked URL for the old id must resolve, not 404."""
        tenant_a, _ = seeded_tenants
        survivor = await _lead(tenant_a)
        loser = await _lead(tenant_a)

        await lifecycle_ops.merge_leads(
            tenant_id=tenant_a, actor_id=uuid4(), survivor_id=survivor, loser_id=loser
        )

        merged = await _get(tenant_a, loser)
        assert merged.merged_into_id == survivor
        assert merged.deleted_at is not None
        assert merged.status == "archived"

    async def test_only_empty_fields_are_filled(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """Overwriting a human-corrected field with older data is unforgivable."""
        tenant_a, _ = seeded_tenants
        survivor = await _lead(tenant_a, phone=None, last_name="Menon")
        loser = await _lead(tenant_a, phone="+919812345678", last_name="Menonn")

        result = await lifecycle_ops.merge_leads(
            tenant_id=tenant_a, actor_id=uuid4(), survivor_id=survivor, loser_id=loser
        )

        kept = await _get(tenant_a, survivor)
        assert kept.phone == "+919812345678"
        assert kept.last_name == "Menon", "the survivor's own value must win"
        assert result["filled_fields"] == ["phone"]

    async def test_source_events_stay_where_they_were_written(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """A merge must not rewrite the evidence of how a lead arrived.

        This used to assert the opposite - that the events were re-pointed at the
        survivor. `app.lead_source_events` is append-only at the database level, so
        that UPDATE could never commit and it took the entire merge down with it.
        Nothing is lost by leaving them alone: the loser is kept and stamped with
        `merged_into_id`, so the attribution is still reachable from the survivor.
        """
        tenant_a, _ = seeded_tenants
        survivor = await _lead(tenant_a)
        loser = await _lead(tenant_a)
        async with tenant_session(tenant_a) as session:
            session.add(
                LeadSourceEvent(
                    id=uuid7(),
                    tenant_id=tenant_a,
                    lead_id=loser,
                    source="web_form",
                    source_channel="web_form",
                    source_idempotency_key=str(uuid7()),
                    raw_payload={},
                    outcome="received",
                )
            )

        await lifecycle_ops.merge_leads(
            tenant_id=tenant_a, actor_id=uuid4(), survivor_id=survivor, loser_id=loser
        )

        async with tenant_session(tenant_a) as session:
            on_survivor = (
                await session.execute(
                    select(func.count())
                    .select_from(LeadSourceEvent)
                    .where(LeadSourceEvent.lead_id == survivor)
                )
            ).scalar_one()
            on_loser = (
                await session.execute(
                    select(func.count())
                    .select_from(LeadSourceEvent)
                    .where(LeadSourceEvent.lead_id == loser)
                )
            ).scalar_one()

        assert on_survivor == 0, "the survivor gains no history it did not have"
        assert on_loser == 1, "and the loser's own history is intact"
        # The route from the survivor back to it: the loser is kept, not deleted.
        assert (await _get(tenant_a, loser)).merged_into_id == survivor

    async def test_a_converted_lead_cannot_be_merged_away(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        survivor = await _lead(tenant_a)
        converted = await _lead(tenant_a, status="converted")

        with pytest.raises(Conflict):
            await lifecycle_ops.merge_leads(
                tenant_id=tenant_a, actor_id=uuid4(), survivor_id=survivor, loser_id=converted
            )

    async def test_a_lead_cannot_be_merged_into_itself(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        lead = await _lead(tenant_a)
        with pytest.raises(ValidationError):
            await lifecycle_ops.merge_leads(
                tenant_id=tenant_a, actor_id=uuid4(), survivor_id=lead, loser_id=lead
            )

    async def test_merging_across_tenants_is_impossible(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, tenant_b = seeded_tenants
        mine = await _lead(tenant_a)
        theirs = await _lead(tenant_b)

        with pytest.raises(NotFound):
            await lifecycle_ops.merge_leads(
                tenant_id=tenant_a, actor_id=uuid4(), survivor_id=mine, loser_id=theirs
            )


class TestDisqualifyAndRestore:
    async def test_disqualification_records_a_reason(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        lead = await _lead(tenant_a)

        result = await lifecycle_ops.disqualify_lead(
            tenant_id=tenant_a, actor_id=uuid4(), lead_id=lead, reason="Budget under 50k"
        )

        assert result["status"] == "disqualified"
        assert result["disqualify_reason"] == "Budget under 50k"

    async def test_an_empty_reason_is_refused(self, wired_engine: Any, seeded_tenants: Any) -> None:
        """Three months later, no reason is indistinguishable from a mis-click."""
        tenant_a, _ = seeded_tenants
        lead = await _lead(tenant_a)
        with pytest.raises(ValidationError):
            await lifecycle_ops.disqualify_lead(
                tenant_id=tenant_a, actor_id=uuid4(), lead_id=lead, reason="  "
            )

    async def test_restore_reopens_and_clears_the_reason(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        lead = await _lead(tenant_a)
        await lifecycle_ops.disqualify_lead(
            tenant_id=tenant_a, actor_id=uuid4(), lead_id=lead, reason="Not now"
        )

        result = await lifecycle_ops.restore_lead(
            tenant_id=tenant_a, actor_id=uuid4(), lead_id=lead
        )

        assert result["status"] == "new"
        assert (await _get(tenant_a, lead)).disqualify_reason is None

    async def test_a_converted_lead_cannot_be_restored(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """A contact already exists downstream; reopening would fork the truth."""
        tenant_a, _ = seeded_tenants
        lead = await _lead(tenant_a, status="converted")
        with pytest.raises(Conflict):
            await lifecycle_ops.restore_lead(tenant_id=tenant_a, actor_id=uuid4(), lead_id=lead)

    async def test_an_open_lead_cannot_be_restored(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        lead = await _lead(tenant_a)
        with pytest.raises(Conflict):
            await lifecycle_ops.restore_lead(tenant_id=tenant_a, actor_id=uuid4(), lead_id=lead)

    async def test_a_merged_lead_points_at_its_survivor_instead_of_restoring(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        survivor = await _lead(tenant_a)
        loser = await _lead(tenant_a)
        await lifecycle_ops.merge_leads(
            tenant_id=tenant_a, actor_id=uuid4(), survivor_id=survivor, loser_id=loser
        )

        with pytest.raises(Conflict) as excinfo:
            await lifecycle_ops.restore_lead(tenant_id=tenant_a, actor_id=uuid4(), lead_id=loser)
        assert excinfo.value.details["survivor_id"] == str(survivor)


class TestDeduplicate:
    async def test_matching_leads_are_recorded_not_merged(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """An automatic merge on a fuzzy match destroys data nobody asked it to touch."""
        tenant_a, _ = seeded_tenants
        shared = f"twin-{uuid4().hex[:8]}@example.in"
        first = await _lead(tenant_a, email=shared)
        await _lead(tenant_a, email=shared)

        result = await lifecycle_ops.deduplicate(
            tenant_id=tenant_a, actor_id=uuid4(), lead_id=first
        )

        assert result["candidates"], "an exact email twin must be found"
        assert (await _get(tenant_a, first)).merged_into_id is None

        recorded = await lifecycle_ops.duplicate_candidates(tenant_id=tenant_a, lead_id=first)
        assert recorded and recorded[0]["resolution"] == "pending"

    async def test_running_it_twice_does_not_duplicate_the_candidates(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        shared = f"twin-{uuid4().hex[:8]}@example.in"
        first = await _lead(tenant_a, email=shared)
        await _lead(tenant_a, email=shared)

        await lifecycle_ops.deduplicate(tenant_id=tenant_a, actor_id=uuid4(), lead_id=first)
        await lifecycle_ops.deduplicate(tenant_id=tenant_a, actor_id=uuid4(), lead_id=first)

        recorded = await lifecycle_ops.duplicate_candidates(tenant_id=tenant_a, lead_id=first)
        assert len({row["candidate_lead_id"] for row in recorded}) == len(recorded)

    async def test_another_tenants_leads_are_never_candidates(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """An identical email in another tenant is not a duplicate. It is invisible.

        Asserted by naming the row that must not appear rather than by demanding an
        empty list: every lead in this module shares a first name and a source, so
        tenant A legitimately accumulates same-tenant candidates as the file runs,
        and an empty list stopped being the true answer for reasons that have
        nothing to do with tenancy.
        """
        tenant_a, tenant_b = seeded_tenants
        shared = f"twin-{uuid4().hex[:8]}@example.in"
        mine = await _lead(tenant_a, email=shared)
        theirs = await _lead(tenant_b, email=shared)

        result = await lifecycle_ops.deduplicate(tenant_id=tenant_a, actor_id=uuid4(), lead_id=mine)

        found = {candidate["lead_id"] for candidate in result["candidates"]}
        assert str(theirs) not in found
        # The exact-email match is what would have been found had tenancy leaked,
        # so nothing in tenant A may claim that reason either.
        assert not [c for c in result["candidates"] if c["match_reason"] == "email_exact"]
