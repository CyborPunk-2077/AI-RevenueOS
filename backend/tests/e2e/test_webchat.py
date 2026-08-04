"""Webchat against real PostgreSQL: origin enforcement, session scope, isolation."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select

from application.communications import webchat
from infrastructure.database.models.communications import WebchatSession
from infrastructure.database.session import tenant_session
from shared.exceptions import Forbidden, NotFound, ValidationError
from shared.utils.timeutil import utcnow

pytestmark = pytest.mark.postgres

SITE = "https://sharma-textiles.in"


async def _widget(tenant_id: Any, *, origins: list[str] | None = None) -> dict[str, Any]:
    return await webchat.configure_widget(
        tenant_id=tenant_id,
        actor_id=uuid4(),
        allowed_origins=origins if origins is not None else [SITE],
        greeting="How can we help?",
        consent_copy="We store this chat to answer your question.",
        is_active=True,
    )


class TestConfiguration:
    async def test_a_widget_cannot_be_activated_without_an_origin(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """Activating with no allow-list would let any site that copies the key embed it."""
        tenant_a, _ = seeded_tenants
        with pytest.raises(ValidationError):
            await webchat.configure_widget(
                tenant_id=tenant_a, actor_id=uuid4(), allowed_origins=[], is_active=True
            )

    async def test_rotating_the_key_invalidates_the_old_one(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        first = await _widget(tenant_a)
        rotated = await webchat.rotate_public_key(tenant_id=tenant_a, actor_id=uuid4())

        assert rotated["public_key"] != first["public_key"]
        with pytest.raises(NotFound):
            await webchat.widget_config(public_key=first["public_key"], origin=SITE)


class TestOriginEnforcement:
    async def test_an_allowed_origin_gets_the_config(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)

        config = await webchat.widget_config(public_key=widget["public_key"], origin=SITE)
        assert config["greeting"] == "How can we help?"

    async def test_an_unlisted_origin_is_refused(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)

        with pytest.raises(Forbidden):
            await webchat.widget_config(
                public_key=widget["public_key"], origin="https://someone-else.example"
            )

    async def test_an_inactive_widget_answers_like_a_missing_one(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)
        await webchat.configure_widget(tenant_id=tenant_a, actor_id=uuid4(), is_active=False)

        with pytest.raises(NotFound):
            await webchat.widget_config(public_key=widget["public_key"], origin=SITE)


class TestVisitorSessions:
    async def test_a_session_opens_a_conversation_and_stores_only_a_hash(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)

        opened = await webchat.start_session(
            public_key=widget["public_key"], origin=SITE, consent_granted=True, ip="203.0.113.7"
        )

        async with tenant_session(tenant_a) as session:
            row = (
                await session.execute(
                    select(WebchatSession).where(WebchatSession.id == opened.session_id)
                )
            ).scalar_one()
        assert row.session_token_hash != opened.token
        assert row.consent_granted is True
        assert row.ip_hash is not None and "203.0.113.7" not in row.ip_hash

    async def test_a_visitor_can_send_and_read_their_own_transcript(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)
        opened = await webchat.start_session(public_key=widget["public_key"], origin=SITE)

        await webchat.post_visitor_message(
            token=opened.token, body="Do you ship to Pune?", origin=SITE
        )
        transcript = await webchat.visitor_transcript(token=opened.token)

        assert [m["content"] for m in transcript["messages"]] == ["Do you ship to Pune?"]
        assert transcript["messages"][0]["author"] == "you"

    async def test_a_token_cannot_be_used_from_a_different_site(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """A stolen token on another page is either a leak or an unauthorised embed."""
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a, origins=[SITE, "https://other.example"])
        opened = await webchat.start_session(public_key=widget["public_key"], origin=SITE)

        with pytest.raises(Forbidden):
            await webchat.post_visitor_message(
                token=opened.token, body="hello", origin="https://other.example"
            )

    async def test_an_empty_message_is_refused(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)
        opened = await webchat.start_session(public_key=widget["public_key"], origin=SITE)

        with pytest.raises(ValidationError):
            await webchat.post_visitor_message(token=opened.token, body="   ", origin=SITE)

    async def test_an_expired_session_stops_accepting_messages(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)
        opened = await webchat.start_session(public_key=widget["public_key"], origin=SITE)

        async with tenant_session(tenant_a) as session:
            row = (
                await session.execute(
                    select(WebchatSession).where(WebchatSession.id == opened.session_id)
                )
            ).scalar_one()
            row.expires_at = utcnow() - timedelta(minutes=1)

        with pytest.raises(NotFound):
            await webchat.post_visitor_message(token=opened.token, body="still there?", origin=SITE)

    async def test_ending_a_session_closes_it(self, wired_engine: Any, seeded_tenants: Any) -> None:
        tenant_a, _ = seeded_tenants
        widget = await _widget(tenant_a)
        opened = await webchat.start_session(public_key=widget["public_key"], origin=SITE)

        await webchat.end_session(token=opened.token)

        with pytest.raises(NotFound):
            await webchat.post_visitor_message(token=opened.token, body="hello again", origin=SITE)

    async def test_a_forged_tenant_prefix_matches_nothing(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        """The tenant id in the token is routing, not authority."""
        tenant_a, tenant_b = seeded_tenants
        widget = await _widget(tenant_a)
        opened = await webchat.start_session(public_key=widget["public_key"], origin=SITE)
        _, _, secret = opened.token.partition(".")

        with pytest.raises(NotFound):
            await webchat.visitor_transcript(token=f"{tenant_b}.{secret}")


class TestTenantIsolation:
    async def test_one_tenants_widget_is_invisible_to_another(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, tenant_b = seeded_tenants
        await _widget(tenant_a)

        assert await webchat.get_widget(tenant_id=tenant_b) is None

    async def test_sessions_are_counted_per_tenant(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, tenant_b = seeded_tenants
        widget = await _widget(tenant_a)
        await webchat.start_session(public_key=widget["public_key"], origin=SITE)

        assert await webchat.active_session_count(tenant_id=tenant_a) >= 1
        assert await webchat.active_session_count(tenant_id=tenant_b) == 0
