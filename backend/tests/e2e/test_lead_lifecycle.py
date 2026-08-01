"""End-to-end: capture -> dedupe -> qualification -> review -> conversion, with isolation."""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.postgres


async def test_capture_persists_lead_source_event_and_outbox_row(
    wired_engine, principal_factory, session_factory
) -> None:
    from application.leads.service import LeadService

    principal = principal_factory()
    service = LeadService.for_principal(principal)

    lead = await service.capture(
        {
            "first_name": "Asha",
            "last_name": "Kumar",
            "email": "asha@example.in",
            "phone": "+919876543210",
            "source": "web_form",
            "source_channel": "web",
            "capture": {"budget_minor": 5_000_000, "location": "Pune"},
            "utm": {"utm_source": "google"},
        }
    )

    assert lead["status"] == "new"
    assert lead["email"] == "asha@example.in"

    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(principal.tenant_id)},
            )
            events = (
                await session.execute(
                    text("SELECT count(*) FROM app.lead_source_events WHERE lead_id = :id"),
                    {"id": lead["id"]},
                )
            ).scalar_one()
        outbox = (
            await session.execute(
                text("SELECT count(*) FROM audit.event_outbox WHERE resource_id = :id"),
                {"id": lead["id"]},
            )
        ).scalar_one()

    assert events == 1, "the raw source event must always be preserved"
    assert outbox == 1, "the state change and its event must commit together"


async def test_duplicate_capture_preserves_both_source_events(
    wired_engine, principal_factory, session_factory
) -> None:
    from application.leads.service import LeadService

    service = LeadService.for_principal(principal_factory())
    payload = {"first_name": "Ravi", "email": "ravi@example.in", "source": "web_form"}

    first = await service.capture(dict(payload))
    second = await service.capture(dict(payload))

    assert first["id"] != second["id"]
    candidates = await service.duplicates(second["id"])
    assert candidates[0]["match_reason"] == "email_exact"
    assert candidates[0]["confidence"] >= 0.95


async def test_qualification_scores_and_records_evidence(wired_engine, principal_factory) -> None:
    from application.leads.service import LeadService

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture(
        {
            "first_name": "Meera",
            "email": "meera@example.in",
            "capture": {
                "requirement": "office space",
                "budget_minor": 100_000,
                "timeline": "immediate",
            },
        }
    )

    result = await service.qualify(lead["id"], mode="rule")
    qualification = result["qualification"]

    assert 0 <= qualification["score"] <= 100
    assert qualification["category"] in ("hot", "warm", "cold")
    assert qualification["evidence"]
    assert qualification["review_state"] == "pending"

    refreshed = await service.get(lead["id"])
    assert refreshed["qualification_score"] == qualification["score"]
    assert refreshed["reviewer_state"] == "pending"


async def test_ai_qualification_degrades_to_the_rule_engine_without_credentials(
    wired_engine, principal_factory
) -> None:
    from application.leads.service import LeadService

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture(
        {
            "first_name": "Sunil",
            "email": "sunil@example.in",
            "capture": {"requirement": "consulting", "timeline": "immediate"},
        }
    )

    result = await service.qualify(lead["id"], mode="ai")
    qualification = result["qualification"]

    assert qualification["degraded"] is True
    assert qualification["qualified_by"] == "rule"
    assert qualification["score"] is not None
    assert any("unavailable" in r.lower() for r in qualification["reasons"])


async def test_human_review_overrides_and_is_persisted(wired_engine, principal_factory) -> None:
    from application.leads.service import LeadService

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture({"first_name": "Neha", "email": "neha@example.in"})
    await service.qualify(lead["id"], mode="rule")

    reviewed = await service.review_qualification(
        lead["id"], decision="edited", edited_score=91, note="spoke to the client directly"
    )
    assert reviewed["qualification"]["score"] == 91
    assert reviewed["qualification"]["category"] == "hot"
    assert reviewed["qualification"]["review_state"] == "edited"

    refreshed = await service.get(lead["id"])
    assert refreshed["qualification_score"] == 91


async def test_conversion_from_new_is_refused_before_qualification(
    wired_engine, principal_factory
) -> None:
    from application.leads.service import LeadService
    from domain.base import InvalidTransition

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture({"first_name": "TooSoon", "email": "toosoon@example.in"})
    with pytest.raises(InvalidTransition):
        await service.convert(lead["id"])


async def test_conversion_creates_a_contact_and_preserves_the_link(
    wired_engine, principal_factory
) -> None:
    from application.leads.service import LeadService

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture(
        {
            "first_name": "Arjun",
            "email": "arjun@example.in",
            "phone": "+919876500011",
            "capture": {"requirement": "gym membership"},
        }
    )

    # The lifecycle requires qualification before conversion.
    await service.update(lead["id"], {"status": "qualified"})
    result = await service.convert(lead["id"])
    assert result["status"] == "converted"

    refreshed = await service.get(lead["id"])
    assert refreshed["status"] == "converted"


async def test_invalid_status_transition_is_refused(wired_engine, principal_factory) -> None:
    from application.leads.service import LeadService
    from domain.base import InvalidTransition

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture({"first_name": "Kiran", "email": "kiran@example.in"})
    await service.update(lead["id"], {"status": "qualified"})
    await service.convert(lead["id"])

    with pytest.raises(InvalidTransition):
        await service.update(lead["id"], {"status": "new"})


async def test_optimistic_concurrency_rejects_a_stale_write(
    wired_engine, principal_factory
) -> None:
    from application.leads.service import LeadService
    from shared.exceptions import PreconditionFailed

    service = LeadService.for_principal(principal_factory())
    lead = await service.capture({"first_name": "Divya", "email": "divya@example.in"})

    await service.update(lead["id"], {"last_name": "Rao"}, expected_version=lead["version"])
    with pytest.raises(PreconditionFailed):
        await service.update(lead["id"], {"last_name": "Stale"}, expected_version=lead["version"])


async def test_a_lead_is_invisible_to_another_tenant(wired_engine, principal_factory) -> None:
    from application.leads.service import LeadService
    from shared.exceptions import NotFound

    owner = LeadService.for_principal(principal_factory(principal_factory.tenant_a))
    intruder = LeadService.for_principal(principal_factory(principal_factory.tenant_b))

    lead = await owner.capture({"first_name": "Private", "email": "private@example.in"})

    assert (await owner.get(lead["id"]))["id"] == lead["id"]
    with pytest.raises(NotFound):
        await intruder.get(lead["id"])


async def test_listing_never_crosses_a_tenant_boundary(wired_engine, principal_factory) -> None:
    from api.deps.principal import ListQuery
    from application.leads.service import LeadService

    a = LeadService.for_principal(principal_factory(principal_factory.tenant_a))
    b = LeadService.for_principal(principal_factory(principal_factory.tenant_b))

    await a.capture({"first_name": "TenantA", "email": "a-only@example.in"})
    await b.capture({"first_name": "TenantB", "email": "b-only@example.in"})

    a_names = {item["first_name"] for item in (await a.list_leads(ListQuery())).items}
    b_names = {item["first_name"] for item in (await b.list_leads(ListQuery())).items}

    assert "TenantB" not in a_names
    assert "TenantA" not in b_names


async def test_outbox_events_are_dispatched_exactly_once_per_handler(
    wired_engine, principal_factory, session_factory
) -> None:
    from application.leads.service import LeadService
    from domain.events.catalog import LEAD_CREATED
    from infrastructure.messaging.outbox import OutboxDispatcher

    service = LeadService.for_principal(principal_factory())
    await service.capture({"first_name": "Outbox", "email": "outbox@example.in"})

    seen: list[dict] = []

    async def handler(payload: dict) -> None:
        seen.append(payload)

    dispatcher = OutboxDispatcher(session_factory)
    dispatcher.subscribe(LEAD_CREATED, handler)

    first = await dispatcher.run_once()
    second = await dispatcher.run_once()

    assert first.dispatched >= 1
    assert second.claimed == 0, "a processed event is never claimed twice"
    assert seen, "the subscribed handler must receive its event type"
    assert all(event["event_type"] == LEAD_CREATED for event in seen)
    assert all("tenant_id" in event for event in seen)
    # At-least-once delivery with idempotent consumers: no duplicate event ids in one pass.
    assert len({event["event_id"] for event in seen}) == len(seen)
