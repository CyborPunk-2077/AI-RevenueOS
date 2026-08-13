"""WhatsApp Cloud API adapter.

EXTERNAL GATE: BSP/Cloud API mode, credential ownership, template approval and an
operational owner are unresolved. The adapter, signature verification, retry,
reconciliation and tests are complete; `FEATURE_WHATSAPP_ENABLED` defaults to false
and `is_configured()` returns false without credentials. Nothing is fabricated.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import httpx

from application.ports import MessagingPort, OutboundMessage, ProviderResult
from infrastructure.integrations.circuit import CircuitOpen, registry
from infrastructure.logging.setup import get_logger

logger = get_logger("integrations.whatsapp")

GRAPH_VERSION = "v21.0"
REPLAY_WINDOW_SECONDS = 300
ACTIVATION_PREREQUISITE = (
    "Meta Business verification, WhatsApp Business Account, a BSP or direct Cloud API "
    "credential owner, an approved message template set and a named operational owner."
)

# Provider status -> internal message status.
STATUS_MAP = {
    "sent": "sent",
    "delivered": "delivered",
    "read": "read",
    "failed": "failed",
    "deleted": "failed",
    "warning": "sent",
}


class WhatsAppAdapter(MessagingPort):
    channel = "whatsapp"
    provider = "whatsapp_cloud"

    def __init__(
        self,
        *,
        phone_number_id: str | None,
        access_token: str | None,
        app_secret: str | None,
        verify_token: str | None = None,
        enabled: bool = False,
        client: httpx.AsyncClient | None = None,
        base_url: str = "https://graph.facebook.com",
    ) -> None:
        self._phone_number_id = phone_number_id
        self._access_token = access_token
        self._app_secret = app_secret
        self._verify_token = verify_token
        self._enabled = enabled
        self._client = client
        self._base_url = base_url.rstrip("/")

    # -- configuration -----------------------------------------------------
    def is_configured(self) -> bool:
        """Never claim configuration we do not have."""
        return bool(
            self._enabled and self._phone_number_id and self._access_token and self._app_secret
        )

    def activation_status(self) -> dict[str, Any]:
        missing = [
            name
            for name, value in (
                ("WHATSAPP_PHONE_NUMBER_ID", self._phone_number_id),
                ("WHATSAPP_ACCESS_TOKEN", self._access_token),
                ("WHATSAPP_APP_SECRET", self._app_secret),
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

    # -- outbound ----------------------------------------------------------
    def build_payload(self, message: OutboundMessage) -> dict[str, Any]:
        base: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": message.to.lstrip("+"),
        }
        if message.template_name:
            base["type"] = "template"
            base["template"] = {
                "name": message.template_name,
                "language": {"code": message.template_variables.get("_language", "en")},
                "components": [
                    {
                        "type": "body",
                        "parameters": [
                            {"type": "text", "text": str(v)}
                            for k, v in message.template_variables.items()
                            if not k.startswith("_")
                        ],
                    }
                ],
            }
        else:
            base["type"] = "text"
            base["text"] = {"preview_url": False, "body": message.body or ""}
        return base

    async def send(self, message: OutboundMessage) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="send",
                queued=True,
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message="WhatsApp is not activated; the message was queued.",
                raw={"activation_prerequisite": ACTIVATION_PREREQUISITE},
            )
        breaker = registry.get(self.provider)
        try:
            breaker.require()
        except CircuitOpen as exc:
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="send",
                queued=True,
                degraded=True,
                error_code="PROVIDER_UNAVAILABLE",
                error_message=str(exc),
            )

        started = time.perf_counter()
        client = self._client or httpx.AsyncClient(timeout=15.0)
        try:
            response = await client.post(
                f"{self._base_url}/{GRAPH_VERSION}/{self._phone_number_id}/messages",
                json=self.build_payload(message),
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/json",
                    # Provider-side dedupe alongside our own idempotency record.
                    "X-Idempotency-Key": message.idempotency_key or "",
                },
            )
            latency = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                breaker.record_failure()
                body = _safe_json(response)
                return ProviderResult(
                    ok=False,
                    provider=self.provider,
                    operation="send",
                    queued=response.status_code >= 500,
                    latency_ms=latency,
                    error_code=str(body.get("error", {}).get("code", response.status_code)),
                    error_message=str(body.get("error", {}).get("message", "send failed")),
                    raw=body,
                )
            breaker.record_success()
            body = _safe_json(response)
            external_id = (body.get("messages") or [{}])[0].get("id")
            return ProviderResult(
                ok=True,
                provider=self.provider,
                operation="send",
                external_id=external_id,
                latency_ms=latency,
                raw=body,
            )
        except httpx.HTTPError as exc:
            breaker.record_failure()
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="send",
                queued=True,
                degraded=True,
                error_code="PROVIDER_UNAVAILABLE",
                error_message=type(exc).__name__,
            )
        finally:
            if self._client is None:
                await client.aclose()

    async def health(self) -> ProviderResult:
        if not self.is_configured():
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="health",
                error_code="PROVIDER_NOT_CONFIGURED",
                error_message="WhatsApp credentials are not present.",
                raw=self.activation_status(),
            )
        client = self._client or httpx.AsyncClient(timeout=10.0)
        try:
            response = await client.get(
                f"{self._base_url}/{GRAPH_VERSION}/{self._phone_number_id}",
                headers={"Authorization": f"Bearer {self._access_token}"},
            )
            return ProviderResult(
                ok=response.status_code < 400,
                provider=self.provider,
                operation="health",
                raw=_safe_json(response),
            )
        except httpx.HTTPError as exc:
            return ProviderResult(
                ok=False,
                provider=self.provider,
                operation="health",
                error_code="PROVIDER_UNAVAILABLE",
                error_message=type(exc).__name__,
            )
        finally:
            if self._client is None:
                await client.aclose()

    # -- inbound -----------------------------------------------------------
    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> bool:
        """HMAC-SHA256 over the raw body, compared in constant time."""
        if not self._app_secret:
            return False
        header = headers.get("x-hub-signature-256") or headers.get("X-Hub-Signature-256") or ""
        if not header.startswith("sha256="):
            return False
        expected = hmac.new(self._app_secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, header.removeprefix("sha256="))

    def verify_challenge(self, *, mode: str, token: str, challenge: str) -> str | None:
        if (
            mode == "subscribe"
            and self._verify_token
            and hmac.compare_digest(token, self._verify_token)
        ):
            return challenge
        return None

    @staticmethod
    def is_replay(timestamp: int | str, *, now: float | None = None) -> bool:
        moment = now if now is not None else time.time()
        try:
            return abs(moment - int(timestamp)) > REPLAY_WINDOW_SECONDS
        except (TypeError, ValueError):
            return True

    def parse_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """Normalise inbound messages and delivery status updates into flat events."""
        events: list[dict[str, Any]] = []
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                # Which of *our* numbers this arrived on. Meta sends one webhook
                # per app, so without this a second business on the same app would
                # have its customers filed under the first one's workspace. It is
                # the only thing in the payload that can route a tenant.
                metadata = value.get("metadata") or {}
                business_number_id = metadata.get("phone_number_id")
                business_number = metadata.get("display_phone_number")
                for message in value.get("messages", []):
                    events.append(
                        {
                            "kind": "inbound_message",
                            "business_phone_number_id": business_number_id,
                            "business_phone_number": business_number,
                            "external_id": message.get("id"),
                            "from": "+" + str(message.get("from", "")).lstrip("+"),
                            "profile_name": _profile_name(value, message.get("from")),
                            "timestamp": message.get("timestamp"),
                            "content_type": _content_type(message),
                            "content": _content_text(message),
                            "media": _media(message),
                            "context_id": (message.get("context") or {}).get("id"),
                        }
                    )
                for status in value.get("statuses", []):
                    events.append(
                        {
                            "kind": "status_update",
                            "business_phone_number_id": business_number_id,
                            "external_id": status.get("id"),
                            "status": STATUS_MAP.get(status.get("status", ""), "pending"),
                            "timestamp": status.get("timestamp"),
                            "recipient": "+" + str(status.get("recipient_id", "")).lstrip("+"),
                            "error": (status.get("errors") or [{}])[0]
                            if status.get("errors")
                            else None,
                        }
                    )
        return events

    @staticmethod
    def is_opt_out(text: str | None) -> bool:
        """Opt-out keywords stop queued and running customer contact immediately."""
        if not text:
            return False
        return text.strip().lower() in {
            "stop",
            "unsubscribe",
            "opt out",
            "optout",
            "cancel",
            "band karo",
            "band karein",
        }


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        data = response.json()
        return data if isinstance(data, dict) else {"data": data}
    except ValueError:
        return {"raw": response.text[:1000]}


def _profile_name(value: dict[str, Any], wa_id: str | None) -> str | None:
    """The name WhatsApp shows for the sender, when they have one set.

    Used only as a starting label for a brand-new prospect. It is whatever the
    customer typed into their own phone, so it is never treated as identifying and
    never overwrites a name somebody in the business has entered.
    """
    if not wa_id:
        return None
    for contact in value.get("contacts", []) or []:
        if str(contact.get("wa_id", "")).lstrip("+") == str(wa_id).lstrip("+"):
            name: str | None = (contact.get("profile") or {}).get("name")
            return name
    return None


def _content_type(message: dict[str, Any]) -> str:
    kind = message.get("type", "text")
    return (
        kind
        if kind in ("text", "image", "video", "audio", "document", "location", "interactive")
        else "text"
    )


def _content_text(message: dict[str, Any]) -> str | None:
    if "text" in message:
        body: str | None = message["text"].get("body")
        return body
    if "button" in message:
        label: str | None = message["button"].get("text")
        return label
    if "interactive" in message:
        interactive = message["interactive"]
        for key in ("button_reply", "list_reply"):
            if key in interactive:
                title: str | None = interactive[key].get("title")
                return title
    caption: str | None = (message.get(message.get("type", ""), {}) or {}).get("caption")
    return caption


def _media(message: dict[str, Any]) -> dict[str, Any]:
    kind = message.get("type")
    if kind in ("image", "video", "audio", "document") and isinstance(message.get(kind), dict):
        node = message[kind]
        return {
            "media_id": node.get("id"),
            "mime_type": node.get("mime_type"),
            "sha256": node.get("sha256"),
            "filename": node.get("filename"),
        }
    return {}
