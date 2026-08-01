"""Appointments over HTTP against real PostgreSQL with RLS forced.

The assertion that matters most is double booking: it must be refused by the
`slot_locks` unique constraint, not by a read-then-write check that two
concurrent requests would both pass.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from shared.utils.timeutil import utcnow
from tests.e2e.test_crm_contacts_accounts import (  # noqa: F401
    ACME_EMAIL,
    GLOBEX_EMAIL,
    client,
    demo_data,
    fake_redis,
    make_account,
    make_contact,
    sign_in,
    wired_engine,
)

pytestmark = pytest.mark.postgres


def soon(hours: int = 24) -> str:
    return (utcnow() + timedelta(hours=hours)).isoformat()


def book(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {"title": f"Site visit {uuid4().hex[:6]}", "start_at": soon(), **overrides}
    response = client.post("/v1/appointments", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestBooking:
    def test_book_read_and_list(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        appointment = book(client, headers, title="Kitchen measurement")

        assert appointment["status"] == "scheduled"
        assert appointment["organizer_name"] == "Asha Kumar"
        # Calendar sync is gated, so nothing pretends an event was created.
        assert appointment["calendar_event_id"] is None

        listed = client.get("/v1/appointments", headers=headers).json()["data"]["appointments"]
        assert any(a["id"] == appointment["id"] for a in listed)
        assert (
            client.get(f"/v1/appointments/{appointment['id']}", headers=headers).status_code == 200
        )

    def test_it_can_be_linked_to_a_contact(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers, first_name="Rahul")
        appointment = book(client, headers, contact_id=contact["id"])
        assert appointment["contact_name"].startswith("Rahul")

        on_contact = client.get(
            f"/v1/contacts/{contact['id']}/appointments", headers=headers
        ).json()["data"]["appointments"]
        assert [a["id"] for a in on_contact] == [appointment["id"]]

    def test_booking_in_the_past_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/appointments",
            headers=headers,
            json={"title": "Yesterday", "start_at": soon(hours=-48)},
        )
        assert response.status_code == 422

    def test_an_unknown_location_type_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/appointments",
            headers=headers,
            json={"title": "X", "start_at": soon(), "location_type": "teleport"},
        )
        assert response.status_code == 422

    def test_the_upcoming_filter_excludes_the_past_and_the_cancelled(
        self, client: TestClient
    ) -> None:
        headers = sign_in(client, ACME_EMAIL)
        future = book(client, headers, start_at=soon(hours=48))
        cancelled = book(client, headers, start_at=soon(hours=72))
        client.post(f"/v1/appointments/{cancelled['id']}/cancel", headers=headers, json={})

        upcoming = client.get("/v1/appointments?upcoming=true", headers=headers).json()["data"][
            "appointments"
        ]
        ids = {a["id"] for a in upcoming}
        assert future["id"] in ids
        assert cancelled["id"] not in ids


class TestDoubleBookingIsRefusedByTheDatabase:
    def test_the_same_organiser_and_instant_is_a_conflict(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        when = soon(hours=30)
        book(client, headers, start_at=when)

        clash = client.post(
            "/v1/appointments", headers=headers, json={"title": "Clashing", "start_at": when}
        )
        assert clash.status_code == 409
        assert "already booked" in clash.json()["error"]["message"].lower()

    def test_the_failed_booking_left_nothing_behind(self, client: TestClient) -> None:
        """The appointment and its lock commit together, so a refusal rolls back both."""
        headers = sign_in(client, ACME_EMAIL)
        when = soon(hours=31)
        book(client, headers, start_at=when)
        client.post("/v1/appointments", headers=headers, json={"title": "Ghost", "start_at": when})

        titles = [
            a["title"]
            for a in client.get("/v1/appointments?page_size=200", headers=headers).json()["data"][
                "appointments"
            ]
        ]
        assert "Ghost" not in titles

    def test_a_different_instant_is_fine(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        book(client, headers, start_at=soon(hours=40))
        second = client.post(
            "/v1/appointments",
            headers=headers,
            json={"title": "Later", "start_at": soon(hours=41)},
        )
        assert second.status_code == 201

    def test_cancelling_releases_the_slot_for_rebooking(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        when = soon(hours=50)
        first = book(client, headers, start_at=when)

        assert (
            client.post(
                "/v1/appointments", headers=headers, json={"title": "Blocked", "start_at": when}
            ).status_code
            == 409
        )

        client.post(f"/v1/appointments/{first['id']}/cancel", headers=headers, json={})

        # A cancelled slot that stays locked is a slot nobody can ever book again.
        rebooked = client.post(
            "/v1/appointments", headers=headers, json={"title": "Rebooked", "start_at": when}
        )
        assert rebooked.status_code == 201

    def test_two_tenants_may_book_the_same_instant(self, client: TestClient) -> None:
        """The lock is per tenant; one organisation's diary is not the other's."""
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        when = soon(hours=60)

        book(client, acme, start_at=when)
        other = client.post(
            "/v1/appointments", headers=globex, json={"title": "Globex", "start_at": when}
        )
        assert other.status_code == 201


class TestRescheduleCancelOutcome:
    def test_reschedule_moves_it_and_frees_the_old_slot(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        original = soon(hours=70)
        appointment = book(client, headers, start_at=original)

        moved = client.post(
            f"/v1/appointments/{appointment['id']}/reschedule",
            headers={**headers, "If-Match": f'W/"{appointment["version"]}"'},
            json={"start_at": soon(hours=71)},
        )
        assert moved.status_code == 200
        assert moved.json()["data"]["start_at"] != appointment["start_at"]

        # The lock moved with it, so the original instant is bookable again.
        assert (
            client.post(
                "/v1/appointments",
                headers=headers,
                json={"title": "Takes the old slot", "start_at": original},
            ).status_code
            == 201
        )

    def test_rescheduling_onto_a_taken_slot_is_a_conflict(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        taken = soon(hours=80)
        book(client, headers, start_at=taken)
        movable = book(client, headers, start_at=soon(hours=81))

        clash = client.post(
            f"/v1/appointments/{movable['id']}/reschedule",
            headers=headers,
            json={"start_at": taken},
        )
        assert clash.status_code == 409

    def test_a_past_appointment_cannot_be_rescheduled(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        """The domain policy refuses it; the API must surface that, not a 500."""
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        appointment = book(client, headers, start_at=soon(hours=90))

        async def drag_into_the_past() -> None:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                await conn.execute(
                    text(
                        "UPDATE app.appointments SET start_at = now() - interval '2 hours', "
                        "end_at = now() - interval '1 hour' WHERE id = :aid"
                    ),
                    {"aid": appointment["id"]},
                )

        asyncio.new_event_loop().run_until_complete(drag_into_the_past())

        response = client.post(
            f"/v1/appointments/{appointment['id']}/reschedule",
            headers=headers,
            json={"start_at": soon(hours=100)},
        )
        assert response.status_code == 422
        assert "past" in response.json()["error"]["message"].lower()

    def test_cancelling_twice_is_a_conflict(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        appointment = book(client, headers, start_at=soon(hours=110))
        assert (
            client.post(
                f"/v1/appointments/{appointment['id']}/cancel",
                headers=headers,
                json={"reason": "Customer rang"},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/v1/appointments/{appointment['id']}/cancel", headers=headers, json={}
            ).status_code
            == 409
        )

    def test_recording_an_outcome(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        appointment = book(client, headers, start_at=soon(hours=120))

        done = client.post(
            f"/v1/appointments/{appointment['id']}/outcome",
            headers=headers,
            json={"status": "completed", "outcome": "quoted", "outcome_note": "Sending a quote"},
        )
        assert done.status_code == 200
        body = done.json()["data"]
        assert body["status"] == "completed"
        assert body["outcome"] == "quoted"

    def test_a_cancelled_appointment_has_no_outcome(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        appointment = book(client, headers, start_at=soon(hours=130))
        client.post(f"/v1/appointments/{appointment['id']}/cancel", headers=headers, json={})

        response = client.post(
            f"/v1/appointments/{appointment['id']}/outcome",
            headers=headers,
            json={"status": "completed"},
        )
        assert response.status_code == 422

    def test_a_stale_reschedule_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        appointment = book(client, headers, start_at=soon(hours=140))
        stale = f'W/"{appointment["version"]}"'

        assert (
            client.post(
                f"/v1/appointments/{appointment['id']}/reschedule",
                headers={**headers, "If-Match": stale},
                json={"start_at": soon(hours=141)},
            ).status_code
            == 200
        )
        assert (
            client.post(
                f"/v1/appointments/{appointment['id']}/reschedule",
                headers={**headers, "If-Match": stale},
                json={"start_at": soon(hours=142)},
            ).status_code
            == 412
        )


class TestCalendarSyncIsGated:
    def test_it_reports_honestly(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        body = client.get("/v1/appointments/calendar-sync", headers=headers).json()["data"]
        assert body["enabled"] is False
        assert "verification" in body["blocker"].lower()


class TestAppointmentTenantIsolation:
    def test_another_tenant_cannot_read_it(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        appointment = book(client, acme, title="AcmeSecretVisit", start_at=soon(hours=150))

        assert client.get(f"/v1/appointments/{appointment['id']}", headers=acme).status_code == 200
        assert (
            client.get(f"/v1/appointments/{appointment['id']}", headers=globex).status_code == 404
        )

    def test_another_tenant_cannot_cancel_or_reschedule_it(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        appointment = book(client, acme, start_at=soon(hours=160))

        assert (
            client.post(
                f"/v1/appointments/{appointment['id']}/cancel", headers=globex, json={}
            ).status_code
            == 404
        )
        assert (
            client.post(
                f"/v1/appointments/{appointment['id']}/reschedule",
                headers=globex,
                json={"start_at": soon(hours=161)},
            ).status_code
            == 404
        )
        assert (
            client.get(f"/v1/appointments/{appointment['id']}", headers=acme).json()["data"][
                "status"
            ]
            == "scheduled"
        )

    def test_it_cannot_be_booked_against_another_tenants_contact(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        acme_contact = make_contact(client, acme)

        response = client.post(
            "/v1/appointments",
            headers=globex,
            json={
                "title": "Cross tenant",
                "start_at": soon(hours=170),
                "contact_id": acme_contact["id"],
            },
        )
        assert response.status_code == 404

    def test_an_anonymous_caller_is_refused(self, client: TestClient) -> None:
        assert client.get("/v1/appointments").status_code == 401
        assert client.post("/v1/appointments", json={}).status_code == 401


class TestAppointmentEvents:
    def test_booking_and_cancelling_emit_their_events(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        appointment = book(client, headers, start_at=soon(hours=180))
        client.post(f"/v1/appointments/{appointment['id']}/cancel", headers=headers, json={})

        async def counts() -> tuple[int, int, int]:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                booked = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'appointment.booked'"
                    ),
                    {"rid": appointment["id"]},
                )
                cancelled = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'appointment.cancelled'"
                    ),
                    {"rid": appointment["id"]},
                )
                audits = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid "
                        "AND action = 'appointment.book'"
                    ),
                    {"rid": appointment["id"]},
                )
                return (
                    int(booked.scalar_one()),
                    int(cancelled.scalar_one()),
                    int(audits.scalar_one()),
                )

        booked, cancelled, audits = asyncio.new_event_loop().run_until_complete(counts())
        assert booked == 1
        assert cancelled == 1
        assert audits == 1
