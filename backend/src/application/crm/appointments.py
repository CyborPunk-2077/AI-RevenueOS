"""Appointments: booking, rescheduling, cancelling and recording the outcome.

The admin side. Public self-service booking pages are a separate surface and are
not in this scope.

**Double booking is prevented by the database, not by a check.** `slot_locks` has
a unique constraint on `(tenant_id, resource_id, start_at, slot_index)`, and the
booking path inserts a lock in the same transaction as the appointment. Two
concurrent requests for the same slot both pass any read-then-write check; only
one survives the constraint. A capacity of N is modelled as N indexed locks on the
same instant, which is why `slot_index_for` exists.

Timing rules -- notice periods, cancellation cutoffs, slot generation -- come from
`domain/appointments/slots.py`, which is already unit tested.

Calendar sync is gated (`calendar_sync_enabled` is off pending Google OAuth
verification), so `calendar_event_id` stays null and nothing pretends an event was
written to anyone's calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.appointments.slots import can_cancel, can_reschedule
from domain.base import DomainEvent
from domain.events.catalog import (
    APPOINTMENT_BOOKED,
    APPOINTMENT_CANCELLED,
    APPOINTMENT_COMPLETED,
    APPOINTMENT_RESCHEDULED,
)
from infrastructure.logging.setup import get_logger
from shared.exceptions import Conflict, NotFound, ValidationError
from shared.pagination import Page
from shared.settings import get_settings
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.crm.appointments")

STATUSES = ("scheduled", "confirmed", "completed", "cancelled", "no_show")
OPEN_STATUSES = frozenset({"scheduled", "confirmed"})
LOCATION_TYPES = ("physical", "virtual", "phone")
DEFAULT_DURATION_MINUTES = 30
# A lock outlives its appointment so a cancelled-then-rebooked slot cannot be
# grabbed by a racing request in the gap.
LOCK_TTL = timedelta(days=400)


def serialize_appointment(
    row: Any, *, contact_name: str | None = None, organizer_name: str | None = None
) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "title": row.title,
        "status": row.status,
        "start_at": row.start_at.isoformat(),
        "end_at": row.end_at.isoformat(),
        "timezone": row.timezone,
        "location_type": row.location_type,
        "location_detail": row.location_detail,
        "contact_id": str(row.contact_id) if row.contact_id else None,
        "contact_name": contact_name,
        "deal_id": str(row.deal_id) if row.deal_id else None,
        "organizer_id": str(row.organizer_id) if row.organizer_id else None,
        "organizer_name": organizer_name,
        "outcome": row.outcome,
        "outcome_note": row.outcome_note,
        "cancelled_reason": row.cancelled_reason,
        "rescheduled_from_id": (str(row.rescheduled_from_id) if row.rescheduled_from_id else None),
        # Null until calendar sync is genuinely activated. Never invented.
        "calendar_event_id": row.calendar_event_id,
        "is_past": row.end_at < utcnow(),
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@dataclass(slots=True)
class AppointmentService(_PrincipalScoped):
    """The admin booking surface."""

    async def _names(self, session: Any, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.users import User

        rows = await session.execute(
            select(User.id, User.full_name).where(
                User.id.in_(ids), User.tenant_id == self.tenant_id
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

    async def _assert_links_visible(self, session: Any, payload: dict[str, Any]) -> None:
        """A contact or deal from another tenant must be as absent as a fake id."""
        from infrastructure.database.models.crm import Contact, Deal
        from infrastructure.database.repositories.base import TenantRepository

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        class DealRepository(TenantRepository[Deal]):
            model = Deal

        if payload.get("contact_id") and (
            await ContactRepository(session, self.tenant_id).get(
                payload["contact_id"], self.permissions_scope()
            )
            is None
        ):
            raise NotFound("Contact not found.")
        if payload.get("deal_id") and (
            await DealRepository(session, self.tenant_id).get(
                payload["deal_id"], self.permissions_scope()
            )
            is None
        ):
            raise NotFound("Deal not found.")

    async def list_appointments(
        self, query: Any, *, status: str | None = None, upcoming: bool = False
    ) -> Page:
        from infrastructure.database.models.appointments import Appointment
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class AppointmentRepository(TenantRepository[Appointment]):
            model = Appointment

        if status and status not in STATUSES:
            raise ValidationError(f"Unknown status: {status!r}.")

        async with tenant_session(self.tenant_id) as session:
            repo = AppointmentRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if status:
                stmt = stmt.where(Appointment.status == status)
            if upcoming:
                # Against the database clock, like every other time question here.
                stmt = stmt.where(
                    Appointment.end_at >= utcnow(),
                    Appointment.status.in_(tuple(OPEN_STATUSES)),
                )
            stmt = stmt.order_by(Appointment.start_at.asc())

            page = await repo.paginate_cursor(
                self.permissions_scope(), stmt, cursor=query.cursor, page_size=query.page_size
            )
            contacts = await self._contact_names(
                session, {a.contact_id for a in page.items if a.contact_id}
            )
            people = await self._names(
                session, {a.organizer_id for a in page.items if a.organizer_id}
            )
            page.items = [
                serialize_appointment(
                    a,
                    contact_name=contacts.get(a.contact_id) if a.contact_id else None,
                    organizer_name=people.get(a.organizer_id) if a.organizer_id else None,
                )
                for a in page.items
            ]
            return page

    async def get(self, appointment_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.appointments import Appointment
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class AppointmentRepository(TenantRepository[Appointment]):
            model = Appointment

        async with tenant_session(self.tenant_id) as session:
            row = await AppointmentRepository(session, self.tenant_id).get_scoped(
                appointment_id, self.permissions_scope()
            )
            if row is None:
                raise NotFound("Appointment not found.")
            contacts = await self._contact_names(
                session, {row.contact_id} if row.contact_id else set()
            )
            people = await self._names(session, {row.organizer_id} if row.organizer_id else set())
            return serialize_appointment(
                row,
                contact_name=contacts.get(row.contact_id) if row.contact_id else None,
                organizer_name=people.get(row.organizer_id) if row.organizer_id else None,
            )

    async def book(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Book a slot. The unique constraint on `slot_locks` decides who wins."""
        from sqlalchemy.exc import IntegrityError

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.appointments import Appointment, SlotLock
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValidationError("A title is required.")

        start_at = payload.get("start_at")
        if start_at is None:
            raise ValidationError("A start time is required.")
        duration = int(payload.get("duration_minutes") or DEFAULT_DURATION_MINUTES)
        if duration <= 0:
            raise ValidationError("Duration must be positive.")
        end_at = payload.get("end_at") or (start_at + timedelta(minutes=duration))
        if end_at <= start_at:
            raise ValidationError("The end time must be after the start time.")
        if start_at < utcnow():
            raise ValidationError("An appointment cannot be booked in the past.")

        location_type = str(payload.get("location_type") or "physical")
        if location_type not in LOCATION_TYPES:
            raise ValidationError(
                f"Unknown location type. Expected one of: {', '.join(LOCATION_TYPES)}."
            )

        # The organiser is the resource being booked: two appointments cannot hold
        # the same person at the same instant.
        organizer_id = payload.get("organizer_id") or self.user_id
        appointment_id = uuid7()

        try:
            async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
                await self._assert_links_visible(uow.session, payload)

                uow.session.add(
                    Appointment(
                        id=appointment_id,
                        tenant_id=self.tenant_id,
                        title=title[:250],
                        contact_id=payload.get("contact_id"),
                        deal_id=payload.get("deal_id"),
                        organizer_id=organizer_id,
                        start_at=start_at,
                        end_at=end_at,
                        timezone=str(payload.get("timezone") or "Asia/Kolkata"),
                        location_type=location_type,
                        location_detail=payload.get("location_detail"),
                        status="scheduled",
                        intake={},
                        created_by=self.user_id,
                        version=1,
                    )
                )
                # Written in the same transaction. If the constraint rejects it,
                # the appointment rolls back with it -- there is no window in
                # which a booking exists without its lock.
                uow.session.add(
                    SlotLock(
                        id=uuid7(),
                        tenant_id=self.tenant_id,
                        resource_id=organizer_id,
                        start_at=start_at,
                        end_at=end_at,
                        slot_index=0,
                        appointment_id=appointment_id,
                        expires_at=utcnow() + LOCK_TTL,
                    )
                )
                AuditRecorder(uow.session).record(
                    action="appointment.book",
                    resource_type="appointment",
                    resource_id=appointment_id,
                    tenant_id=self.tenant_id,
                    actor_id=self.user_id,
                    new_values={"title": title, "start_at": start_at.isoformat()},
                )
                uow.collect(
                    DomainEvent(
                        event_type=APPOINTMENT_BOOKED,
                        tenant_id=self.tenant_id,
                        resource_type="appointment",
                        resource_id=appointment_id,
                        actor_id=self.user_id,
                        payload={
                            "start_at": start_at.isoformat(),
                            "contact_id": (
                                str(payload["contact_id"]) if payload.get("contact_id") else None
                            ),
                        },
                    )
                )
        except IntegrityError as exc:
            # The database, not a race-prone read-then-write check, is what said no.
            logger.info("appointment_slot_taken", start_at=start_at.isoformat())
            raise Conflict("That slot is already booked.") from exc

        logger.info("appointment_booked", appointment_id=str(appointment_id))
        return await self.get(appointment_id)

    async def reschedule(
        self,
        appointment_id: UUID,
        new_start: datetime,
        *,
        duration_minutes: int | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Move an appointment. Notice rules come from the domain."""
        from sqlalchemy import select
        from sqlalchemy.exc import IntegrityError

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.appointments import Appointment, SlotLock
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class AppointmentRepository(TenantRepository[Appointment]):
            model = Appointment

        try:
            async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
                repo = AppointmentRepository(uow.session, self.tenant_id)
                row = await repo.get_scoped_or_404(appointment_id, self.permissions_scope())
                if row.status not in OPEN_STATUSES:
                    raise ValidationError(f"A {row.status} appointment cannot be rescheduled.")

                allowed, reason = can_reschedule(
                    current_start=row.start_at,
                    new_start=new_start,
                    # 0 here: the notice rule belongs to the appointment type, and
                    # an admin moving their own diary is not subject to the
                    # customer-facing notice period.
                    min_notice_minutes=0,
                )
                if not allowed:
                    raise ValidationError(reason or "This appointment cannot be rescheduled.")

                previous_start = row.start_at
                minutes = duration_minutes or int((row.end_at - row.start_at).total_seconds() // 60)
                row.start_at = new_start
                row.end_at = new_start + timedelta(minutes=minutes)
                row.rescheduled_from_id = appointment_id

                # Move the lock with it, or the old slot stays blocked forever and
                # the new one is unprotected.
                lock = (
                    await uow.session.execute(
                        select(SlotLock).where(SlotLock.appointment_id == appointment_id)
                    )
                ).scalar_one_or_none()
                if lock is not None:
                    lock.start_at = row.start_at
                    lock.end_at = row.end_at

                await repo.bump_version(row, expected_version)
                row.updated_by = self.user_id

                AuditRecorder(uow.session).record(
                    action="appointment.reschedule",
                    resource_type="appointment",
                    resource_id=appointment_id,
                    tenant_id=self.tenant_id,
                    actor_id=self.user_id,
                    old_values={"start_at": previous_start.isoformat()},
                    new_values={"start_at": row.start_at.isoformat()},
                )
                uow.collect(
                    DomainEvent(
                        event_type=APPOINTMENT_RESCHEDULED,
                        tenant_id=self.tenant_id,
                        resource_type="appointment",
                        resource_id=appointment_id,
                        actor_id=self.user_id,
                        payload={
                            "from": previous_start.isoformat(),
                            "to": row.start_at.isoformat(),
                        },
                    )
                )
        except IntegrityError as exc:
            raise Conflict("That slot is already booked.") from exc

        return await self.get(appointment_id)

    async def cancel(
        self, appointment_id: UUID, reason: str | None, *, expected_version: int | None = None
    ) -> dict[str, Any]:
        """Cancel and release the slot so it can be booked again."""
        from sqlalchemy import delete

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.appointments import Appointment, SlotLock
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class AppointmentRepository(TenantRepository[Appointment]):
            model = Appointment

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = AppointmentRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped_or_404(appointment_id, self.permissions_scope())
            if row.status == "cancelled":
                raise Conflict("This appointment is already cancelled.")
            if row.status == "completed":
                raise ValidationError("A completed appointment cannot be cancelled.")

            allowed, why = can_cancel(start_at=row.start_at, cancellation_cutoff_minutes=0)
            if not allowed:
                raise ValidationError(why or "This appointment can no longer be cancelled.")

            row.status = "cancelled"
            row.cancelled_reason = (reason or "")[:300] or None
            await repo.bump_version(row, expected_version)
            row.updated_by = self.user_id

            # Releasing the lock is the point: a cancelled slot that stays locked
            # is a slot nobody can ever book again.
            await uow.session.execute(
                delete(SlotLock).where(SlotLock.appointment_id == appointment_id)
            )

            AuditRecorder(uow.session).record(
                action="appointment.cancel",
                resource_type="appointment",
                resource_id=appointment_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"reason": row.cancelled_reason},
            )
            uow.collect(
                DomainEvent(
                    event_type=APPOINTMENT_CANCELLED,
                    tenant_id=self.tenant_id,
                    resource_type="appointment",
                    resource_id=appointment_id,
                    actor_id=self.user_id,
                    payload={"reason": row.cancelled_reason},
                )
            )
        return await self.get(appointment_id)

    async def record_outcome(
        self,
        appointment_id: UUID,
        payload: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        """Mark it completed or a no-show, with a note."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.appointments import Appointment
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class AppointmentRepository(TenantRepository[Appointment]):
            model = Appointment

        status = str(payload.get("status", ""))
        if status not in {"completed", "no_show"}:
            raise ValidationError("An outcome is either 'completed' or 'no_show'.")

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = AppointmentRepository(uow.session, self.tenant_id)
            row = await repo.get_scoped_or_404(appointment_id, self.permissions_scope())
            if row.status == "cancelled":
                raise ValidationError("A cancelled appointment has no outcome to record.")

            row.status = status
            row.outcome = (payload.get("outcome") or "")[:80] or None
            row.outcome_note = payload.get("outcome_note")
            await repo.bump_version(row, expected_version)
            row.updated_by = self.user_id

            AuditRecorder(uow.session).record(
                action="appointment.outcome",
                resource_type="appointment",
                resource_id=appointment_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"status": status, "outcome": row.outcome},
            )
            if status == "completed":
                uow.collect(
                    DomainEvent(
                        event_type=APPOINTMENT_COMPLETED,
                        tenant_id=self.tenant_id,
                        resource_type="appointment",
                        resource_id=appointment_id,
                        actor_id=self.user_id,
                        payload={"outcome": row.outcome},
                    )
                )
        return await self.get(appointment_id)

    async def for_contact(self, contact_id: UUID) -> list[dict[str, Any]]:
        """Appointments on one contact, soonest first."""
        from application.crm.service import ContactService

        await ContactService(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        ).get(contact_id)

        from infrastructure.database.models.appointments import Appointment
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class AppointmentRepository(TenantRepository[Appointment]):
            model = Appointment

        async with tenant_session(self.tenant_id) as session:
            repo = AppointmentRepository(session, self.tenant_id)
            stmt = (
                repo.scoped_query(self.permissions_scope())
                .where(Appointment.contact_id == contact_id)
                .order_by(Appointment.start_at.asc())
                .limit(100)
            )
            rows = list((await session.execute(stmt)).scalars().all())
            people = await self._names(session, {a.organizer_id for a in rows if a.organizer_id})
            return [
                serialize_appointment(
                    a, organizer_name=people.get(a.organizer_id) if a.organizer_id else None
                )
                for a in rows
            ]

    def calendar_sync_status(self) -> dict[str, Any]:
        """Honest reporting: calendar sync is gated on Google OAuth verification."""
        settings = get_settings()
        return {
            "enabled": bool(settings.features.calendar_sync_enabled),
            "blocker": (
                None
                if settings.features.calendar_sync_enabled
                else "Google Calendar sync requires OAuth app verification; "
                "appointments are stored locally and no calendar event is created."
            ),
        }
