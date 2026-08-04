"""Email adapter (SES/SendGrid).

EXTERNAL GATE: provider selection, commercial terms, regional availability and sender
domain ownership (SPF/DKIM/DMARC) are unresolved. Default provider is `none`.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from application.ports import MessagingPort, OutboundMessage, ProviderResult

ACTIVATION_PREREQUISITE = (
    "Provider decision (Amazon SES or SendGrid), commercial terms, ap-south-1 "
    "availability confirmation, verified sender domain with SPF/DKIM/DMARC records "
    "and a bounce/complaint handling owner."
)

HARD_BOUNCE_TYPES = frozenset({"Permanent", "hard", "blocked", "suppressed"})


class EmailAdapter(MessagingPort):
    channel = "email"

    def __init__(
        self,
        *,
        provider: str = "none",
        api_key: str | None = None,
        from_address: str | None = None,
        webhook_secret: str | None = None,
        enabled: bool = False,
    ) -> None:
        self.provider = provider
        self._api_key = api_key
        self._from = from_address
        self._webhook_secret = webhook_secret
        self._enabled = enabled

    def is_configured(self) -> bool:
        return bool(self._enabled and self.provider != "none" and self._api_key and self._from)

    def activation_status(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "enabled_flag": self._enabled,
            "configured": self.is_configured(),
            "decision_gate": "Email and voice provider selection",
            "activation_prerequisite": ACTIVATION_PREREQUISITE,
        }

    async def send(self, message: OutboundMessage) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="send",
                queued=True,
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message="Email is not activated; the message was queued.",
                raw={"activation_prerequisite": ACTIVATION_PREREQUISITE},
            )
        raise NotImplementedError(
            "the concrete SES/SendGrid client is implemented once the provider decision is recorded"
        )

    async def health(self) -> ProviderResult:
        return ProviderResult(
            ok=self.is_configured(),
            provider=self.provider,
            operation="health",
            error_code=None if self.is_configured() else "PROVIDER_NOT_CONFIGURED",
            raw=self.activation_status(),
        )

    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> bool:
        if not self._webhook_secret:
            return False
        signature = headers.get("x-email-signature", "")
        expected = hmac.new(self._webhook_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(self, payload: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Normalise SES and SendGrid delivery notifications into one shape."""
        events: list[dict[str, Any]] = []
        records = payload if isinstance(payload, list) else payload.get("Records", [payload])
        for record in records:
            kind = record.get("eventType") or record.get("event") or record.get("notificationType")
            bounce = record.get("bounce") or {}
            events.append(
                {
                    "kind": "status_update",
                    "external_id": (
                        record.get("sg_message_id") or record.get("mail", {}).get("messageId")
                    ),
                    "status": _status_for(str(kind or "")),
                    "recipient": record.get("email")
                    or (record.get("mail", {}).get("destination", [None])[0]),
                    "hard_bounce": str(bounce.get("bounceType", record.get("type", "")))
                    in HARD_BOUNCE_TYPES,
                    "reason": record.get("reason") or bounce.get("bounceSubType"),
                }
            )
        return events


def _status_for(kind: str) -> str:
    lowered = kind.lower()
    if "bounce" in lowered:
        return "bounced"
    if "delivery" in lowered or lowered == "delivered":
        return "delivered"
    if "open" in lowered or "click" in lowered:
        return "read"
    if "complaint" in lowered or "dropped" in lowered or "spam" in lowered:
        return "failed"
    return "sent"
