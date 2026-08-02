from __future__ import annotations

import hashlib
import hmac
import json

import httpx
import pytest

from infrastructure.integrations.webhook import send_webhook, validate_destination


async def _public_resolver(_host: str, _port: int) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    (
        "http://example.com/hook",
        "https://user:pass@example.com/hook",
        "https://example.com:8443/hook",
        "https://example.com/hook#fragment",
    ),
)
async def test_destination_rejects_unsafe_url_components(url: str) -> None:
    with pytest.raises(ValueError):
        await validate_destination(url, resolver=_public_resolver)


@pytest.mark.parametrize("address", ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"))
async def test_destination_rejects_any_non_public_resolution(address: str) -> None:
    async def resolver(_host: str, _port: int) -> list[str]:
        return ["93.184.216.34", address]

    with pytest.raises(ValueError, match="non-public"):
        await validate_destination("https://example.com/hook", resolver=resolver)


async def test_transport_sends_canonical_signed_json_without_redirects() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = await request.aread()
        seen["signature"] = request.headers["X-AIRevenueOS-Signature"]
        seen["timestamp"] = request.headers["X-AIRevenueOS-Timestamp"]
        seen["idempotency_key"] = request.headers["X-AIRevenueOS-Idempotency-Key"]
        return httpx.Response(204)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_webhook(
            url="https://example.com/hook",
            payload={"z": 1, "a": "value"},
            secret="test-signing-secret",
            idempotency_key="config:event",
            client=client,
            resolver=_public_resolver,
        )

    body = json.dumps({"z": 1, "a": "value"}, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(seen["timestamp"])
    signature = hmac.new(
        b"test-signing-secret", f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    assert result.delivered is True
    assert result.status_code == 204
    assert seen["body"] == body
    assert seen["signature"] == f"t={timestamp},v1={signature}"
    assert seen["idempotency_key"] == "config:event"


@pytest.mark.parametrize(
    ("status", "terminal"),
    ((400, True), (422, True), (429, False), (500, False), (503, False)),
)
async def test_transport_classifies_provider_responses(status: int, terminal: bool) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="provider response")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await send_webhook(
            url="https://example.com/hook",
            payload={"event_type": "contact.created"},
            secret="secret",
            idempotency_key="config:event",
            client=client,
            resolver=_public_resolver,
        )

    assert result.delivered is False
    assert result.terminal is terminal
    assert result.response_excerpt == "provider response"
