"""Turning a verified WhatsApp webhook into Sangam's own customer record.

Before this existed, an inbound WhatsApp event was verified, deduplicated, logged
and then dropped. That is why the module matters: the adapter was complete and the
product still could not answer "who messaged us, and has anybody replied?"

Everything here writes into the **canonical** customer context - the same leads,
conversations, activities and tasks the rest of Sangam reads. There is deliberately
no WhatsApp-shaped copy of a customer, no separate WhatsApp inbox model and no
second definition of a prospect. A business that later switches WhatsApp off keeps
every conversation it had.

Four rules this file exists to keep:

* **An inbound message is an enquiry, not a reply.** It is recorded with the
  outcome `received`, handed to the one canonical first-response rule, and that
  rule says no. The prospect keeps showing as waiting until somebody answers,
  which is the entire point of the measurement.
* **Nothing is invented.** A message from a number nobody recognises creates a
  prospect with the phone number and whatever name WhatsApp reports - not a
  guessed company, not a fabricated requirement.
* **The same event twice changes nothing.** Meta retries, and it retries on the
  path where our response was slow. Idempotency is on the provider's message id,
  in the database, not only in a cache that a restart empties.
* **Routing is explicit.** The tenant is resolved from the business number the
  message arrived on. A payload that matches no configured number is refused
  rather than filed under a default workspace.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from uuid import UUID

from domain.leads.first_response import RECEIVED
from infrastructure.logging.setup import get_logger
from shared.utils.ids import uuid7
from shared.utils.phone import try_normalize_phone
from shared.utils.timeutil import utcnow

logger = get_logger("communications.whatsapp_ingest")

CHANNEL: Final = "whatsapp"

#: How many trailing digits make two numbers "the same person". Ten is the Indian
#: mobile length, and it is what the CSV importer already uses - so a business
#: imported as `09845012201` and messaging from `+919845012201` is one prospect,
#: not two. Stated once here and reused rather than re-derived.
MATCH_DIGITS: Final = 10


@dataclass(frozen=True, slots=True)
class Ingested:
    """What happened to one inbound message."""

    accepted: bool
    reason: str
    tenant_id: UUID | None = None
    lead_id: UUID | None = None
    conversation_id: UUID | None = None
    message_id: UUID | None = None
    created_lead: bool = False


def _match_key(phone: str | None) -> str | None:
    digits = "".join(character for character in (phone or "") if character.isdigit())
    return digits[-MATCH_DIGITS:] if len(digits) >= MATCH_DIGITS else None


async def resolve_tenant(business_phone_number_id: str | None) -> UUID | None:
    """Which workspace owns the number this message arrived on.

    Registered in `app.channels`, which already carries a unique
    (tenant, channel_type, identifier). No configured channel means no tenant, and
    the event is refused - filing a stranger's enquiry into whichever workspace
    happened to be first would be worse than dropping it.
    """
    if not business_phone_number_id:
        return None

    from sqlalchemy import select

    from infrastructure.database.models.communications import Channel
    from infrastructure.database.session import admin_session

    async with admin_session() as session:
        tenant_id = (
            await session.execute(
                select(Channel.tenant_id).where(
                    Channel.channel_type == CHANNEL,
                    Channel.identifier == str(business_phone_number_id),
                    Channel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

    return UUID(str(tenant_id)) if tenant_id else None


async def _already_ingested(session: Any, tenant_id: UUID, external_id: str) -> bool:
    """Has this provider message id already been written for this tenant?

    In the database rather than only in Redis. The cache is the fast path; this is
    the one that still holds after a restart, and Meta will happily redeliver a
    webhook hours later.
    """
    from sqlalchemy import select

    from infrastructure.database.models.communications import Message

    found = (
        await session.execute(
            select(Message.id).where(
                Message.tenant_id == tenant_id,
                Message.channel == CHANNEL,
                Message.external_id == external_id,
            )
        )
    ).first()
    return found is not None


async def _find_lead_by_phone(session: Any, tenant_id: UUID, phone: str) -> UUID | None:
    """An existing prospect with this number, most recently created first."""
    from sqlalchemy import func, select

    from infrastructure.database.models.leads import Lead

    key = _match_key(phone)
    if not key:
        return None

    row = (
        await session.execute(
            select(Lead.id)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.deleted_at.is_(None),
                # Compare on trailing digits so formatting differences do not
                # create a second copy of a business already being worked.
                func.right(func.regexp_replace(Lead.phone, r"\D", "", "g"), MATCH_DIGITS) == key,
            )
            .order_by(Lead.created_at.desc())
            .limit(1)
        )
    ).first()
    return UUID(str(row[0])) if row else None


async def _create_lead(
    session: Any, tenant_id: UUID, *, phone: str, profile_name: str | None, occurred_at: datetime
) -> UUID:
    """A prospect for a number nobody recognises.

    Deliberately thin. The phone number is the only thing actually known; the
    WhatsApp profile name is whatever the customer typed into their own handset,
    so it is used as a label and nothing more. No company, no requirement, no
    score is invented - somebody in the business will fill those in after they
    have spoken to the person.
    """
    from infrastructure.database.models.leads import Lead

    lead_id = uuid7()
    session.add(
        Lead(
            id=lead_id,
            tenant_id=tenant_id,
            first_name=(profile_name or "WhatsApp enquiry")[:120],
            phone=phone,
            source="whatsapp",
            source_channel=CHANNEL,
            capture={
                "captured_via": "whatsapp_inbound",
                # Not `demo_data`. This is a real enquiry from a real number and
                # must never be inside a demo manifest's reach.
                "first_seen_at": occurred_at.isoformat(),
            },
            utm={},
            reasoning={},
            status="new",
            version=1,
        )
    )
    return lead_id


async def conversation_for(
    session: Any, tenant_id: UUID, lead_id: UUID, occurred_at: datetime
) -> UUID:
    """The open WhatsApp thread with this prospect, or a new one."""
    from sqlalchemy import select

    from infrastructure.database.models.communications import Conversation

    existing = (
        await session.execute(
            select(Conversation.id)
            .where(
                Conversation.tenant_id == tenant_id,
                Conversation.lead_id == lead_id,
                Conversation.primary_channel == CHANNEL,
                Conversation.status == "active",
                Conversation.deleted_at.is_(None),
            )
            .order_by(Conversation.created_at.desc())
            .limit(1)
        )
    ).first()
    if existing:
        return UUID(str(existing[0]))

    conversation_id = uuid7()
    session.add(
        Conversation(
            id=conversation_id,
            tenant_id=tenant_id,
            lead_id=lead_id,
            primary_channel=CHANNEL,
            subject="WhatsApp",
            status="active",
            last_message_at=occurred_at,
            metadata_json={"source": "whatsapp_cloud"},
            version=1,
        )
    )
    return conversation_id


async def ingest_inbound_message(event: dict[str, Any]) -> Ingested:
    """One verified inbound WhatsApp message, written into the customer record."""
    external_id = str(event.get("external_id") or "")
    if not external_id:
        return Ingested(accepted=False, reason="no_external_id")

    tenant_id = await resolve_tenant(event.get("business_phone_number_id"))
    if tenant_id is None:
        # Refused, loudly. This is a configuration problem, and treating it as one
        # is how the founders find out rather than wondering where a message went.
        logger.warning(
            "whatsapp_inbound_unroutable",
            business_phone_number_id=event.get("business_phone_number_id"),
        )
        return Ingested(accepted=False, reason="no_tenant_for_business_number")

    phone = try_normalize_phone(event.get("from"))
    if not phone:
        return Ingested(accepted=False, reason="unusable_sender_number", tenant_id=tenant_id)

    from sqlalchemy import select

    from application.audit.recorder import AuditRecorder
    from application.leads.first_response import record_first_response
    from infrastructure.database.models.communications import Conversation, Message
    from infrastructure.database.models.crm import Activity
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    occurred_at = utcnow()

    async with SqlAlchemyUnitOfWork(tenant_id) as uow:
        session = uow.session

        if await _already_ingested(session, tenant_id, external_id):
            return Ingested(accepted=False, reason="duplicate", tenant_id=tenant_id)

        lead_id = await _find_lead_by_phone(session, tenant_id, phone)
        created_lead = lead_id is None
        if lead_id is None:
            lead_id = await _create_lead(
                session,
                tenant_id,
                phone=phone,
                profile_name=event.get("profile_name"),
                occurred_at=occurred_at,
            )
            await session.flush()

        conversation_id = await conversation_for(session, tenant_id, lead_id, occurred_at)
        await session.flush()

        message_id = uuid7()
        session.add(
            Message(
                id=message_id,
                created_at=occurred_at,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                channel=CHANNEL,
                direction="inbound",
                sender_type="contact",
                content=event.get("content"),
                content_type=str(event.get("content_type") or "text"),
                media=event.get("media") or {},
                status="delivered",
                delivered_at=occurred_at,
                external_id=external_id,
            )
        )

        # The timeline entry, so the prospect's history reads the same whether the
        # contact came through a provider or was typed in by hand.
        session.add(
            Activity(
                id=uuid7(),
                tenant_id=tenant_id,
                activity_type=CHANNEL,
                subject=(event.get("content") or "WhatsApp message")[:300],
                body=event.get("content"),
                entity_type="lead",
                entity_id=lead_id,
                actor_id=None,
                actor_type="system",
                metadata_json={
                    "direction": "inbound",
                    "outcome": RECEIVED,
                    "external_id": external_id,
                },
                created_at=occurred_at,
            )
        )

        # Asked, and answered "no". An inbound message is the enquiry; nobody has
        # replied to it yet. Calling this rather than skipping it is the point -
        # there is one rule, and every channel goes through it.
        await record_first_response(
            uow,
            tenant_id=tenant_id,
            lead_id=lead_id,
            channel=CHANNEL,
            direction="inbound",
            outcome=RECEIVED,
            occurred_at=occurred_at,
            actor_id=None,
            source="whatsapp.inbound",
        )

        conversation = (
            await session.execute(select(Conversation).where(Conversation.id == conversation_id))
        ).scalar_one()
        conversation.last_message_at = occurred_at
        conversation.unread_count += 1

        AuditRecorder(session).record(
            action="whatsapp.inbound",
            resource_type="message",
            resource_id=message_id,
            tenant_id=tenant_id,
            actor_id=None,
            new_values={"lead_id": str(lead_id), "external_id": external_id},
        )

    logger.info(
        "whatsapp_inbound_recorded",
        tenant_id=str(tenant_id),
        lead_id=str(lead_id),
        created_lead=created_lead,
    )
    return Ingested(
        accepted=True,
        reason="recorded",
        tenant_id=tenant_id,
        lead_id=lead_id,
        conversation_id=conversation_id,
        message_id=message_id,
        created_lead=created_lead,
    )


async def ingest_status_update(event: dict[str, Any]) -> Ingested:
    """A delivery receipt from Meta, applied to the message it refers to.

    Only ever moves a message *forward* through sent → delivered → read, and only
    ever records a failure that the provider actually reported. Nothing here may
    invent a delivery: a message we never heard back about stays as it was.
    """
    external_id = str(event.get("external_id") or "")
    status = str(event.get("status") or "")
    if not external_id or status not in {"sent", "delivered", "read", "failed"}:
        return Ingested(accepted=False, reason="unusable_status")

    tenant_id = await resolve_tenant(event.get("business_phone_number_id"))
    if tenant_id is None:
        return Ingested(accepted=False, reason="no_tenant_for_business_number")

    from sqlalchemy import select

    from infrastructure.database.models.communications import Message
    from infrastructure.database.session import tenant_session

    # How far along a message is. A late "sent" callback arriving after "read"
    # must not walk the status backwards, which providers do reorder in practice.
    rank = {"pending": 0, "sent": 1, "delivered": 2, "read": 3}

    async with tenant_session(tenant_id) as session:
        message = (
            await session.execute(
                select(Message).where(
                    Message.tenant_id == tenant_id,
                    Message.channel == CHANNEL,
                    Message.external_id == external_id,
                )
            )
        ).scalar_one_or_none()

        if message is None:
            return Ingested(accepted=False, reason="unknown_message", tenant_id=tenant_id)

        now = utcnow()
        if status == "failed":
            message.status = "failed"
            error = event.get("error") or {}
            message.failure_reason = str(error.get("title") or error.get("message") or "")[:300]
        elif rank.get(status, 0) > rank.get(message.status, 0):
            message.status = status
            if status == "delivered":
                message.delivered_at = now
            if status == "read":
                message.read_at = now
                if message.delivered_at is None:
                    message.delivered_at = now

    logger.info("whatsapp_status_recorded", tenant_id=str(tenant_id), status=status)
    return Ingested(accepted=True, reason=status, tenant_id=tenant_id)
