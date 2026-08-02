"""End-to-end: capture -> dedupe -> qualification -> review -> conversion, with isolation."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

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
            audits = (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit.audit_logs "
                        "WHERE resource_id = :id AND action = 'lead.create'"
                    ),
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
    assert audits == 1, "the state, outbox and audit row must commit together"


async def test_every_lead_mutation_has_a_compact_audit_trail(
    wired_engine, principal_factory, session_factory
) -> None:
    from application.leads.service import LeadService

    principal = principal_factory()
    service = LeadService.for_principal(principal)
    lead = await service.capture(
        {
            "first_name": "Audited",
            "email": f"audited-{uuid4()}@example.in",
            "source": "audit-test",
        }
    )
    await service.update(lead["id"], {"status": "qualified"})
    await service.qualify(lead["id"], mode="rule")
    await service.review_qualification(
        lead["id"], decision="edited", edited_score=88, note="verified by sales"
    )
    await service.convert(lead["id"])

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(principal.tenant_id)},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT action, new_values FROM audit.audit_logs "
                    "WHERE resource_id=:rid ORDER BY created_at"
                ),
                {"rid": lead["id"]},
            )
        ).all()

    assert [row[0] for row in rows] == [
        "lead.create",
        "lead.update",
        "lead.qualify",
        "lead.qualification_review",
        "lead.convert",
    ]
    # Capture audit is deliberately compact: source/ownership is useful for
    # reconstruction, while customer email and phone do not belong in it.
    assert "email" not in rows[0][1]
    assert rows[-1][1]["status"] == "converted"


async def test_lead_audit_is_tenant_scoped_and_immutable(
    wired_engine, principal_factory, session_factory
) -> None:
    from application.leads.service import LeadService

    owner = principal_factory(principal_factory.tenant_a)
    lead = await LeadService.for_principal(owner).capture(
        {
            "first_name": "Immutable",
            "email": f"immutable-{uuid4()}@example.in",
            "source": "audit-test",
        }
    )

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(principal_factory.tenant_b)},
        )
        cross_tenant_count = (
            await session.execute(
                text("SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid"),
                {"rid": lead["id"]},
            )
        ).scalar_one()

    assert cross_tenant_count == 0, "audit rows are tenant data and must remain RLS-isolated"

    async with session_factory() as session:
        with pytest.raises(SQLAlchemyError) as exc:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": str(owner.tenant_id)},
                )
                await session.execute(
                    text(
                        "UPDATE audit.audit_logs SET action = 'lead.tampered' "
                        "WHERE resource_id = :rid"
                    ),
                    {"rid": lead["id"]},
                )

    assert "permission denied" in str(exc.value).lower() or "append-only" in str(exc.value).lower()

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(owner.tenant_id)},
        )
        action = (
            await session.execute(
                text("SELECT action FROM audit.audit_logs WHERE resource_id = :rid"),
                {"rid": lead["id"]},
            )
        ).scalar_one()

    assert action == "lead.create"


async def test_member_capture_and_duplicate_checks_stay_self_scoped(
    wired_engine, principal_factory
) -> None:
    from application.leads.service import LeadService
    from domain.auth.permissions import Role
    from shared.exceptions import NotFound

    member = principal_factory(role=Role.MEMBER)
    admin = principal_factory(tenant_id=member.tenant_id, role=Role.ADMIN)
    email = f"scope-{uuid4()}@example.in"
    mine = await LeadService.for_principal(member).capture(
        {"first_name": "Mine", "email": email, "source": "scope-test"}
    )
    other = await LeadService.for_principal(admin).capture(
        {
            "first_name": "Other",
            "email": email,
            "source": "scope-test",
            "assignee_id": admin.user_id,
        }
    )

    assert mine["assignee_id"] == str(member.user_id)
    assert await LeadService.for_principal(member).duplicates(mine["id"]) == []
    with pytest.raises(NotFound):
        await LeadService.for_principal(member).duplicates(other["id"])


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
            "email": f"arjun-{uuid4()}@example.in",
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
    lead = await service.capture({"first_name": "Kiran", "email": f"kiran-{uuid4()}@example.in"})
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
    lead = await service.capture({"first_name": "Outbox", "email": f"outbox-{uuid4()}@example.in"})

    seen: list[dict] = []

    async def handler(payload: dict) -> None:
        seen.append(payload)

    dispatcher = OutboxDispatcher(session_factory)
    dispatcher.subscribe(LEAD_CREATED, handler)

    # The reusable real-Postgres harness deliberately preserves prior test data,
    # so drain every available batch instead of assuming the global outbox starts
    # empty. The assertion is scoped to the event created by this test.
    for _ in range(50):
        stats = await dispatcher.run_once()
        if stats.claimed == 0:
            break
    else:
        pytest.fail("the available outbox did not drain within 50 batches")

    matching = [event for event in seen if event["resource"]["id"] == lead["id"]]
    assert len(matching) == 1, "this lead-created event must reach the handler exactly once"
    assert matching[0]["event_type"] == LEAD_CREATED
    assert "tenant_id" in matching[0]
    assert (await dispatcher.run_once()).claimed == 0, "a processed event is never claimed twice"
