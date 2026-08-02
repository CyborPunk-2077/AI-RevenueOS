"""Immutable consent evidence and immediate revocation enforcement."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.base import DomainEvent
from domain.events.catalog import CONSENT_GRANTED, CONSENT_REVOKED
from shared.exceptions import NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

CONSENT_TYPES = frozenset({"marketing", "communication", "data_processing", "whatsapp_optin"})
CHANNELS = frozenset({"whatsapp", "email", "sms", "voice", "web_chat"})


def serialize_consent(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "subject_type": row.subject_type,
        "subject_id": str(row.subject_id) if row.subject_id else None,
        "subject_identifier": row.subject_identifier,
        "consent_type": row.consent_type,
        "channel": row.channel,
        "status": row.status,
        "evidence": dict(row.evidence or {}),
        "policy_version": row.policy_version,
        "source": row.source,
        "withdraws_id": str(row.withdraws_id) if row.withdraws_id else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "created_at": row.created_at.isoformat(),
        "created_by": str(row.created_by) if row.created_by else None,
    }


async def contact_has_consent(
    session: Any, *, tenant_id: UUID, contact_id: UUID, channel: str
) -> bool:
    """Return the current channel-specific ledger decision for a contact."""
    from sqlalchemy import or_, select

    from infrastructure.database.models.audit import ConsentRecord

    consent_type = "whatsapp_optin" if channel == "whatsapp" else "communication"
    row = (
        await session.execute(
            select(ConsentRecord)
            .where(
                ConsentRecord.tenant_id == tenant_id,
                ConsentRecord.subject_type == "contact",
                ConsentRecord.subject_id == contact_id,
                ConsentRecord.consent_type == consent_type,
                or_(ConsentRecord.channel == channel, ConsentRecord.channel.is_(None)),
            )
            .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    return bool(
        row is not None
        and row.status == "granted"
        and (row.expires_at is None or row.expires_at > utcnow())
    )


@dataclass(slots=True)
class ConsentService(_PrincipalScoped):
    async def _subject_identifier(self, subject_type: str, subject_id: UUID, channel: str) -> str:
        if subject_type != "contact":
            raise ValidationError("Only contact consent is supported by this surface.")
        from application.crm.service import ContactService

        contact = await ContactService(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        ).get(subject_id)
        identifier = contact.get("email") if channel == "email" else contact.get("phone")
        if channel == "web_chat":
            identifier = str(subject_id)
        if not identifier:
            raise ValidationError(f"The contact has no {channel} identifier.")
        return str(identifier)

    async def list_records(
        self, *, subject_type: str | None = None, subject_id: UUID | None = None
    ) -> list[dict[str, Any]]:
        from sqlalchemy import select

        from infrastructure.database.models.audit import ConsentRecord
        from infrastructure.database.models.crm import Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        if subject_type not in (None, "contact"):
            raise ValidationError("Only contact consent is supported by this surface.")
        if subject_id is not None:
            await self._subject_identifier(subject_type or "contact", subject_id, "web_chat")
        async with tenant_session(self.tenant_id) as session:
            visible_contacts = (
                ContactRepository(session, self.tenant_id)
                .scoped_query(self.permissions_scope())
                .with_only_columns(Contact.id)
            )
            stmt = (
                select(ConsentRecord)
                .where(
                    ConsentRecord.subject_type == "contact",
                    ConsentRecord.subject_id.in_(visible_contacts),
                )
                .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
            )
            if subject_type:
                stmt = stmt.where(ConsentRecord.subject_type == subject_type)
            if subject_id:
                stmt = stmt.where(ConsentRecord.subject_id == subject_id)
            rows = list((await session.execute(stmt.limit(200))).scalars().all())
        return [serialize_consent(row) for row in rows]

    async def grant(
        self,
        *,
        subject_type: str,
        subject_id: UUID,
        consent_type: str,
        channel: str,
        policy_version: str,
        source: str,
        evidence: dict[str, Any],
        expires_at: datetime | None,
    ) -> dict[str, Any]:
        if consent_type not in CONSENT_TYPES:
            raise ValidationError("Unknown consent type.")
        if channel not in CHANNELS:
            raise ValidationError("Unknown consent channel.")
        if source not in {"api", "agent_confirmed", "public_form", "provider", "import"}:
            raise ValidationError("Unknown consent evidence source.")
        identifier = await self._subject_identifier(subject_type, subject_id, channel)

        from sqlalchemy import select, text

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.audit import ConsentRecord
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        moment = utcnow()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            lock_key = (
                f"consent:{self.tenant_id}:{subject_type}:{subject_id}:{consent_type}:{channel}"
            )
            await uow.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key}
            )
            latest = (
                await uow.session.execute(
                    select(ConsentRecord)
                    .where(
                        ConsentRecord.subject_type == subject_type,
                        ConsentRecord.subject_id == subject_id,
                        ConsentRecord.consent_type == consent_type,
                        ConsentRecord.channel == channel,
                    )
                    .order_by(ConsentRecord.created_at.desc(), ConsentRecord.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if (
                latest is not None
                and latest.status == "granted"
                and (latest.expires_at is None or latest.expires_at > moment)
            ):
                return {**serialize_consent(latest), "duplicate": True}

            record_id = uuid7()
            row = ConsentRecord(
                id=record_id,
                tenant_id=self.tenant_id,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_identifier=identifier,
                consent_type=consent_type,
                channel=channel,
                status="granted",
                evidence=dict(evidence),
                policy_version=policy_version,
                source=source,
                expires_at=expires_at,
                created_at=moment,
                created_by=self.user_id,
            )
            uow.session.add(row)
            AuditRecorder(uow.session).record(
                action="consent.granted",
                resource_type="consent",
                resource_id=record_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={
                    "subject_type": subject_type,
                    "consent_type": consent_type,
                    "channel": channel,
                    "policy_version": policy_version,
                },
            )
            uow.collect(
                DomainEvent(
                    event_type=CONSENT_GRANTED,
                    tenant_id=self.tenant_id,
                    resource_type="consent",
                    resource_id=record_id,
                    actor_id=self.user_id,
                    payload={
                        "subject_type": subject_type,
                        "subject_id": str(subject_id),
                        "consent_type": consent_type,
                        "channel": channel,
                    },
                )
            )
        return {**serialize_consent(row), "duplicate": False}

    async def withdraw(self, consent_id: UUID, *, reason: str) -> dict[str, Any]:
        from sqlalchemy import select, text, update

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.audit import ConsentRecord
        from infrastructure.database.models.communications import Conversation, Message
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        moment = utcnow()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            grant = (
                await uow.session.execute(
                    select(ConsentRecord).where(ConsentRecord.id == consent_id).with_for_update()
                )
            ).scalar_one_or_none()
            if grant is None or grant.status != "granted":
                raise NotFound("Consent grant not found.")
            if grant.subject_id is None:
                raise ValidationError("This consent record has no supported subject.")
            await self._subject_identifier(grant.subject_type, grant.subject_id, "web_chat")
            await uow.session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"consent-withdraw:{self.tenant_id}:{consent_id}"},
            )
            existing = (
                await uow.session.execute(
                    select(ConsentRecord).where(ConsentRecord.withdraws_id == consent_id).limit(1)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return {**serialize_consent(existing), "duplicate": True, "cancelled_messages": 0}

            record_id = uuid7()
            row = ConsentRecord(
                id=record_id,
                tenant_id=self.tenant_id,
                subject_type=grant.subject_type,
                subject_id=grant.subject_id,
                subject_identifier=grant.subject_identifier,
                consent_type=grant.consent_type,
                channel=grant.channel,
                status="withdrawn",
                evidence={"reason": reason[:500]},
                policy_version=grant.policy_version,
                source="api",
                withdraws_id=grant.id,
                created_at=moment,
                created_by=self.user_id,
            )
            uow.session.add(row)
            cancelled = 0
            if grant.subject_type == "contact" and grant.subject_id:
                result = await uow.session.execute(
                    update(Message)
                    .where(
                        Message.conversation_id.in_(
                            select(Conversation.id).where(
                                Conversation.contact_id == grant.subject_id
                            )
                        ),
                        Message.direction == "outbound",
                        Message.status.in_(("pending", "queued")),
                        Message.channel == grant.channel,
                    )
                    .values(status="failed", failure_reason="Consent withdrawn before delivery")
                )
                cancelled = int(getattr(result, "rowcount", 0) or 0)
            AuditRecorder(uow.session).record(
                action="consent.revoked",
                resource_type="consent",
                resource_id=record_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values={"status": "granted"},
                new_values={"status": "withdrawn", "cancelled_messages": cancelled},
            )
            uow.collect(
                DomainEvent(
                    event_type=CONSENT_REVOKED,
                    tenant_id=self.tenant_id,
                    resource_type="consent",
                    resource_id=record_id,
                    actor_id=self.user_id,
                    payload={
                        "subject_type": grant.subject_type,
                        "subject_id": str(grant.subject_id),
                        "consent_type": grant.consent_type,
                        "channel": grant.channel,
                        "cancelled_messages": cancelled,
                    },
                )
            )
        return {**serialize_consent(row), "duplicate": False, "cancelled_messages": cancelled}
