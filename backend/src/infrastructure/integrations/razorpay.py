"""Razorpay hosted-collection adapter.

EXTERNAL GATE: Razorpay commercial model, collections-versus-SaaS-billing split and
refund/reconciliation policy are unresolved. Amount authority is always server side;
no card data is ever accepted, stored or logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any
from uuid import UUID

import httpx

from application.ports import PaymentPort, ProviderResult
from domain.payments.state_machine import sanitize_provider_payload
from infrastructure.integrations.circuit import CircuitOpen, registry
from infrastructure.logging.setup import get_logger

logger = get_logger("integrations.razorpay")

BASE_URL = "https://api.razorpay.com/v1"
ACTIVATION_PREREQUISITE = (
    "Razorpay merchant account, agreed commercial model, a decision on collections "
    "versus SaaS billing, a documented refund/reconciliation policy and webhook secret."
)

# Razorpay event -> internal payment status.
EVENT_STATUS = {
    "payment.authorized": "attempted",
    "payment.captured": "captured",
    "payment.failed": "failed",
    "refund.created": "refunded",
    "refund.processed": "refunded",
    "order.paid": "captured",
}


class RazorpayAdapter(PaymentPort):
    provider = "razorpay"

    def __init__(
        self,
        *,
        key_id: str | None,
        key_secret: str | None,
        webhook_secret: str | None,
        enabled: bool = False,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._key_id = key_id
        self._key_secret = key_secret
        self._webhook_secret = webhook_secret
        self._enabled = enabled
        self._client = client
        self._base_url = base_url.rstrip("/")

    def is_configured(self) -> bool:
        return bool(self._enabled and self._key_id and self._key_secret and self._webhook_secret)

    def activation_status(self) -> dict[str, Any]:
        missing = [
            name
            for name, value in (
                ("RAZORPAY_KEY_ID", self._key_id),
                ("RAZORPAY_KEY_SECRET", self._key_secret),
                ("RAZORPAY_WEBHOOK_SECRET", self._webhook_secret),
            )
            if not value
        ]
        return {
            "provider": self.provider,
            "enabled_flag": self._enabled,
            "configured": self.is_configured(),
            "missing_configuration": missing,
            "activation_prerequisite": ACTIVATION_PREREQUISITE,
        }

    def _auth_header(self) -> str:
        raw = f"{self._key_id}:{self._key_secret}".encode()
        return "Basic " + base64.b64encode(raw).decode()

    async def create_order(
        self,
        *,
        tenant_id: UUID,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any],
        idempotency_key: str,
    ) -> ProviderResult:
        if currency != "INR":
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="create_order",
                error_code="VALIDATION_ERROR",
                error_message="only INR is supported",
            )
        if amount_minor <= 0:
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="create_order",
                error_code="VALIDATION_ERROR",
                error_message="amount must be positive",
            )
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="create_order",
                queued=True,
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message=(
                    "Payments are not activated; the order was queued for reconciliation."
                ),
                raw={"activation_prerequisite": ACTIVATION_PREREQUISITE},
            )
        breaker = registry.get(self.provider)
        try:
            breaker.require()
        except CircuitOpen as exc:
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="create_order",
                queued=True,
                degraded=True,
                error_code="PROVIDER_UNAVAILABLE",
                error_message=str(exc),
            )

        started = time.perf_counter()
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.post(
                f"{self._base_url}/orders",
                json={
                    "amount": amount_minor,  # server-derived; never client supplied
                    "currency": currency,
                    "receipt": receipt[:40],
                    "notes": {"tenant_id": str(tenant_id), **{k: str(v) for k, v in notes.items()}},
                    "payment_capture": 1,
                },
                headers={
                    "Authorization": self._auth_header(),
                    "Content-Type": "application/json",
                    "X-Razorpay-Idempotency-Key": idempotency_key,
                },
            )
            latency = int((time.perf_counter() - started) * 1000)
            body = sanitize_provider_payload(_safe_json(response))
            if response.status_code >= 400:
                breaker.record_failure()
                return ProviderResult(
                    ok=False,
                    provider=self.provider,
                    operation="create_order",
                    queued=response.status_code >= 500,
                    latency_ms=latency,
                    raw=body,
                    error_code=str(body.get("error", {}).get("code", response.status_code)),
                    error_message=str(body.get("error", {}).get("description", "order failed")),
                )
            breaker.record_success()
            return ProviderResult(
                ok=True,
                provider=self.provider,
                operation="create_order",
                external_id=body.get("id"),
                latency_ms=latency,
                raw=body,
            )
        except httpx.HTTPError as exc:
            breaker.record_failure()
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="create_order",
                queued=True,
                degraded=True,
                error_code="PROVIDER_UNAVAILABLE",
                error_message=type(exc).__name__,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def fetch_payment(self, external_payment_id: str) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="fetch_payment",
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message="Payments are not activated.",
            )
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.get(
                f"{self._base_url}/payments/{external_payment_id}",
                headers={"Authorization": self._auth_header()},
            )
            body = sanitize_provider_payload(_safe_json(response))
            return ProviderResult(
                ok=response.status_code < 400,
                provider=self.provider,
                operation="fetch_payment",
                external_id=body.get("id"),
                raw=body,
            )
        except httpx.HTTPError as exc:
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="fetch_payment",
                error_code="PROVIDER_UNAVAILABLE",
                error_message=type(exc).__name__,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def refund(
        self, *, external_payment_id: str, amount_minor: int, idempotency_key: str
    ) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="refund",
                queued=True,
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message="Payments are not activated.",
            )
        client = self._client or httpx.AsyncClient(timeout=20.0)
        try:
            response = await client.post(
                f"{self._base_url}/payments/{external_payment_id}/refund",
                json={"amount": amount_minor, "speed": "normal"},
                headers={
                    "Authorization": self._auth_header(),
                    "X-Razorpay-Idempotency-Key": idempotency_key,
                },
            )
            body = sanitize_provider_payload(_safe_json(response))
            return ProviderResult(
                ok=response.status_code < 400,
                provider=self.provider,
                operation="refund",
                external_id=body.get("id"),
                raw=body,
                error_message=None if response.status_code < 400 else "refund failed",
            )
        except httpx.HTTPError as exc:
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="refund",
                queued=True,
                error_code="PROVIDER_UNAVAILABLE",
                error_message=type(exc).__name__,
            )
        finally:
            if self._client is None:
                await client.aclose()

    # -- webhook verification ---------------------------------------------
    def verify_webhook_signature(self, *, body: bytes, signature: str) -> bool:
        if not self._webhook_secret or not signature:
            return False
        expected = hmac.new(self._webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def verify_payment_signature(self, *, order_id: str, payment_id: str, signature: str) -> bool:
        """Checkout handback verification, signed with the API key secret."""
        if not self._key_secret:
            return False
        expected = hmac.new(
            self._key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature or "")

    @staticmethod
    def parse_webhook(payload: dict[str, Any]) -> dict[str, Any]:
        event = payload.get("event", "")
        entity_wrapper = payload.get("payload", {})
        entity = (
            entity_wrapper.get("payment", {}).get("entity")
            or entity_wrapper.get("refund", {}).get("entity")
            or entity_wrapper.get("order", {}).get("entity")
            or {}
        )
        return {
            "event": event,
            "external_event_id": str(payload.get("id") or entity.get("id") or ""),
            "status": EVENT_STATUS.get(event),
            "external_payment_id": entity.get("id")
            if "payment" in event
            else entity.get("payment_id"),
            "external_order_id": entity.get("order_id")
            or (entity.get("id") if "order" in event else None),
            "amount_minor": entity.get("amount"),
            "currency": entity.get("currency"),
            "method": entity.get("method", "unknown"),
            "created_at": payload.get("created_at"),
            "entity": sanitize_provider_payload(entity),
        }


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}
    except ValueError:
        return {"raw": response.text[:1000]}
