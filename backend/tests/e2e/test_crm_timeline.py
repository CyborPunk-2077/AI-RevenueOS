"""Activities and notes on contacts and accounts, over HTTP against real PostgreSQL."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

# Fixtures and helpers are reused rather than duplicated. pytest resolves a
# fixture by the name bound in the module, so importing them is how sharing works
# outside a conftest; ruff sees the shadowing of the parameter names as a
# redefinition, which is exactly what pytest requires here.
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


def log_activity(
    client: TestClient, headers: dict[str, str], contact_id: str, **overrides: Any
) -> dict[str, Any]:
    payload = {"activity_type": "call", "subject": "Intro call", **overrides}
    response = client.post(f"/v1/contacts/{contact_id}/activities", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def add_note(
    client: TestClient, headers: dict[str, str], contact_id: str, **overrides: Any
) -> dict[str, Any]:
    payload = {"body": "Wants a quote by Friday.", **overrides}
    response = client.post(f"/v1/contacts/{contact_id}/notes", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestTimeline:
    def test_activities_and_notes_appear_together_newest_first(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)

        log_activity(client, headers, contact["id"], subject="First call")
        add_note(client, headers, contact["id"], body="Follow up next week")

        entries = client.get(f"/v1/contacts/{contact['id']}/timeline", headers=headers).json()[
            "data"
        ]["timeline"]
        assert len(entries) == 2
        assert {e["kind"] for e in entries} == {"activity", "note"}
        # Newest first.
        assert entries[0]["created_at"] >= entries[1]["created_at"]

    def test_the_timeline_names_who_did_what(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        log_activity(client, headers, contact["id"])

        entry = client.get(f"/v1/contacts/{contact['id']}/timeline", headers=headers).json()[
            "data"
        ]["timeline"][0]
        assert entry["actor_name"] == "Asha Kumar"
        assert entry["created_at"]

    def test_a_pinned_note_sorts_to_the_top(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        add_note(client, headers, contact["id"], body="Pinned", is_pinned=True)
        log_activity(client, headers, contact["id"], subject="Later call")

        entries = client.get(f"/v1/contacts/{contact['id']}/timeline", headers=headers).json()[
            "data"
        ]["timeline"]
        assert entries[0]["kind"] == "note" and entries[0]["is_pinned"] is True

    def test_an_empty_timeline_is_an_empty_list(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        response = client.get(f"/v1/contacts/{contact['id']}/timeline", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["timeline"] == []

    def test_accounts_have_a_timeline_too(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        response = client.post(
            f"/v1/accounts/{account['id']}/activities",
            headers=headers,
            json={"activity_type": "meeting", "subject": "QBR"},
        )
        assert response.status_code == 201
        entries = client.get(f"/v1/accounts/{account['id']}/timeline", headers=headers).json()[
            "data"
        ]["timeline"]
        assert entries[0]["subject"] == "QBR"

    def test_a_system_activity_cannot_be_forged(self, client: TestClient) -> None:
        """`system` and `status_change` are platform-written, never client-supplied."""
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        response = client.post(
            f"/v1/contacts/{contact['id']}/activities",
            headers=headers,
            json={"activity_type": "system", "subject": "Forged"},
        )
        assert response.status_code == 422

    def test_an_empty_note_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        response = client.post(
            f"/v1/contacts/{contact['id']}/notes", headers=headers, json={"body": "   "}
        )
        assert response.status_code == 422


class TestNoteAuthorship:
    def test_the_author_can_edit_their_note(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        note = add_note(client, headers, contact["id"], body="Original")
        assert note["editable"] is True

        edited = client.patch(
            f"/v1/notes/{note['id']}",
            headers={**headers, "If-Match": f'W/"{note["version"]}"'},
            json={"body": "Revised"},
        )
        assert edited.status_code == 200
        assert edited.json()["data"]["body"] == "Revised"

    def test_a_stale_note_edit_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        note = add_note(client, headers, contact["id"])
        stale = f'W/"{note["version"]}"'

        assert (
            client.patch(
                f"/v1/notes/{note['id']}",
                headers={**headers, "If-Match": stale},
                json={"body": "A"},
            ).status_code
            == 200
        )
        conflict = client.patch(
            f"/v1/notes/{note['id']}", headers={**headers, "If-Match": stale}, json={"body": "B"}
        )
        assert conflict.status_code == 412

    def test_an_activity_has_no_update_route_at_all(self, client: TestClient) -> None:
        """Append-only is enforced by there being nothing to call."""
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        activity = log_activity(client, headers, contact["id"])
        assert activity["editable"] is False

        for method in ("patch", "delete"):
            response = getattr(client, method)(
                f"/v1/activities/{activity['id']}",
                headers=headers,
                **({"json": {}} if method == "patch" else {}),
            )
            assert response.status_code == 404


class TestTimelineTenantIsolation:
    def test_another_tenant_gets_404_for_the_timeline(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme)
        log_activity(client, acme, contact["id"], subject="AcmeSecret")

        # 404, not an empty list: an empty list would confirm the id exists.
        cross = client.get(f"/v1/contacts/{contact['id']}/timeline", headers=globex)
        assert cross.status_code == 404
        assert cross.json()["error"]["code"] == "NOT_FOUND"

    def test_another_tenant_cannot_log_against_the_first_tenants_contact(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme)

        for path, payload in (
            (f"/v1/contacts/{contact['id']}/activities", {"activity_type": "call", "subject": "X"}),
            (f"/v1/contacts/{contact['id']}/notes", {"body": "X"}),
        ):
            assert client.post(path, headers=globex, json=payload).status_code == 404

    def test_another_tenants_note_is_not_editable(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme)
        note = add_note(client, acme, contact["id"], body="Acme only")

        cross = client.patch(f"/v1/notes/{note['id']}", headers=globex, json={"body": "Hijacked"})
        assert cross.status_code == 404

        after = client.get(f"/v1/contacts/{contact['id']}/timeline", headers=acme).json()["data"][
            "timeline"
        ][0]
        assert after["body"] == "Acme only"

    def test_an_unknown_parent_is_404(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        assert client.get(f"/v1/contacts/{uuid4()}/timeline", headers=headers).status_code == 404


class TestLastContactHandler:
    def test_logging_a_call_stamps_last_contact_at(self, client: TestClient) -> None:
        """A real handler, not a stub: the effect is observable on the contact."""
        import asyncio

        from application.crm.handlers import stamp_last_contact_at

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        contact = make_contact(client, headers)
        activity = log_activity(client, headers, contact["id"], activity_type="call")

        event = {
            "event_type": "activity.logged",
            "tenant_id": tenant_id,
            "resource_id": activity["id"],
            "payload": {
                "activity_type": "call",
                "entity_type": "contact",
                "entity_id": contact["id"],
            },
        }
        loop = asyncio.new_event_loop()
        loop.run_until_complete(stamp_last_contact_at(event))

        # Re-running must not change anything: the relay is at-least-once.
        loop.run_until_complete(stamp_last_contact_at(event))

        from sqlalchemy import text

        async def stamped() -> Any:
            from uuid import UUID as _UUID

            from infrastructure.database.session import tenant_session

            async with tenant_session(_UUID(tenant_id)) as session:
                row = await session.execute(
                    text("SELECT last_contact_at FROM app.contacts WHERE id = :cid"),
                    {"cid": contact["id"]},
                )
                return row.scalar_one()

        assert loop.run_until_complete(stamped()) is not None

    def test_a_note_does_not_count_as_contact(self, client: TestClient) -> None:
        """Writing a note to yourself is not an interaction with the person."""
        import asyncio
        from uuid import UUID as _UUID

        from application.crm.handlers import stamp_last_contact_at

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        contact = make_contact(client, headers)
        activity = log_activity(
            client, headers, contact["id"], activity_type="note", subject="memo"
        )

        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            stamp_last_contact_at(
                {
                    "event_type": "activity.logged",
                    "tenant_id": tenant_id,
                    "resource_id": activity["id"],
                    "payload": {
                        "activity_type": "note",
                        "entity_type": "contact",
                        "entity_id": contact["id"],
                    },
                }
            )
        )

        from sqlalchemy import text

        async def stamped() -> Any:
            from infrastructure.database.session import tenant_session

            async with tenant_session(_UUID(tenant_id)) as session:
                row = await session.execute(
                    text("SELECT last_contact_at FROM app.contacts WHERE id = :cid"),
                    {"cid": contact["id"]},
                )
                return row.scalar_one()

        assert loop.run_until_complete(stamped()) is None
