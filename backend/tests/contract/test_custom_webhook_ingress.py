"""Regression suite for the tenant custom webhook ingress.

The original implementation checked only that a signature header was *present*
and never verified it, so any caller could inject workflow trigger payloads for
any tenant. These tests fail against that version.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from uuid import uuid4

import pytest

from application.workflows.ingress import (
    REPLAY_WINDOW_SECONDS,
    accept_custom_webhook,
    verify_signature,
)
from shared.exceptions import Forbidden

pytestmark = pytest.mark.contract

SECRET = "webhook-signing-secret"
WEBHOOK_ID = str(uuid4())
TENANT_ID = uuid4()


def sign(body: bytes, secret: str = SECRET, *, at: int | None = None) -> str:
    timestamp = at if at is not None else int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_config(webhook_id: str) -> tuple[Any, str] | None:
        return (TENANT_ID, SECRET) if webhook_id == WEBHOOK_ID else None

    monkeypatch.setattr("application.workflows.ingress.load_webhook_config", fake_config)


class TestSignatureVerification:
    def test_valid_signature_verifies(self) -> None:
        body = b'{"event":"ping"}'
        assert verify_signature(secret=SECRET, body=body, header=sign(body)) is True

    def test_wrong_secret_rejected(self) -> None:
        body = b'{"event":"ping"}'
        header = sign(body, secret="attacker-secret")
        assert verify_signature(secret=SECRET, body=body, header=header) is False

    def test_tampered_body_rejected(self) -> None:
        header = sign(b'{"amount":1}')
        assert verify_signature(secret=SECRET, body=b'{"amount":999}', header=header) is False

    def test_expired_timestamp_rejected(self) -> None:
        body = b"{}"
        stale = int(time.time()) - REPLAY_WINDOW_SECONDS - 1
        assert verify_signature(secret=SECRET, body=body, header=sign(body, at=stale)) is False

    def test_future_timestamp_outside_the_window_rejected(self) -> None:
        body = b"{}"
        ahead = int(time.time()) + REPLAY_WINDOW_SECONDS + 60
        assert verify_signature(secret=SECRET, body=body, header=sign(body, at=ahead)) is False

    @pytest.mark.parametrize("header", ["", "garbage", "t=abc,v1=xyz", "v1=onlysignature"])
    def test_malformed_headers_rejected(self, header: str) -> None:
        assert verify_signature(secret=SECRET, body=b"{}", header=header) is False


class TestIngressFailsClosed:
    async def test_missing_signature_header_is_refused(self, configured: None) -> None:
        with pytest.raises(Forbidden):
            await accept_custom_webhook(webhook_id=WEBHOOK_ID, body=b"{}", headers={})

    async def test_present_but_invalid_signature_is_refused(self, configured: None) -> None:
        """The original implementation accepted this."""
        with pytest.raises(Forbidden):
            await accept_custom_webhook(
                webhook_id=WEBHOOK_ID,
                body=b'{"trigger":"payment.succeeded"}',
                headers={"x-airev-signature": "t=1,v1=deadbeef"},
            )

    async def test_signature_from_another_secret_is_refused(self, configured: None) -> None:
        body = b'{"trigger":"lead.created"}'
        with pytest.raises(Forbidden):
            await accept_custom_webhook(
                webhook_id=WEBHOOK_ID,
                body=body,
                headers={"x-airev-signature": sign(body, secret="not-the-secret")},
            )

    async def test_unknown_webhook_id_is_refused_indistinguishably(self, configured: None) -> None:
        body = b"{}"
        with pytest.raises(Forbidden) as unknown:
            await accept_custom_webhook(
                webhook_id=str(uuid4()),
                body=body,
                headers={"x-airev-signature": sign(body)},
            )
        with pytest.raises(Forbidden) as bad_signature:
            await accept_custom_webhook(
                webhook_id=WEBHOOK_ID,
                body=body,
                headers={"x-airev-signature": "t=1,v1=deadbeef"},
            )
        # Identical message: the endpoint cannot be used to enumerate webhook ids.
        assert str(unknown.value) == str(bad_signature.value)

    async def test_unconfigured_master_key_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def no_config(webhook_id: str) -> None:
            return None

        monkeypatch.setattr("application.workflows.ingress.load_webhook_config", no_config)
        body = b"{}"
        with pytest.raises(Forbidden):
            await accept_custom_webhook(
                webhook_id=WEBHOOK_ID,
                body=body,
                headers={"x-airev-signature": sign(body)},
            )


class TestIngressHappyPath:
    async def test_valid_request_is_accepted_once_then_deduplicated(self, configured: None) -> None:
        body = b'{"trigger":"lead.created","id":"abc"}'
        headers = {"x-airev-signature": sign(body), "x-idempotency-key": "evt-1"}

        first = await accept_custom_webhook(webhook_id=WEBHOOK_ID, body=body, headers=headers)
        second = await accept_custom_webhook(webhook_id=WEBHOOK_ID, body=body, headers=headers)

        assert first["accepted"] is True and first["duplicate"] is False
        assert second["accepted"] is True and second["duplicate"] is True
        assert first["event_id"] == "evt-1"

    async def test_idempotency_is_scoped_per_webhook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        other_id = str(uuid4())

        async def fake_config(webhook_id: str) -> tuple[Any, str]:
            return (TENANT_ID, SECRET)

        monkeypatch.setattr("application.workflows.ingress.load_webhook_config", fake_config)
        body = b'{"n":1}'
        headers = {"x-airev-signature": sign(body), "x-idempotency-key": "shared-key"}

        first = await accept_custom_webhook(webhook_id=WEBHOOK_ID, body=body, headers=headers)
        other = await accept_custom_webhook(webhook_id=other_id, body=body, headers=headers)

        assert first["duplicate"] is False
        # A different webhook must not be silenced by another webhook's event id.
        assert other["duplicate"] is False
