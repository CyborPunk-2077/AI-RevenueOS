"""Conversations and messages over HTTP against real PostgreSQL with RLS forced.

The load-bearing assertions here are the two things this module could get
dangerously wrong: writing into a partitioned table, and claiming a message was
delivered when no provider exists to deliver it.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

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


def open_conversation(
    client: TestClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    payload = {"subject": f"Thread {uuid4().hex[:6]}", "primary_channel": "web_chat", **overrides}
    response = client.post("/v1/conversations", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def receive(client: TestClient, headers: dict[str, str], cid: str, content: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/conversations/{cid}/inbound", headers=headers, json={"content": content}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def reply(client: TestClient, headers: dict[str, str], cid: str, content: str) -> dict[str, Any]:
    response = client.post(
        f"/v1/conversations/{cid}/messages", headers=headers, json={"content": content}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestConversations:
    def test_open_list_and_read(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers, subject="Broken invoice")

        listed = client.get("/v1/conversations", headers=headers).json()["data"]["conversations"]
        assert any(c["id"] == conversation["id"] for c in listed)

        opened = client.get(f"/v1/conversations/{conversation['id']}", headers=headers)
        assert opened.status_code == 200
        assert opened.json()["data"]["subject"] == "Broken invoice"
        assert opened.json()["data"]["status"] == "active"

    def test_a_conversation_can_be_linked_to_a_contact(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers, first_name="Nisha")
        conversation = open_conversation(client, headers, contact_id=contact["id"])
        assert conversation["contact_name"].startswith("Nisha")

    def test_it_cannot_be_linked_to_another_tenants_contact(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        acme_contact = make_contact(client, acme)

        response = client.post(
            "/v1/conversations",
            headers=globex,
            json={"subject": "Cross tenant", "contact_id": acme_contact["id"]},
        )
        assert response.status_code == 404

    def test_resolving_and_assigning(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        me = client.get("/v1/auth/me", headers=headers).json()["data"]
        conversation = open_conversation(client, headers)

        updated = client.patch(
            f"/v1/conversations/{conversation['id']}",
            headers={**headers, "If-Match": f'W/"{conversation["version"]}"'},
            json={"status": "resolved", "assignee_id": me["id"]},
        )
        assert updated.status_code == 200
        body = updated.json()["data"]
        assert body["status"] == "resolved"
        assert body["assignee_name"] == "Asha Kumar"

    def test_an_unknown_status_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        response = client.patch(
            f"/v1/conversations/{conversation['id']}", headers=headers, json={"status": "burning"}
        )
        assert response.status_code == 422

    def test_a_stale_edit_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        stale = f'W/"{conversation["version"]}"'
        assert (
            client.patch(
                f"/v1/conversations/{conversation['id']}",
                headers={**headers, "If-Match": stale},
                json={"subject": "First"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/v1/conversations/{conversation['id']}",
                headers={**headers, "If-Match": stale},
                json={"subject": "Second"},
            ).status_code
            == 412
        )

    def test_the_status_filter_matches(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        client.patch(
            f"/v1/conversations/{conversation['id']}", headers=headers, json={"status": "resolved"}
        )

        resolved = client.get("/v1/conversations?status=resolved", headers=headers).json()["data"][
            "conversations"
        ]
        assert any(c["id"] == conversation["id"] for c in resolved)
        assert all(c["status"] == "resolved" for c in resolved)


class TestThread:
    def test_inbound_lands_in_the_thread_and_bumps_unread(self, client: TestClient) -> None:
        """This is the partitioned write. If the partition were missing it would raise."""
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)

        message = receive(client, headers, conversation["id"], "My order never arrived")
        assert message["direction"] == "inbound"
        # Inbound is delivered by definition -- it already got here.
        assert message["status"] == "delivered"

        thread = client.get(
            f"/v1/conversations/{conversation['id']}/messages", headers=headers
        ).json()["data"]["messages"]
        assert [m["content"] for m in thread] == ["My order never arrived"]

        after = client.get(f"/v1/conversations/{conversation['id']}", headers=headers).json()[
            "data"
        ]
        assert after["unread_count"] == 1
        assert after["last_message_at"] is not None

    def test_marking_read_clears_the_counter_and_is_idempotent(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        receive(client, headers, conversation["id"], "Hello")

        for _ in range(2):
            body = client.post(
                f"/v1/conversations/{conversation['id']}/read", headers=headers
            ).json()["data"]
            assert body["unread_count"] == 0

    def test_the_thread_reads_oldest_first(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        receive(client, headers, conversation["id"], "First")
        reply(client, headers, conversation["id"], "Second")
        receive(client, headers, conversation["id"], "Third")

        thread = client.get(
            f"/v1/conversations/{conversation['id']}/messages", headers=headers
        ).json()["data"]["messages"]
        assert [m["content"] for m in thread] == ["First", "Second", "Third"]

    def test_an_empty_message_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        assert (
            client.post(
                f"/v1/conversations/{conversation['id']}/messages",
                headers=headers,
                json={"content": "   "},
            ).status_code
            == 422
        )

    def test_a_message_has_no_update_or_delete_route(self, client: TestClient) -> None:
        """Immutable in both directions, enforced by there being nothing to call."""
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        message = receive(client, headers, conversation["id"], "Permanent")

        for method in ("patch", "delete"):
            response = getattr(client, method)(
                f"/v1/messages/{message['id']}",
                headers=headers,
                **({"json": {}} if method == "patch" else {}),
            )
            assert response.status_code == 404


class TestOutboundIsGatedNeverFaked:
    """The point of the whole design: no fabricated delivery."""

    def test_a_reply_is_queued_not_sent(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers, primary_channel="whatsapp")
        message = reply(client, headers, conversation["id"], "We are looking into it")

        assert message["status"] == "queued"
        assert message["status"] not in {"sent", "delivered", "read"}
        assert message["delivered_at"] is None
        assert message["provider_ready"] is False
        assert "no provider credential" in message["delivery_note"].lower()
        assert "whatsapp" in (message["failure_reason"] or "").lower()

    def test_the_same_holds_for_email(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers, primary_channel="email")
        message = reply(client, headers, conversation["id"], "Thanks for writing in")
        assert message["status"] == "queued"
        assert message["provider_ready"] is False

    def test_channel_readiness_reports_honestly(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        channels = {
            c["channel"]: c["ready"]
            for c in client.get("/v1/conversations/channels", headers=headers).json()["data"][
                "channels"
            ]
        }
        # First-party channel, no credential to obtain.
        assert channels["web_chat"] is True
        # Everything needing an external provider is off until one exists.
        assert channels["whatsapp"] is False
        assert channels["email"] is False
        assert channels["voice"] is False

    def test_a_reply_on_a_ready_channel_is_still_only_queued(self, client: TestClient) -> None:
        """Even the enabled channel does not claim delivery from the API alone."""
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers, primary_channel="web_chat")
        message = reply(client, headers, conversation["id"], "Hello there")
        assert message["status"] == "queued"
        assert message["provider_ready"] is True
        assert message["failure_reason"] is None

    def test_an_agent_reply_stops_automation(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        conversation = open_conversation(client, headers)
        assert conversation["automation_stopped"] is False

        reply(client, headers, conversation["id"], "A human is handling this")
        after = client.get(f"/v1/conversations/{conversation['id']}", headers=headers).json()[
            "data"
        ]
        assert after["automation_stopped"] is True


class TestInboxTenantIsolation:
    def test_another_tenant_cannot_read_the_conversation_or_thread(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        conversation = open_conversation(client, acme, subject="AcmeSecretThread")
        receive(client, acme, conversation["id"], "Confidential")

        assert (
            client.get(f"/v1/conversations/{conversation['id']}", headers=globex).status_code == 404
        )
        # 404, not an empty thread: an empty list would confirm the id exists.
        assert (
            client.get(
                f"/v1/conversations/{conversation['id']}/messages", headers=globex
            ).status_code
            == 404
        )

    def test_another_tenant_cannot_post_into_the_thread(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        conversation = open_conversation(client, acme)

        for path in ("messages", "inbound"):
            assert (
                client.post(
                    f"/v1/conversations/{conversation['id']}/{path}",
                    headers=globex,
                    json={"content": "Intrusion"},
                ).status_code
                == 404
            )

        thread = client.get(
            f"/v1/conversations/{conversation['id']}/messages", headers=acme
        ).json()["data"]["messages"]
        assert thread == []

    def test_another_tenant_cannot_resolve_it(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        conversation = open_conversation(client, acme)

        assert (
            client.patch(
                f"/v1/conversations/{conversation['id']}",
                headers=globex,
                json={"status": "resolved"},
            ).status_code
            == 404
        )
        assert (
            client.get(f"/v1/conversations/{conversation['id']}", headers=acme).json()["data"][
                "status"
            ]
            == "active"
        )

    def test_neither_inbox_shows_the_others_threads(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        conversation = open_conversation(client, acme, subject="AcmeOnlyThread")

        globex_ids = {
            c["id"]
            for c in client.get("/v1/conversations?page_size=200", headers=globex).json()["data"][
                "conversations"
            ]
        }
        assert conversation["id"] not in globex_ids

    def test_an_anonymous_caller_is_refused(self, client: TestClient) -> None:
        for method, path in (
            ("get", "/v1/conversations"),
            ("post", "/v1/conversations"),
            ("get", "/v1/conversations/channels"),
        ):
            assert getattr(client, method)(path).status_code == 401


class TestInboxEventsAndAudit:
    def test_inbound_and_outbound_emit_their_own_events(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        conversation = open_conversation(client, headers)
        receive(client, headers, conversation["id"], "Inbound one")
        message = reply(client, headers, conversation["id"], "Outbound one")

        async def counts() -> tuple[int, int, int]:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                received = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'conversation.message_received'"
                    ),
                    {"rid": conversation["id"]},
                )
                queued = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'message.queued'"
                    ),
                    {"rid": message["id"]},
                )
                audits = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid "
                        "AND action = 'message.queue'"
                    ),
                    {"rid": message["id"]},
                )
                return (
                    int(received.scalar_one()),
                    int(queued.scalar_one()),
                    int(audits.scalar_one()),
                )

        received, queued, audits = asyncio.new_event_loop().run_until_complete(counts())
        assert received == 1
        assert queued == 1
        assert audits == 1

    def test_the_message_landed_in_this_months_partition(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        """Proves the partitioned write actually reached a child table."""
        import asyncio

        from sqlalchemy import text

        from shared.utils.timeutil import utcnow

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        conversation = open_conversation(client, headers)
        message = receive(client, headers, conversation["id"], "Partitioned")

        suffix = utcnow().strftime("%Y%m")

        async def in_partition() -> int:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                # The partition name is derived from the server clock, not from
                # user input; the id is still bound as a parameter.
                result = await conn.execute(
                    text(f"SELECT count(*) FROM app.messages_p{suffix} WHERE id = :mid"),  # noqa: S608
                    {"mid": message["id"]},
                )
                return int(result.scalar_one())

        assert asyncio.new_event_loop().run_until_complete(in_partition()) == 1
