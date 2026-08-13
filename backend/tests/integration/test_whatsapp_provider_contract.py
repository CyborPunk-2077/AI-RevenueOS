"""What must be true about WhatsApp before a single real message is exchanged.

None of this needs Meta credentials, and that is the point. Every claim below is
one that would otherwise only be discovered by sending a real message to a real
person and watching it go wrong:

* a forged webhook is refused;
* the same event delivered twice changes nothing;
* an inbound message is an enquiry, not a reply;
* a reply the provider rejected never marks a prospect as answered;
* one workspace's WhatsApp traffic cannot reach another's records;
* a delivery status is only ever what the provider actually said.

The adapter is driven against a stub transport rather than the real Graph API, so
the payloads are Meta's shapes and the outcomes are ours.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select, text

from application.communications.whatsapp_ingest import (
    ingest_inbound_message,
    ingest_status_update,
    resolve_tenant,
)
from application.tenants.provisioning import (
    TEST,
    Person,
    WorkspaceSpec,
    provision_workspace,
)
from domain.auth.permissions import Role
from domain.leads.first_response import qualifies_as_first_response
from infrastructure.database.models.communications import Message
from infrastructure.database.models.leads import Lead
from infrastructure.database.session import admin_session
from infrastructure.integrations.whatsapp import WhatsAppAdapter
from shared.utils.ids import uuid7

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

TENANT_A = UUID("01890000-0000-7000-8000-0000000ba001")
TENANT_B = UUID("01890000-0000-7000-8000-0000000ba002")

PHONE_ID_A = "111111111111111"
PHONE_ID_B = "222222222222222"

APP_SECRET = "test-app-secret"
VERIFY_TOKEN = "test-verify-token"
HASH = "$2b$12$abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUV"

CUSTOMER = "+919845099001"


def adapter(*, client: httpx.AsyncClient | None = None, enabled: bool = True) -> WhatsAppAdapter:
    return WhatsAppAdapter(
        phone_number_id=PHONE_ID_A,
        access_token="test-token",
        app_secret=APP_SECRET,
        verify_token=VERIFY_TOKEN,
        enabled=enabled,
        client=client,
    )


def inbound_payload(*, phone_number_id: str, message_id: str, text_body: str) -> dict[str, Any]:
    """Meta's shape, not ours."""
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "WABA_ID",
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "919000000000",
                                "phone_number_id": phone_number_id,
                            },
                            "contacts": [
                                {"profile": {"name": "Ramesh"}, "wa_id": CUSTOMER.lstrip("+")}
                            ],
                            "messages": [
                                {
                                    "from": CUSTOMER.lstrip("+"),
                                    "id": message_id,
                                    "timestamp": "1760000000",
                                    "type": "text",
                                    "text": {"body": text_body},
                                }
                            ],
                        },
                    }
                ],
            }
        ],
    }


def status_payload(*, phone_number_id: str, message_id: str, status: str) -> dict[str, Any]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "statuses": [
                                {
                                    "id": message_id,
                                    "status": status,
                                    "timestamp": "1760000100",
                                    "recipient_id": CUSTOMER.lstrip("+"),
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


async def _register_channel(session: Any, tenant_id: UUID, identifier: str) -> None:
    await session.execute(
        text(
            "INSERT INTO app.channels (id, tenant_id, channel_type, identifier, display_name,"
            " settings, is_active, health_status, health_detail, version, created_at, updated_at)"
            " VALUES (:id, :t, 'whatsapp', :ident, 'Test number', '{}', true, 'healthy', '{}',"
            " 1, now(), now())"
            " ON CONFLICT DO NOTHING"
        ),
        {"id": uuid7(), "t": tenant_id, "ident": identifier},
    )


@pytest.fixture
async def workspaces() -> Any:
    """Two tenants, each owning a different WhatsApp business number.

    The engine is dropped either side of the test. These cases drive the real
    ingest path, which opens its own sessions from the application's cached
    engine, and pytest-asyncio gives every test a fresh event loop - so a pooled
    connection created under the previous loop is bound to a loop that no longer
    exists. Resetting is cheaper and clearer than threading a session in.
    """
    from infrastructure.database.session import install_pool_guards, reset_engine

    install_pool_guards.cache_clear()
    reset_engine()

    async with admin_session() as session:
        for tenant_id, slug, phone_id in (
            (TENANT_A, "wa-contract-a", PHONE_ID_A),
            (TENANT_B, "wa-contract-b", PHONE_ID_B),
        ):
            await provision_workspace(
                session,
                WorkspaceSpec(
                    tenant_id=tenant_id,
                    name=f"WhatsApp Contract {slug}",
                    slug=slug,
                    kind=TEST,
                    people=(
                        Person(
                            email=f"owner@{slug}.test",
                            full_name="Owner",
                            role=Role.OWNER,
                            scope="global",
                        ),
                    ),
                ),
                password_hash=HASH,
            )
            await _register_channel(session, tenant_id, phone_id)

    yield

    # `activities`, `audit_logs` and the outbox are absent on purpose: they are
    # append-only and the database refuses to delete from them. That refusal is a
    # feature - it is what preserved the evidence used to recover a destroyed
    # prospect in session 4B - so the cleanup works around it rather than against
    # it. The two tenants are left in place for the same reason, and provisioning
    # is idempotent, so a re-run reuses them.
    async with admin_session() as session:
        for table in (
            "messages",
            "conversations",
            "channels",
            "team_members",
            "teams",
            "branches",
            "user_roles",
            "role_permissions",
            "tasks",
            "notes",
            "leads",
            "users",
            "roles",
        ):
            await session.execute(
                text(f"DELETE FROM app.{table} WHERE tenant_id = ANY(:ids)"),  # noqa: S608
                {"ids": [TENANT_A, TENANT_B]},
            )

    install_pool_guards.cache_clear()
    reset_engine()


class TestWebhookSecurity:
    def test_a_correctly_signed_body_is_accepted(self) -> None:
        body = json.dumps({"hello": "world"}).encode()
        signature = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
        assert adapter().verify_webhook(
            body=body, headers={"x-hub-signature-256": f"sha256={signature}"}
        )

    def test_a_forged_signature_is_refused(self) -> None:
        body = json.dumps({"hello": "world"}).encode()
        assert not adapter().verify_webhook(
            body=body, headers={"x-hub-signature-256": "sha256=" + "0" * 64}
        )

    def test_a_body_altered_after_signing_is_refused(self) -> None:
        original = json.dumps({"amount": 1}).encode()
        signature = hmac.new(APP_SECRET.encode(), original, hashlib.sha256).hexdigest()
        tampered = json.dumps({"amount": 1000000}).encode()
        assert not adapter().verify_webhook(
            body=tampered, headers={"x-hub-signature-256": f"sha256={signature}"}
        )

    def test_a_missing_signature_header_is_refused(self) -> None:
        assert not adapter().verify_webhook(body=b"{}", headers={})

    def test_no_app_secret_means_nothing_is_trusted(self) -> None:
        """A misconfigured deployment must fail closed, not open."""
        blind = WhatsAppAdapter(
            phone_number_id=PHONE_ID_A, access_token="t", app_secret=None, enabled=True
        )
        body = b"{}"
        signature = hmac.new(b"", body, hashlib.sha256).hexdigest()
        assert not blind.verify_webhook(
            body=body, headers={"x-hub-signature-256": f"sha256={signature}"}
        )

    def test_subscription_verification_echoes_only_for_the_right_token(self) -> None:
        assert (
            adapter().verify_challenge(mode="subscribe", token=VERIFY_TOKEN, challenge="abc")
            == "abc"
        )
        assert adapter().verify_challenge(mode="subscribe", token="wrong", challenge="abc") is None
        assert (
            adapter().verify_challenge(mode="unsubscribe", token=VERIFY_TOKEN, challenge="abc")
            is None
        )


class TestParsing:
    def test_the_business_number_is_carried_through_for_routing(self) -> None:
        events = adapter().parse_webhook(
            inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.1", text_body="hi")
        )
        assert events[0]["business_phone_number_id"] == PHONE_ID_A
        assert events[0]["from"] == CUSTOMER
        assert events[0]["content"] == "hi"
        assert events[0]["profile_name"] == "Ramesh"


class TestInboundIngestion:
    async def test_an_unknown_number_becomes_a_prospect_nobody_has_answered(
        self, workspaces: Any
    ) -> None:
        events = adapter().parse_webhook(
            inbound_payload(
                phone_number_id=PHONE_ID_A, message_id="wamid.new", text_body="Do you do AMC?"
            )
        )
        result = await ingest_inbound_message(events[0])

        assert result.accepted
        assert result.created_lead
        assert result.tenant_id == TENANT_A

        async with admin_session() as session:
            lead = (
                await session.execute(select(Lead).where(Lead.id == result.lead_id))
            ).scalar_one()
            # The enquiry exists and is explicitly *not* answered.
            assert lead.first_response_at is None
            assert lead.phone == CUSTOMER
            assert lead.source == "whatsapp"
            # Nothing invented beyond what WhatsApp actually reported.
            assert lead.first_name == "Ramesh"
            assert lead.capture.get("demo_data") is None

    async def test_the_thread_inherits_the_prospects_owner_and_team(self, workspaces: Any) -> None:
        """A thread with no owner is invisible to everyone who is not global.

        The founder saw this as an Inbox that intermittently emptied: the
        conversation existed, the direct URL worked, and the list showed nothing,
        because scope filters on `team_id`/`assignee_id` and both were null.
        """
        from infrastructure.database.models.communications import Conversation

        result = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(
                    phone_number_id=PHONE_ID_A, message_id=f"wamid.{uuid7().hex}", text_body="hi"
                )
            )[0]
        )
        assert result.accepted

        owner = uuid7()
        team = uuid7()
        async with admin_session() as session:
            await session.execute(
                text("UPDATE app.leads SET assignee_id = :o, team_id = :m WHERE id = :lead"),
                {"o": owner, "m": team, "lead": result.lead_id},
            )

        # The next message reconciles the thread with the prospect.
        await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(
                    phone_number_id=PHONE_ID_A, message_id=f"wamid.{uuid7().hex}", text_body="again"
                )
            )[0]
        )

        async with admin_session() as session:
            conversation = (
                await session.execute(
                    select(Conversation).where(Conversation.id == result.conversation_id)
                )
            ).scalar_one()

        assert conversation.assignee_id == owner
        assert conversation.team_id == team

    async def test_a_closed_thread_reopens_instead_of_forking(self, workspaces: Any) -> None:
        """Archiving a thread must not split the customer's history in two.

        Matching only `active` threads meant a message arriving after somebody
        archived one started a second conversation for the same person, leaving
        half the history somewhere nobody looks.
        """
        from infrastructure.database.models.communications import Conversation

        first = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(
                    phone_number_id=PHONE_ID_A, message_id=f"wamid.{uuid7().hex}", text_body="one"
                )
            )[0]
        )

        async with admin_session() as session:
            await session.execute(
                text("UPDATE app.conversations SET status = 'archived' WHERE id = :c"),
                {"c": first.conversation_id},
            )

        second = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(
                    phone_number_id=PHONE_ID_A, message_id=f"wamid.{uuid7().hex}", text_body="two"
                )
            )[0]
        )

        assert second.conversation_id == first.conversation_id, "the thread forked"

        async with admin_session() as session:
            conversation = (
                await session.execute(
                    select(Conversation).where(Conversation.id == first.conversation_id)
                )
            ).scalar_one()
            threads = (
                await session.execute(
                    select(Conversation.id).where(
                        Conversation.tenant_id == TENANT_A, Conversation.lead_id == first.lead_id
                    )
                )
            ).all()

        # A customer who messages again is not "archived", whatever was clicked.
        assert conversation.status == "active"
        assert len(threads) == 1

    async def test_inbound_alone_never_counts_as_a_reply(self) -> None:
        """Stated at the domain level too, so it cannot drift from the ingest path."""
        assert not qualifies_as_first_response(
            channel="whatsapp", direction="inbound", outcome="received"
        )

    async def test_a_second_message_from_the_same_number_reuses_the_prospect(
        self, workspaces: Any
    ) -> None:
        first = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.a", text_body="one")
            )[0]
        )
        second = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.b", text_body="two")
            )[0]
        )

        assert first.lead_id == second.lead_id
        assert second.created_lead is False
        # And one thread, not two.
        assert first.conversation_id == second.conversation_id

    async def test_the_same_event_delivered_twice_writes_nothing_new(self, workspaces: Any) -> None:
        """Meta retries when our acknowledgement was slow, not when anything changed."""
        event = adapter().parse_webhook(
            inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.dup", text_body="hi")
        )[0]

        first = await ingest_inbound_message(event)
        again = await ingest_inbound_message(event)

        assert first.accepted
        assert not again.accepted
        assert again.reason == "duplicate"

        async with admin_session() as session:
            count = len(
                (
                    await session.execute(
                        select(Message.id).where(
                            Message.tenant_id == TENANT_A, Message.external_id == "wamid.dup"
                        )
                    )
                ).all()
            )
        assert count == 1

    async def test_a_message_on_an_unclaimed_number_is_refused(self, workspaces: Any) -> None:
        event = adapter().parse_webhook(
            inbound_payload(phone_number_id="999999999999999", message_id="wamid.x", text_body="hi")
        )[0]
        result = await ingest_inbound_message(event)

        assert not result.accepted
        assert result.reason == "no_tenant_for_business_number"

    async def test_each_business_number_routes_to_its_own_workspace(self, workspaces: Any) -> None:
        """The isolation claim, exercised rather than asserted."""
        to_a = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.ta", text_body="a")
            )[0]
        )
        to_b = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_B, message_id="wamid.tb", text_body="b")
            )[0]
        )

        assert to_a.tenant_id == TENANT_A
        assert to_b.tenant_id == TENANT_B
        assert to_a.lead_id != to_b.lead_id

        async with admin_session() as session:
            lead_b = (
                await session.execute(select(Lead).where(Lead.id == to_b.lead_id))
            ).scalar_one()
        # The same customer number, in two workspaces, as two separate records.
        assert lead_b.tenant_id == TENANT_B

    async def test_resolve_tenant_refuses_an_empty_identifier(self) -> None:
        assert await resolve_tenant(None) is None
        assert await resolve_tenant("") is None


class TestStatusReconciliation:
    async def test_status_moves_forward_and_never_backwards(self, workspaces: Any) -> None:
        ingested = await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.s", text_body="hi")
            )[0]
        )
        assert ingested.accepted

        # Pretend this id is one of ours awaiting receipts.
        events = adapter().parse_webhook(
            status_payload(phone_number_id=PHONE_ID_A, message_id="wamid.s", status="read")
        )
        assert (await ingest_status_update(events[0])).accepted

        late = adapter().parse_webhook(
            status_payload(phone_number_id=PHONE_ID_A, message_id="wamid.s", status="sent")
        )
        await ingest_status_update(late[0])

        async with admin_session() as session:
            message = (
                await session.execute(
                    select(Message).where(
                        Message.tenant_id == TENANT_A, Message.external_id == "wamid.s"
                    )
                )
            ).scalar_one()
        # A reordered "sent" arriving after "read" must not walk it back.
        assert message.status == "read"

    async def test_every_state_of_one_message_is_recorded_not_just_the_first(
        self, workspaces: Any
    ) -> None:
        """The live-test defect, pinned.

        One outbound message emits `sent`, then `delivered`, then `read` - same
        provider id, same event kind. The webhook de-duplicator keyed on
        (id, kind) alone, so the first was kept and the other two were dropped as
        duplicates. A message that genuinely reached somebody's phone sat in
        Sangam forever saying only "sent".
        """
        from application.communications.inbound import enqueue_whatsapp_events

        # Run-unique: this path de-duplicates through Redis, whose keys outlive
        # the database cleanup between runs. A fixed id would make the second run
        # of this file fail for a reason that has nothing to do with the claim.
        wamid = f"wamid.walk.{uuid7().hex}"

        await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id=wamid, text_body="hi")
            )[0]
        )

        for state in ("sent", "delivered", "read"):
            events = adapter().parse_webhook(
                status_payload(phone_number_id=PHONE_ID_A, message_id=wamid, status=state)
            )
            accepted = await enqueue_whatsapp_events(events)
            assert accepted == 1, f"{state} was swallowed as a duplicate"

        async with admin_session() as session:
            message = (
                await session.execute(
                    select(Message).where(
                        Message.tenant_id == TENANT_A, Message.external_id == wamid
                    )
                )
            ).scalar_one()

        assert message.status == "read"
        assert message.delivered_at is not None
        assert message.read_at is not None

    async def test_the_same_state_twice_is_still_a_duplicate(self, workspaces: Any) -> None:
        """Separating the states must not switch de-duplication off."""
        from application.communications.inbound import enqueue_whatsapp_events

        wamid = f"wamid.dd.{uuid7().hex}"
        await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id=wamid, text_body="hi")
            )[0]
        )
        events = adapter().parse_webhook(
            status_payload(phone_number_id=PHONE_ID_A, message_id=wamid, status="delivered")
        )

        assert await enqueue_whatsapp_events(events) == 1
        assert await enqueue_whatsapp_events(events) == 0

    async def test_a_status_for_an_unknown_message_is_refused(self, workspaces: Any) -> None:
        events = adapter().parse_webhook(
            status_payload(phone_number_id=PHONE_ID_A, message_id="wamid.nope", status="delivered")
        )
        result = await ingest_status_update(events[0])
        assert not result.accepted
        assert result.reason == "unknown_message"

    async def test_a_failure_is_recorded_as_a_failure(self, workspaces: Any) -> None:
        await ingest_inbound_message(
            adapter().parse_webhook(
                inbound_payload(phone_number_id=PHONE_ID_A, message_id="wamid.f", text_body="hi")
            )[0]
        )
        events = adapter().parse_webhook(
            status_payload(phone_number_id=PHONE_ID_A, message_id="wamid.f", status="failed")
        )
        assert (await ingest_status_update(events[0])).accepted

        async with admin_session() as session:
            message = (
                await session.execute(
                    select(Message).where(
                        Message.tenant_id == TENANT_A, Message.external_id == "wamid.f"
                    )
                )
            ).scalar_one()
        assert message.status == "failed"


class TestOutboundNeverFabricatesSuccess:
    async def test_an_unconfigured_provider_reports_queued_not_sent(self) -> None:
        from application.ports import OutboundMessage

        off = WhatsAppAdapter(
            phone_number_id=None, access_token=None, app_secret=None, enabled=False
        )
        result = await off.send(
            OutboundMessage(tenant_id=TENANT_A, to=CUSTOMER, channel="whatsapp", body="hello")
        )

        assert result.ok is False
        assert result.queued is True
        assert result.error_code == "PROVIDER_NOT_CONFIGURED"
        assert result.external_id is None

    async def test_a_rejected_send_is_not_a_reply(self) -> None:
        """The whole reason the reply path asks the domain rather than assuming."""
        assert not qualifies_as_first_response(
            channel="whatsapp", direction="outbound", outcome="failed"
        )
        assert qualifies_as_first_response(channel="whatsapp", direction="outbound", outcome="sent")

    async def test_a_provider_error_is_reported_as_an_error(self) -> None:
        from application.ports import OutboundMessage

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={"error": {"code": 131047, "message": "Re-engagement message"}},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await adapter(client=client).send(
            OutboundMessage(tenant_id=TENANT_A, to=CUSTOMER, channel="whatsapp", body="hello")
        )
        await client.aclose()

        assert result.ok is False
        assert result.external_id is None
        assert result.error_code == "131047"

    async def test_a_genuine_send_carries_the_provider_message_id(self) -> None:
        from application.ports import OutboundMessage

        async def handler(request: httpx.Request) -> httpx.Response:
            assert "Bearer" in request.headers["authorization"]
            return httpx.Response(200, json={"messages": [{"id": "wamid.out"}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        result = await adapter(client=client).send(
            OutboundMessage(tenant_id=TENANT_A, to=CUSTOMER, channel="whatsapp", body="hello")
        )
        await client.aclose()

        assert result.ok is True
        assert result.external_id == "wamid.out"


class TestTheseTestsIgnoreTheRealEnvironment:
    """Results must not depend on whether a real `.env.local` happens to exist.

    Every adapter in this file is constructed with explicit values, so the live
    Meta credentials on the founder's machine cannot make a "configured" case
    pass for the wrong reason - or an "unconfigured" one fail.
    """

    def test_the_configured_adapter_uses_injected_credentials(self) -> None:
        assert adapter().is_configured()

    def test_the_unconfigured_adapter_is_unconfigured_whatever_the_environment(self) -> None:
        blank = WhatsAppAdapter(
            phone_number_id=None, access_token=None, app_secret=None, enabled=True
        )
        assert not blank.is_configured()
        assert set(blank.activation_status()["missing_configuration"]) == {
            "WHATSAPP_PHONE_NUMBER_ID",
            "WHATSAPP_ACCESS_TOKEN",
            "WHATSAPP_APP_SECRET",
        }


class TestSecretsAreNotLeaked:
    def test_the_activation_report_names_what_is_missing_not_what_is_set(self) -> None:
        report = adapter().activation_status()
        serialised = json.dumps(report)
        assert "test-token" not in serialised
        assert APP_SECRET not in serialised
        assert VERIFY_TOKEN not in serialised

    def test_settings_do_not_repr_credentials(self) -> None:
        """`repr=False` on the secret fields, so a settings dump cannot print them."""
        from shared.settings import Settings

        for field in (
            "whatsapp_access_token",
            "whatsapp_app_secret",
            "whatsapp_verify_token",
            "whatsapp_phone_number_id",
        ):
            assert Settings.model_fields[field].repr is False, field
