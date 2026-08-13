"""Is WhatsApp actually connected, and how far has a real test got?

Two things are deliberately kept apart here, because conflating them is the
standard way an integration page lies:

* **configured** - the credentials exist. This is typing.
* **connected**  - Meta answered a live call to the Graph API with those
                   credentials and told us about the number. This is proof.

`CONNECTED` is only ever returned after the second one. A page that goes green
when somebody pastes a token teaches its owner that green means nothing.

Nothing in here returns a secret. The access token, app secret and verify token
are never read back out; only whether each is present, and what Meta said about
the number.
"""

from __future__ import annotations

from typing import Any, Final
from uuid import UUID

from infrastructure.logging.setup import get_logger

logger = get_logger("communications.whatsapp_status")

NOT_CONFIGURED: Final = "NOT_CONFIGURED"
CONNECTED: Final = "CONNECTED"
ERROR: Final = "ERROR"


async def connection_status(tenant_id: UUID | None = None) -> dict[str, Any]:
    """Probe the provider. Never claims a connection it has not just made."""
    from application.communications.registry import get_whatsapp_adapter

    adapter = get_whatsapp_adapter()
    activation = adapter.activation_status()

    if not adapter.is_configured():
        return {
            "state": NOT_CONFIGURED,
            "configured": False,
            "missing": activation["missing_configuration"],
            "detail": (
                "WhatsApp is not connected. The credentials Meta issues for a "
                "WhatsApp Business number have not been supplied."
            ),
            "prerequisite": activation["activation_prerequisite"],
            "business_number": None,
            "webhook_path": _webhook_path(),
            "channel_registered": await _channel_registered(tenant_id),
        }

    # A real call to Meta with the real credentials. This is the whole point.
    probe = await adapter.health()
    if not probe.ok:
        return {
            "state": ERROR,
            "configured": True,
            "missing": [],
            "detail": (
                "Credentials are present, but Meta refused them. Nothing can be "
                "sent or received until this is resolved."
            ),
            "error_code": probe.error_code,
            "error_message": probe.error_message,
            "business_number": None,
            "webhook_path": _webhook_path(),
            "channel_registered": await _channel_registered(tenant_id),
        }

    raw = probe.raw or {}
    return {
        "state": CONNECTED,
        "configured": True,
        "missing": [],
        "detail": "Meta answered with these credentials and identified the number.",
        # Straight from the provider, so the owner can check it is the number they
        # think it is before anybody messages a customer from it.
        "business_number": {
            "display_phone_number": raw.get("display_phone_number"),
            "verified_name": raw.get("verified_name"),
            "quality_rating": raw.get("quality_rating"),
        },
        "webhook_path": _webhook_path(),
        "channel_registered": await _channel_registered(tenant_id),
    }


def _webhook_path() -> str:
    """Where Meta must be told to deliver. Path only - the host is the tunnel's."""
    return "/v1/webhooks/inbound/whatsapp/whatsapp_cloud"


async def _channel_registered(tenant_id: UUID | None) -> dict[str, Any]:
    """Has this workspace claimed the business number that webhooks arrive on?

    Without this row an inbound message cannot be routed to a tenant and is
    refused. It is the single most likely reason a live test appears to do
    nothing, so it is reported next to the credentials rather than buried.
    """
    if tenant_id is None:
        return {"registered": False, "identifier": None}

    from sqlalchemy import select

    from infrastructure.database.models.communications import Channel
    from infrastructure.database.session import tenant_session

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(Channel.identifier, Channel.health_status).where(
                    Channel.tenant_id == tenant_id,
                    Channel.channel_type == "whatsapp",
                    Channel.deleted_at.is_(None),
                )
            )
        ).first()

    if row is None:
        return {
            "registered": False,
            "identifier": None,
            "detail": (
                "This workspace has not claimed a WhatsApp business number, so an "
                "inbound message would have no workspace to belong to."
            ),
        }
    return {"registered": True, "identifier": row[0], "health": row[1]}


async def real_test_checklist(tenant_id: UUID) -> list[dict[str, Any]]:
    """How far a genuine end-to-end WhatsApp test has actually got.

    Every row is observed, not asserted. Nothing is marked done because the code
    exists; each one is answered from the provider, the configuration or the rows
    a real message would have written.
    """
    from sqlalchemy import func, select

    from infrastructure.database.models.communications import Message
    from infrastructure.database.session import tenant_session

    status = await connection_status(tenant_id)

    async with tenant_session(tenant_id) as session:
        inbound = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Message)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.channel == "whatsapp",
                        Message.direction == "inbound",
                    )
                )
            ).scalar_one()
        )
        outbound_accepted = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Message)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.channel == "whatsapp",
                        Message.direction == "outbound",
                        Message.external_id.is_not(None),
                    )
                )
            ).scalar_one()
        )
        reconciled = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(Message)
                    .where(
                        Message.tenant_id == tenant_id,
                        Message.channel == "whatsapp",
                        Message.direction == "outbound",
                        Message.status.in_(("delivered", "read")),
                    )
                )
            ).scalar_one()
        )

    channel = status["channel_registered"]

    def row(key: str, label: str, done: bool, detail: str) -> dict[str, Any]:
        return {"key": key, "label": label, "observed": done, "detail": detail}

    return [
        row(
            "credentials",
            "Credentials configured",
            bool(status["configured"]),
            "The Meta phone number id, access token and app secret are present."
            if status["configured"]
            else f"Missing: {', '.join(status.get('missing') or []) or 'all of them'}.",
        ),
        row(
            "provider_identity",
            "Provider identity verified",
            status["state"] == CONNECTED,
            (
                f"Meta identified this number as "
                f"{(status.get('business_number') or {}).get('display_phone_number')}."
                if status["state"] == CONNECTED
                else "Meta has not confirmed these credentials."
            ),
        ),
        row(
            "channel_routing",
            "Business number claimed by this workspace",
            bool(channel.get("registered")),
            channel.get("detail")
            or f"Inbound messages on {channel.get('identifier')} belong to this workspace.",
        ),
        row(
            "webhook_reachable",
            "Webhook reachable from the internet",
            False,
            (
                "Cannot be observed from inside the app. Meta calls the webhook, so "
                "the proof is an inbound message arriving below."
            ),
        ),
        row(
            "inbound_observed",
            "A real inbound message arrived",
            inbound > 0,
            f"{inbound} inbound WhatsApp message(s) recorded against this workspace."
            if inbound
            else "No inbound WhatsApp message has ever reached this workspace.",
        ),
        row(
            "outbound_accepted",
            "A real outbound reply was accepted",
            outbound_accepted > 0,
            f"{outbound_accepted} reply(ies) came back with a provider message id."
            if outbound_accepted
            else "No reply has been accepted by the provider yet.",
        ),
        row(
            "status_reconciled",
            "Delivery status came back",
            reconciled > 0,
            f"{reconciled} outbound message(s) reached delivered or read."
            if reconciled
            else "No delivery or read receipt has been received.",
        ),
    ]
