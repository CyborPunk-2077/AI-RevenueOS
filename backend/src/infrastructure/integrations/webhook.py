"""Signed outbound webhook transport with SSRF and retry classification."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import socket
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from opentelemetry.trace import SpanKind

from infrastructure.observability.tracing import set_attributes, start_span

Resolver = Callable[[str, int], Awaitable[list[str]]]


@dataclass(frozen=True, slots=True)
class WebhookResult:
    delivered: bool
    terminal: bool
    status_code: int | None = None
    response_excerpt: str = ""
    error: str | None = None


async def _resolve(host: str, port: int) -> list[str]:
    loop = asyncio.get_running_loop()
    rows = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(row[4][0]) for row in rows})


async def validate_destination(url: str, *, resolver: Resolver = _resolve) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("outbound webhook URLs must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("outbound webhook URL contains forbidden components")
    port = parsed.port or 443
    if port != 443:
        raise ValueError("outbound webhook URLs must use TCP port 443")
    addresses = await resolver(parsed.hostname, port)
    if not addresses:
        raise ValueError("outbound webhook hostname did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise ValueError("outbound webhook hostname resolves to a non-public address")


def signed_headers(
    *, secret: str, body: bytes, timestamp: int, idempotency_key: str
) -> dict[str, str]:
    signature = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "User-Agent": "AI-RevenueOS-Webhook/1.0",
        "X-AIRevenueOS-Timestamp": str(timestamp),
        "X-AIRevenueOS-Signature": f"t={timestamp},v1={signature}",
        "X-AIRevenueOS-Idempotency-Key": idempotency_key,
    }


async def send_webhook(
    *,
    url: str,
    payload: dict[str, Any],
    secret: str,
    idempotency_key: str,
    client: httpx.AsyncClient | None = None,
    resolver: Resolver = _resolve,
) -> WebhookResult:
    await validate_destination(url, resolver=resolver)
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = int(time.time())
    headers = signed_headers(
        secret=secret,
        body=body,
        timestamp=timestamp,
        idempotency_key=idempotency_key,
    )
    owned_client = client is None
    http = client or httpx.AsyncClient(timeout=15.0, follow_redirects=False, trust_env=False)
    # The span records the outcome, never the destination URL: a tenant's webhook
    # endpoint frequently embeds a token in its path or query string.
    try:
        with start_span(
            "webhook send",
            kind=SpanKind.CLIENT,
            attributes={"provider.name": "custom_webhook", "provider.operation": "send"},
        ):
            try:
                response = await http.post(url, content=body, headers=headers)
            except httpx.HTTPError as exc:
                set_attributes({"provider.outcome": "transport_error"})
                return WebhookResult(False, False, error=type(exc).__name__)
            set_attributes(
                {
                    "provider.status_code": response.status_code,
                    "provider.outcome": "sent",
                }
            )
    finally:
        if owned_client:
            await http.aclose()
    excerpt = response.text[:1000]
    if 200 <= response.status_code < 300:
        return WebhookResult(True, False, response.status_code, excerpt)
    terminal = 400 <= response.status_code < 500 and response.status_code != 429
    return WebhookResult(
        False,
        terminal,
        response.status_code,
        excerpt,
        f"HTTP_{response.status_code}",
    )
