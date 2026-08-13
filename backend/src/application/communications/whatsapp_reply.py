"""Replying to a prospect on WhatsApp, through the real Cloud API.

The one rule that governs this file: **the provider decides whether a message was
sent, and we record what it decided.**

That sounds obvious and it is the thing most integrations get wrong. A reply that
the API rejected, or that was written while no provider is configured at all, must
never leave the prospect looking answered. So the outcome written on the timeline
comes from the provider's response, and it is handed to the same canonical
first-response rule that a phone call goes through:

* provider accepted it  -> outcome `sent`   -> this answers the enquiry
* provider rejected it  -> outcome `failed` -> the prospect is still waiting
* nothing configured    -> outcome `failed` -> queued honestly, and still waiting

There is no fourth branch where we assume it probably went out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from application.ports import OutboundMessage
from domain.leads.first_response import FAILED, SENT
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.phone import try_normalize_phone
from shared.utils.timeutil import utcnow

logger = get_logger("communications.whatsapp_reply")

CHANNEL = "whatsapp"
MAX_CHARS = 4096


@dataclass(slots=True)
class WhatsAppReplyService(_PrincipalScoped):
    """Send one reply to one prospect, and record exactly what happened."""

    async def reply(self, lead_id: UUID, text: str) -> dict[str, Any]:
        body = (text or "").strip()
        if not body:
            raise ValidationError("A reply cannot be empty.")
        if len(body) > MAX_CHARS:
            raise ValidationError(f"WhatsApp messages are limited to {MAX_CHARS} characters.")

        # Scoped read first, so replying to another team's prospect is a 404
        # before anything reaches the provider.
        from application.leads.service import LeadService

        lead = await LeadService(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        ).get(lead_id)

        to = try_normalize_phone(lead.get("phone"))
        if not to:
            raise ValidationError("This prospect has no usable WhatsApp number.")

        from application.audit.recorder import AuditRecorder
        from application.communications.registry import get_whatsapp_adapter
        from application.communications.whatsapp_ingest import conversation_for
        from application.leads.first_response import record_first_response
        from infrastructure.database.models.communications import Message
        from infrastructure.database.models.crm import Activity
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        adapter = get_whatsapp_adapter()
        message_id = uuid7()
        idempotency_key = str(message_id)

        # The provider call happens outside the transaction on purpose. Holding a
        # database transaction open across a network round trip to Meta is how a
        # slow provider becomes a database incident.
        result = await adapter.send(
            OutboundMessage(
                tenant_id=self.tenant_id,
                to=to,
                channel=CHANNEL,
                body=body,
                idempotency_key=idempotency_key,
            )
        )

        delivered = bool(result.ok)
        outcome = SENT if delivered else FAILED
        status = "sent" if delivered else ("pending" if result.queued else "failed")
        occurred_at = utcnow()

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            session = uow.session
            conversation_id = await conversation_for(session, self.tenant_id, lead_id, occurred_at)
            await session.flush()

            session.add(
                Message(
                    id=message_id,
                    created_at=occurred_at,
                    tenant_id=self.tenant_id,
                    conversation_id=conversation_id,
                    channel=CHANNEL,
                    direction="outbound",
                    sender_type="user",
                    sender_id=self.user_id,
                    content=body,
                    content_type="text",
                    status=status,
                    failure_reason=(result.error_message or "")[:300] if not delivered else None,
                    external_id=result.external_id,
                    idempotency_key=idempotency_key,
                )
            )

            session.add(
                Activity(
                    id=uuid7(),
                    tenant_id=self.tenant_id,
                    activity_type=CHANNEL,
                    subject=body[:300],
                    body=body,
                    entity_type="lead",
                    entity_id=lead_id,
                    actor_id=self.user_id,
                    actor_type="user",
                    metadata_json={
                        "direction": "outbound",
                        "outcome": outcome,
                        "external_id": result.external_id,
                        # Kept so "why is this marked failed?" is answerable from
                        # the record months later, without a log search.
                        "provider_error": result.error_code if not delivered else None,
                    },
                    created_at=occurred_at,
                )
            )

            # Only a genuine send answers the enquiry. `failed` is in the domain's
            # unengaged set, so this call is what refuses it - not an `if` here.
            answered = await record_first_response(
                uow,
                tenant_id=self.tenant_id,
                lead_id=lead_id,
                channel=CHANNEL,
                direction="outbound",
                outcome=outcome,
                occurred_at=occurred_at,
                actor_id=self.user_id,
                source="whatsapp.reply",
            )

            AuditRecorder(session).record(
                action="whatsapp.reply",
                resource_type="message",
                resource_id=message_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                outcome="success" if delivered else "failure",
                new_values={"lead_id": str(lead_id), "status": status},
            )

        logger.info(
            "whatsapp_reply_attempted",
            tenant_id=str(self.tenant_id),
            lead_id=str(lead_id),
            delivered=delivered,
            status=status,
        )

        return {
            "sent": delivered,
            "status": status,
            "provider_message_id": result.external_id,
            "recorded_first_response": answered,
            # Surfaced rather than swallowed: an owner who cannot see why a reply
            # did not go will assume the product is broken, which is worse than
            # the truth.
            "error_code": None if delivered else result.error_code,
            "error_message": None if delivered else result.error_message,
        }


async def lead_for_conversation(tenant_id: UUID, conversation_id: UUID) -> UUID:
    from sqlalchemy import select

    from infrastructure.database.models.communications import Conversation
    from infrastructure.database.session import tenant_session

    async with tenant_session(tenant_id) as session:
        lead_id = (
            await session.execute(
                select(Conversation.lead_id).where(Conversation.id == conversation_id)
            )
        ).scalar_one_or_none()
    if lead_id is None:
        raise NotFound("Conversation not found.")
    return UUID(str(lead_id))
