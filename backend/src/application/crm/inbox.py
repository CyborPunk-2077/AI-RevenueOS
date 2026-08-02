"""Conversations and messages: the shared inbox.

Three things make this module different from the five CRM modules before it.

**`app.messages` is partitioned by month**, with a composite primary key of
`(id, created_at)`. `created_at` is therefore supplied explicitly on every insert
rather than left to a column default: PostgreSQL has to know which partition the
row belongs to before it can write it, and a missing partition is an error, not a
silent fallback. `ensure_partition` covers the current month before any write.

**Messages are immutable in both directions.** There is no update or delete route.
Status moves forward through the delivery lifecycle and nothing else changes; a
sent message that can be edited afterwards is not a record of a conversation.

**Outbound sending is gated and never faked.** WhatsApp, email, SMS and voice all
require a credential nobody has yet, so an outbound message is persisted with
status `queued` and the response says so. It is not marked `sent`, and no delivery
timestamp is invented. When a provider is genuinely activated, the worker picks up
the queued rows -- the API contract does not change.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.base import DomainEvent
from domain.events.catalog import (
    CONVERSATION_ASSIGNED,
    CONVERSATION_MESSAGE_RECEIVED,
    CONVERSATION_RESOLVED,
    MESSAGE_QUEUED,
)
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound, ValidationError
from shared.pagination import Page
from shared.settings import Settings, get_settings
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.crm.inbox")

CONVERSATION_STATUSES = ("active", "resolved", "archived", "spam")
CHANNELS = ("whatsapp", "email", "web_chat", "voice", "sms")

# Which feature flag gates each channel. `web_chat` is first-party -- no external
# provider, no credential to obtain -- so it is the one channel that can actually
# deliver today.
CHANNEL_FLAGS: dict[str, str] = {
    "whatsapp": "whatsapp_enabled",
    "email": "email_enabled",
    "sms": "sms_enabled",
    "voice": "voice_enabled",
    "web_chat": "webchat_enabled",
}


def channel_ready(channel: str, cfg: Settings | None = None) -> bool:
    """True only when both the gate and the real provider configuration hold."""
    settings = cfg or get_settings()
    if channel == "whatsapp":
        from application.communications.registry import get_whatsapp_adapter

        return get_whatsapp_adapter(settings).is_configured()
    if channel == "email":
        from application.communications.registry import get_email_adapter

        return get_email_adapter(settings).is_configured()
    if channel == "voice":
        from application.communications.registry import get_voice_adapter

        return get_voice_adapter(settings).is_configured()
    if channel == "sms":
        # There is no selected SMS adapter until DLT registration and provider
        # contracting are complete. A flag alone cannot make delivery real.
        return False
    flag = CHANNEL_FLAGS.get(channel)
    return bool(flag and getattr(settings.features, flag, False))


def serialize_conversation(
    row: Any, *, contact_name: str | None = None, assignee_name: str | None = None
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "subject": row.subject,
        "primary_channel": row.primary_channel,
        "status": row.status,
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "contact_name": contact_name,
        "assignee_id": str(row.assignee_id) if row.assignee_id else None,
        "assignee_name": assignee_name,
        "unread_count": row.unread_count,
        "automation_stopped": row.automation_stopped,
        "last_message_at": row.last_message_at.isoformat() if row.last_message_at else None,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_message(row: Any, *, sender_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "conversation_id": str(row.conversation_id),
        "channel": row.channel,
        "direction": row.direction,
        "sender_type": row.sender_type,
        "sender_name": sender_name,
        # A redacted message keeps its envelope and loses its body, so the thread
        # still reads correctly after a privacy deletion.
        "content": None if row.redacted_at else row.content,
        "content_type": row.content_type,
        "status": row.status,
        "failure_reason": row.failure_reason,
        "redacted": row.redacted_at is not None,
        "delivered_at": row.delivered_at.isoformat() if row.delivered_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@dataclass(slots=True)
class InboxService(_PrincipalScoped):
    """Conversation threads and the messages inside them."""

    async def _ensure_partition(self, session: Any, moment: datetime) -> None:
        """Create this month's partition if it is missing.

        A write into a partitioned parent with no matching child raises
        `no partition of relation "messages" found for row`. The nightly
        maintenance task creates them ahead of time; this covers a database that
        has just been created, or a month boundary crossed between sweeps.
        """
        from sqlalchemy import text

        from infrastructure.database.ddl import partition_statements

        suffix = moment.strftime("%Y%m")
        exists = (
            await session.execute(
                text(
                    "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'app' AND c.relname = :name"
                ),
                {"name": f"messages_p{suffix}"},
            )
        ).scalar_one_or_none()
        if exists:
            return
        # Partition DDL needs CREATE, which the runtime role deliberately lacks,
        # so this runs on the maintenance credential.
        from infrastructure.database.session import maintenance_session

        async with maintenance_session() as maint:
            for statement in partition_statements(
                "app", "messages", "month", moment.date(), periods=1
            ):
                await maint.execute(text(statement))
        logger.info("messages_partition_created", month=suffix)

    async def _names(self, session: Any, user_ids: set[UUID]) -> dict[UUID, str]:
        if not user_ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.users import User

        rows = await session.execute(
            select(User.id, User.full_name).where(
                User.id.in_(user_ids), User.tenant_id == self.tenant_id
            )
        )
        return {row[0]: row[1] for row in rows}

    async def _contact_names(self, session: Any, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.crm import Contact

        rows = await session.execute(
            select(Contact.id, Contact.first_name, Contact.last_name).where(
                Contact.id.in_(ids), Contact.tenant_id == self.tenant_id
            )
        )
        return {row[0]: f"{row[1]} {row[2] or ''}".strip() for row in rows}

    # --- conversations ------------------------------------------------------

    async def list_conversations(
        self, query: Any, *, status: str | None = None, mine: bool = False
    ) -> Page:
        from infrastructure.database.models.communications import Conversation
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ConversationRepository(TenantRepository[Conversation]):
            model = Conversation

        if status and status not in CONVERSATION_STATUSES:
            raise ValidationError(f"Unknown status: {status!r}.")

        async with tenant_session(self.tenant_id) as session:
            repo = ConversationRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if status:
                stmt = stmt.where(Conversation.status == status)
            if mine:
                stmt = stmt.where(Conversation.assignee_id == self.user_id)
            # Newest activity first: an inbox sorted by creation date buries the
            # thread that just got a reply.
            stmt = stmt.order_by(
                Conversation.last_message_at.desc().nulls_last(),
                Conversation.created_at.desc(),
            )

            page = await repo.paginate_cursor(
                self.permissions_scope(), stmt, cursor=query.cursor, page_size=query.page_size
            )
            contacts = await self._contact_names(
                session, {c.contact_id for c in page.items if c.contact_id}
            )
            people = await self._names(
                session, {c.assignee_id for c in page.items if c.assignee_id}
            )
            page.items = [
                serialize_conversation(
                    c,
                    contact_name=contacts.get(c.contact_id) if c.contact_id else None,
                    assignee_name=people.get(c.assignee_id) if c.assignee_id else None,
                )
                for c in page.items
            ]
            return page

    async def get(self, conversation_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.communications import Conversation
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ConversationRepository(TenantRepository[Conversation]):
            model = Conversation

        async with tenant_session(self.tenant_id) as session:
            row = await ConversationRepository(session, self.tenant_id).get_scoped(
                conversation_id, self.permissions_scope()
            )
            if row is None:
                raise NotFound("Conversation not found.")
            contacts = await self._contact_names(
                session, {row.contact_id} if row.contact_id else set()
            )
            people = await self._names(session, {row.assignee_id} if row.assignee_id else set())
            return serialize_conversation(
                row,
                contact_name=contacts.get(row.contact_id) if row.contact_id else None,
                assignee_name=people.get(row.assignee_id) if row.assignee_id else None,
            )

    async def thread(self, conversation_id: UUID) -> list[dict[str, Any]]:
        """Every message in one conversation, oldest first, as a thread reads."""
        await self.get(conversation_id)  # 404s before revealing anything

        from sqlalchemy import select

        from infrastructure.database.models.communications import Message
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            rows = list(
                (
                    await session.execute(
                        select(Message)
                        .where(Message.conversation_id == conversation_id)
                        .order_by(Message.created_at.asc())
                        .limit(500)
                    )
                )
                .scalars()
                .all()
            )
            people = await self._names(session, {m.sender_id for m in rows if m.sender_id})
            return [
                serialize_message(m, sender_name=people.get(m.sender_id) if m.sender_id else None)
                for m in rows
            ]

    async def open_conversation(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Start a thread, optionally against a contact."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.communications import Conversation
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        channel = str(payload.get("primary_channel", "web_chat"))
        if channel not in CHANNELS:
            raise ValidationError(f"Unknown channel: {channel!r}.")

        contact_id = payload.get("contact_id")
        if contact_id:
            await self._assert_contact_visible(contact_id)

        conversation_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                Conversation(
                    id=conversation_id,
                    tenant_id=self.tenant_id,
                    contact_id=contact_id,
                    primary_channel=channel,
                    subject=(payload.get("subject") or "")[:300] or None,
                    status="active",
                    assignee_id=payload.get("assignee_id"),
                    unread_count=0,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="conversation.open",
                resource_type="conversation",
                resource_id=conversation_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"channel": channel},
            )
        logger.info("conversation_opened", conversation_id=str(conversation_id))
        return await self.get(conversation_id)

    async def _assert_contact_visible(self, contact_id: UUID) -> None:
        from application.crm.service import ContactService

        await ContactService(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        ).get(contact_id)

    async def update_conversation(
        self, conversation_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        """Assign, resolve, archive or mark as spam."""
        from application.audit.recorder import AuditRecorder, diff_for_audit
        from infrastructure.database.models.communications import Conversation
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class ConversationRepository(TenantRepository[Conversation]):
            model = Conversation

        if changes.get("status") and changes["status"] not in CONVERSATION_STATUSES:
            raise ValidationError(
                f"Unknown status. Expected one of: {', '.join(CONVERSATION_STATUSES)}."
            )

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = ConversationRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped_or_404(conversation_id, self.permissions_scope())
            before = serialize_conversation(row)

            for field_name, value in changes.items():
                if field_name == "assignee_id" or value is not None:
                    setattr(row, field_name, value)

            await repo.bump_version(row, expected_version)
            after = serialize_conversation(row)

            events = []
            if before["assignee_id"] != after["assignee_id"] and after["assignee_id"]:
                events.append(
                    DomainEvent(
                        event_type=CONVERSATION_ASSIGNED,
                        tenant_id=self.tenant_id,
                        resource_type="conversation",
                        resource_id=conversation_id,
                        actor_id=self.user_id,
                        payload={"assignee_id": after["assignee_id"]},
                    )
                )
            if before["status"] != "resolved" and after["status"] == "resolved":
                events.append(
                    DomainEvent(
                        event_type=CONVERSATION_RESOLVED,
                        tenant_id=self.tenant_id,
                        resource_type="conversation",
                        resource_id=conversation_id,
                        actor_id=self.user_id,
                        payload={},
                    )
                )

            old_values, new_values = diff_for_audit(before, after)
            AuditRecorder(uow.session).record(
                action="conversation.update",
                resource_type="conversation",
                resource_id=conversation_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values=old_values,
                new_values=new_values,
            )
            if events:
                uow.collect(*events)
        return await self.get(conversation_id)

    async def mark_read(self, conversation_id: UUID) -> dict[str, Any]:
        """Clear the unread counter. Idempotent."""
        from infrastructure.database.models.communications import Conversation
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class ConversationRepository(TenantRepository[Conversation]):
            model = Conversation

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = ConversationRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped_or_404(conversation_id, self.permissions_scope())
            row.unread_count = 0
        return await self.get(conversation_id)

    # --- messages -----------------------------------------------------------

    async def receive(self, conversation_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        """Record an inbound message.

        Inbound is the half that works today: a message that has already arrived
        needs no provider credential to be written down. Real ingress arrives via
        the verified provider webhooks; this is the same path they land on.
        """
        conversation = await self.get(conversation_id)

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.communications import Conversation, Message
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        content = str(payload.get("content", "")).strip()
        if not content:
            raise ValidationError("A message needs content.")

        channel = str(payload.get("channel") or conversation["primary_channel"])
        if channel not in CHANNELS:
            raise ValidationError(f"Unknown channel: {channel!r}.")

        moment = utcnow()
        message_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            await self._ensure_partition(uow.session, moment)
            uow.session.add(
                Message(
                    id=message_id,
                    # Explicit: it is half the primary key and decides the partition.
                    created_at=moment,
                    tenant_id=self.tenant_id,
                    conversation_id=conversation_id,
                    channel=channel,
                    direction="inbound",
                    sender_type="contact",
                    content=content,
                    content_type="text",
                    # An inbound message is, by definition, already delivered.
                    status="delivered",
                    delivered_at=moment,
                )
            )
            from sqlalchemy import select

            row = (
                await uow.session.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
            ).scalar_one()
            row.last_message_at = moment
            row.unread_count = row.unread_count + 1

            AuditRecorder(uow.session).record(
                action="message.receive",
                resource_type="message",
                resource_id=message_id,
                tenant_id=self.tenant_id,
                actor_id=None,
                actor_type="system",
                new_values={"channel": channel, "conversation_id": str(conversation_id)},
            )
            uow.collect(
                DomainEvent(
                    event_type=CONVERSATION_MESSAGE_RECEIVED,
                    tenant_id=self.tenant_id,
                    resource_type="conversation",
                    resource_id=conversation_id,
                    actor_id=None,
                    payload={"message_id": str(message_id), "channel": channel},
                )
            )

        logger.info("message_received", conversation_id=str(conversation_id), channel=channel)
        return await self._read_message(message_id, moment)

    async def send(self, conversation_id: UUID, payload: dict[str, Any]) -> dict[str, Any]:
        """Queue an outbound reply.

        The status is `queued`, and it stays `queued` until a real provider
        acknowledges it. Nothing here marks a message `sent` or stamps a delivery
        time -- doing so would let an operator believe a customer received
        something that never left the building.
        """
        conversation = await self.get(conversation_id)

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.communications import Conversation, Message
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        content = str(payload.get("content", "")).strip()
        if not content:
            raise ValidationError("A message needs content.")

        channel = str(payload.get("channel") or conversation["primary_channel"])
        if channel not in CHANNELS:
            raise ValidationError(f"Unknown channel: {channel!r}.")

        ready = channel_ready(channel)
        moment = utcnow()
        message_id = uuid7()

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            await self._ensure_partition(uow.session, moment)
            uow.session.add(
                Message(
                    id=message_id,
                    created_at=moment,
                    tenant_id=self.tenant_id,
                    conversation_id=conversation_id,
                    channel=channel,
                    direction="outbound",
                    sender_type="agent",
                    sender_id=self.user_id,
                    content=content,
                    content_type="text",
                    status="queued",
                    failure_reason=(
                        None
                        if ready
                        else f"{channel} is not configured; the message is held until it is"
                    ),
                )
            )
            from sqlalchemy import select

            row = (
                await uow.session.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
            ).scalar_one()
            if row.contact_id and channel in {"whatsapp", "email", "sms", "voice"}:
                from application.communications.consents import contact_has_consent

                if not await contact_has_consent(
                    uow.session,
                    tenant_id=self.tenant_id,
                    contact_id=row.contact_id,
                    channel=channel,
                ):
                    raise ValidationError(
                        "No current consent permits this channel for the linked contact.",
                        details={"channel": channel, "consent_required": True},
                    )
            row.last_message_at = moment
            # A human replied, so automation stops driving this thread.
            if not row.automation_stopped:
                row.automation_stopped = True
                row.automation_stopped_reason = "agent_reply"

            AuditRecorder(uow.session).record(
                action="message.queue",
                resource_type="message",
                resource_id=message_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"channel": channel, "provider_ready": ready},
            )
            uow.collect(
                DomainEvent(
                    event_type=MESSAGE_QUEUED,
                    tenant_id=self.tenant_id,
                    resource_type="message",
                    resource_id=message_id,
                    actor_id=self.user_id,
                    payload={
                        "conversation_id": str(conversation_id),
                        "channel": channel,
                        "provider_ready": ready,
                    },
                )
            )

        logger.info(
            "message_queued",
            conversation_id=str(conversation_id),
            channel=channel,
            provider_ready=ready,
        )
        message = await self._read_message(message_id, moment)
        return {
            **message,
            "provider_ready": ready,
            # Said plainly, because "queued" on its own reads like success.
            "delivery_note": (
                "Queued for delivery."
                if ready
                else f"Held: {channel} has no provider credential configured yet."
            ),
        }

    async def _read_message(self, message_id: UUID, created_at: datetime) -> dict[str, Any]:
        from sqlalchemy import select

        from infrastructure.database.models.communications import Message
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            row = (
                await session.execute(
                    select(Message).where(
                        Message.id == message_id, Message.created_at == created_at
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                raise NotFound("Message not found.")
            people = await self._names(session, {row.sender_id} if row.sender_id else set())
            return serialize_message(
                row, sender_name=people.get(row.sender_id) if row.sender_id else None
            )

    async def channel_readiness(self) -> list[dict[str, Any]]:
        """What can actually be sent right now, and what each channel is waiting on."""
        settings = get_settings()
        return [
            {
                "channel": channel,
                "ready": channel_ready(channel, settings),
                "flag": CHANNEL_FLAGS[channel],
            }
            for channel in CHANNELS
        ]
