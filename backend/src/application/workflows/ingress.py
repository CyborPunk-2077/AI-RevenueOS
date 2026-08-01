"""Custom inbound webhook ingress: verify, dedupe, enqueue, acknowledge within 2s."""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from uuid import UUID

from infrastructure.logging.setup import get_logger
from shared.exceptions import Forbidden

logger = get_logger("workflows.ingress")

REPLAY_WINDOW_SECONDS = 300


def verify_signature(*, secret: str, body: bytes, header: str) -> bool:
    """Header format: `t=<unix>,v1=<hmac-sha256>`."""
    parts = dict(piece.split("=", 1) for piece in header.split(",") if "=" in piece)
    timestamp, signature = parts.get("t", ""), parts.get("v1", "")
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > REPLAY_WINDOW_SECONDS:
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


async def load_webhook_config(webhook_id: str) -> tuple[UUID, str] | None:
    """Resolve a webhook id to its tenant and decrypted signing secret.

    The lookup is unscoped because the caller is anonymous and the webhook id is
    what establishes the tenant. Only an active configuration resolves, and the
    returned tenant id is what every subsequent operation is scoped by.
    """
    from sqlalchemy import select

    from infrastructure.auth.encryption import EnvelopeEncryptor
    from infrastructure.database.models.workflows import InboundWebhookConfig
    from infrastructure.database.session import unscoped_session
    from shared.settings import get_settings

    try:
        identifier = UUID(webhook_id)
    except (ValueError, AttributeError):
        return None

    async with unscoped_session() as session:
        row = (
            await session.execute(
                select(
                    InboundWebhookConfig.tenant_id,
                    InboundWebhookConfig.signing_secret_encrypted,
                ).where(
                    InboundWebhookConfig.id == identifier,
                    InboundWebhookConfig.is_active.is_(True),
                )
            )
        ).one_or_none()

    if row is None:
        return None

    master_key = get_settings().encryption_master_key
    if not master_key:
        # Without the master key the secret cannot be decrypted, so the request
        # cannot be authenticated. Fail closed rather than accept it unverified.
        return None

    try:
        secret = EnvelopeEncryptor(master_key).decrypt_str(row[1], tenant_id=str(row[0]))
    except Exception:
        return None
    return row[0], secret


async def accept_custom_webhook(
    *, webhook_id: str, body: bytes, headers: dict[str, str], correlation_id: str | None = None
) -> dict[str, Any]:
    """Verify the signature, deduplicate, then acknowledge.

    Fails closed: an unknown webhook id, a missing master key, a malformed header
    or a signature mismatch are all rejected identically, so the endpoint cannot
    be used to probe which webhook ids exist.
    """
    from application.workflows.executor import inbound_idempotency_key
    from infrastructure.caching.redis import TTL_IDEMPOTENCY, Cache, global_key

    signature = headers.get("x-airev-signature", "")
    if not signature:
        raise Forbidden("A signed request is required.")

    config = await load_webhook_config(webhook_id)
    if config is None:
        raise Forbidden("Signature verification failed.")
    tenant_id, secret = config

    if not verify_signature(secret=secret, body=body, header=signature):
        raise Forbidden("Signature verification failed.")

    event_id = headers.get("x-idempotency-key") or hashlib.sha256(body).hexdigest()
    cache = Cache()
    key = global_key(
        "inbound",
        inbound_idempotency_key(provider=f"custom:{webhook_id}", event_id=event_id),
    )
    if await cache.get_json(key) is not None:
        return {"accepted": True, "duplicate": True, "event_id": event_id}
    await cache.set_json(key, {"seen": True, "tenant_id": str(tenant_id)}, TTL_IDEMPOTENCY)
    logger.info(
        "custom_webhook_accepted",
        tenant_id=str(tenant_id),
        event_id=event_id,
        correlation_id=correlation_id,
    )
    return {"accepted": True, "duplicate": False, "event_id": event_id}
