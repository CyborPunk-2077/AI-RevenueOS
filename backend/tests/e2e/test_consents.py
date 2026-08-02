"""Consent evidence, tenant isolation and revocation on real PostgreSQL."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.e2e.test_crm_contacts_accounts import (  # noqa: F401
    ACME_EMAIL,
    GLOBEX_EMAIL,
    client,
    demo_data,
    fake_redis,
    make_contact,
    sign_in,
    wired_engine,
)
from tests.e2e.test_crm_inbox import open_conversation

pytestmark = pytest.mark.postgres


def grant(
    client: TestClient,
    headers: dict[str, str],
    contact_id: str,
    *,
    consent_type: str = "communication",
    channel: str = "email",
) -> dict[str, Any]:
    response = client.post(
        "/v1/consents",
        headers=headers,
        json={
            "subject_type": "contact",
            "subject_id": contact_id,
            "consent_type": consent_type,
            "channel": channel,
            "policy_version": "dpdp-draft-1",
            "source": "agent_confirmed",
            "evidence": {"capture_method": "recorded_call", "notice_shown": True},
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def test_grant_is_idempotent_and_tenant_private(client: TestClient) -> None:
    acme = sign_in(client, ACME_EMAIL)
    globex = sign_in(client, GLOBEX_EMAIL)
    contact = make_contact(client, acme)

    first = grant(client, acme, contact["id"])
    duplicate = grant(client, acme, contact["id"])
    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["id"] == first["id"]

    listed = client.get("/v1/consents", headers=acme, params={"subject_id": contact["id"]}).json()[
        "data"
    ]
    assert [row["id"] for row in listed] == [first["id"]]
    assert (
        client.get("/v1/consents", headers=globex, params={"subject_id": contact["id"]}).status_code
        == 404
    )


def test_withdrawal_cancels_queued_messages_and_blocks_new_ones(client: TestClient) -> None:
    headers = sign_in(client, ACME_EMAIL)
    contact = make_contact(client, headers)
    consent = grant(client, headers, contact["id"])
    conversation = open_conversation(
        client, headers, contact_id=contact["id"], primary_channel="email"
    )
    queued = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        headers=headers,
        json={"content": "Before withdrawal"},
    )
    assert queued.status_code == 201, queued.text

    withdrawn = client.post(
        f"/v1/consents/{consent['id']}/withdraw",
        headers=headers,
        json={"reason": "Recipient opted out"},
    )
    assert withdrawn.status_code == 200, withdrawn.text
    assert withdrawn.json()["data"]["cancelled_messages"] == 1
    repeated = client.post(
        f"/v1/consents/{consent['id']}/withdraw",
        headers=headers,
        json={"reason": "Recipient opted out"},
    )
    assert repeated.status_code == 200
    assert repeated.json()["data"]["duplicate"] is True

    thread = client.get(f"/v1/conversations/{conversation['id']}/messages", headers=headers).json()[
        "data"
    ]["messages"]
    assert thread[-1]["status"] == "failed"
    blocked = client.post(
        f"/v1/conversations/{conversation['id']}/messages",
        headers=headers,
        json={"content": "Must not queue"},
    )
    assert blocked.status_code == 422
    assert blocked.json()["error"]["details"]["consent_required"] is True


def test_grant_and_withdrawal_commit_audit_and_outbox(
    client: TestClient, wired_engine: Any
) -> None:
    import asyncio

    from sqlalchemy import text

    headers = sign_in(client, ACME_EMAIL)
    tenant_id = client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"]
    contact = make_contact(client, headers)
    consent = grant(client, headers, contact["id"])
    withdrawn = client.post(
        f"/v1/consents/{consent['id']}/withdraw",
        headers=headers,
        json={"reason": "No longer consented"},
    ).json()["data"]

    async def evidence() -> tuple[set[str], set[str]]:
        async with wired_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
            )
            ids = [consent["id"], withdrawn["id"]]
            actions = set(
                (
                    await conn.execute(
                        text(
                            "SELECT action FROM audit.audit_logs "
                            "WHERE resource_id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": ids},
                    )
                ).scalars()
            )
            events = set(
                (
                    await conn.execute(
                        text(
                            "SELECT event_type FROM audit.event_outbox "
                            "WHERE resource_id = ANY(CAST(:ids AS uuid[]))"
                        ),
                        {"ids": ids},
                    )
                ).scalars()
            )
            return actions, events

    actions, events = asyncio.new_event_loop().run_until_complete(evidence())
    assert {"consent.granted", "consent.revoked"} <= actions
    assert {"consent.granted", "consent.revoked"} <= events
