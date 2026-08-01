"""Appointment types, availability, resources and concurrency-safe slot locks."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import (
    SCHEMA_APP,
    ActorMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
    register_tenant_table,
)

APPOINTMENT_STATUSES = ("scheduled", "confirmed", "completed", "cancelled", "no_show")


class AppointmentType(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "appointment_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="appointment_type_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    buffer_before_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    buffer_after_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    location_type: Mapped[str] = mapped_column(String(20), nullable=False, default="physical")
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_notice_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    max_advance_days: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    reminder_offsets_minutes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    intake_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class BookingResource(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "booking_resources"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="resource_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(30), nullable=False, default="staff")
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class AvailabilityRule(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "availability_rules"
    __table_args__ = (
        CheckConstraint("day_of_week BETWEEN 0 AND 6", name="dow_range"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    start_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    end_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AvailabilityException(IdMixin, TimestampMixin, Base):
    __tablename__ = "availability_exceptions"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    resource_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, index=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_holiday: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Appointment(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("end_at > start_at", name="end_after_start"),
        CheckConstraint(f"status IN {APPOINTMENT_STATUSES}", name="status_valid"),
        Index("ix_appointments_tenant_start", "tenant_id", "start_at"),
        Index("ix_appointments_resource_start", "tenant_id", "resource_id", "start_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    appointment_type_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    lead_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    deal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    organizer_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    location_type: Mapped[str] = mapped_column(String(20), nullable=False, default="physical")
    location_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="scheduled")
    outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    outcome_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    calendar_event_id: Mapped[str | None] = mapped_column(String(250), nullable=True)
    booking_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    intake: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    cancelled_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    rescheduled_from_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class SlotLock(IdMixin, TimestampMixin, Base):
    """Database-level uniqueness is what actually prevents double booking."""

    __tablename__ = "slot_locks"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "resource_id", "start_at", "slot_index", name="resource_slot"
        ),
        Index("ix_slot_locks_expiry", "expires_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    resource_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    slot_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    appointment_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AppointmentReminder(IdMixin, TimestampMixin, Base):
    __tablename__ = "appointment_reminders"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "appointment_id", "offset_minutes", "channel", name="appt_offset"
        ),
        Index("ix_reminders_due", "tenant_id", "send_at", postgresql_where="sent_at IS NULL"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    appointment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    offset_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    skip_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)


for _t in (
    "appointment_types",
    "booking_resources",
    "availability_rules",
    "availability_exceptions",
    "appointments",
    "slot_locks",
    "appointment_reminders",
):
    register_tenant_table(_t)
