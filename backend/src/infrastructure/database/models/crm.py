"""Canonical customer model: contact with optional account, plus pipelines and deals."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
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

ACTIVITY_TYPES = (
    "note",
    "call",
    "email",
    "meeting",
    "task",
    "status_change",
    "whatsapp",
    "system",
)
DEAL_STATUSES = ("open", "won", "lost", "abandoned")


class Contact(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (
        CheckConstraint("email IS NOT NULL OR phone IS NOT NULL", name="email_or_phone"),
        Index(
            "uq_contacts_tenant_email_active",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where="deleted_at IS NULL AND email IS NOT NULL",
        ),
        Index("ix_contacts_tenant_phone", "tenant_id", "phone"),
        Index("ix_contacts_tenant_assignee", "tenant_id", "assignee_id"),
        Index("ix_contacts_custom_fields", "custom_fields", postgresql_using="gin"),
        Index("ix_contacts_tenant_created", "tenant_id", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str | None] = mapped_column(String(150), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active")
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    tags: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    account_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    team_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    last_contact_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_into_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Account(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "accounts"
    __table_args__ = (
        Index(
            "uq_accounts_tenant_name_active",
            "tenant_id",
            "name",
            unique=True,
            postgresql_where="deleted_at IS NULL",
        ),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    owner_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    annual_revenue_minor: Mapped[int | None] = mapped_column(nullable=True)
    employee_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class AccountContact(IdMixin, TimestampMixin, Base):
    __tablename__ = "account_contacts"
    __table_args__ = (
        UniqueConstraint("account_id", "contact_id", name="account_contact"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    account_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    contact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    role: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Pipeline(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "pipelines"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="pipeline_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, default="deal")
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Stage(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "stages"
    __table_args__ = (
        UniqueConstraint("pipeline_id", "name", name="pipeline_name"),
        Index("ix_stages_pipeline_position", "pipeline_id", "position"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    pipeline_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.pipelines.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    probability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    required_fields: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    transition_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_won: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_lost: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Deal(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "deals"
    __table_args__ = (
        CheckConstraint(f"status IN {DEAL_STATUSES}", name="status_valid"),
        CheckConstraint("amount_minor >= 0", name="amount_non_negative"),
        CheckConstraint("probability BETWEEN 0 AND 100", name="probability_range"),
        Index("ix_deals_tenant_stage", "tenant_id", "stage_id"),
        Index("ix_deals_tenant_assignee_status", "tenant_id", "assignee_id", "status"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    account_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    pipeline_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    stage_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    amount_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    probability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    loss_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    expected_close_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    team_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    custom_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source_lead_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Activity(IdMixin, TimestampMixin, Base):
    """Append-only. Generated by mutations and never editable."""

    __tablename__ = "activities"
    __table_args__ = (
        CheckConstraint(f"activity_type IN {ACTIVITY_TYPES}", name="type_valid"),
        Index("ix_activities_entity", "tenant_id", "entity_type", "entity_id", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    activity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject: Mapped[str] = mapped_column(String(300), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Task(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('open','in_progress','completed','cancelled')", name="status_valid"
        ),
        Index("ix_tasks_tenant_assignee_due", "tenant_id", "assignee_id", "due_at"),
        Index("ix_tasks_open_due", "tenant_id", "due_at", postgresql_where="status = 'open'"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_next_action: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")


class SlaRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "sla_records"
    __table_args__ = (
        Index("ix_sla_due", "tenant_id", "due_at", postgresql_where="resolved_at IS NULL"),
        UniqueConstraint("tenant_id", "entity_type", "entity_id", "policy", name="entity_policy"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    policy: Mapped[str] = mapped_column(String(60), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    breached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    team_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Note(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "notes"
    __table_args__ = (
        Index("ix_notes_entity", "tenant_id", "entity_type", "entity_id"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Tag(IdMixin, TimestampMixin, Base):
    __tablename__ = "tags"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="tag_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)


class CustomFieldDefinition(IdMixin, TimestampMixin, VersionMixin, Base):
    """Field key is unique per entity; type is immutable after creation."""

    __tablename__ = "custom_field_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "entity_type", "field_key", name="entity_field"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    field_key: Mapped[str] = mapped_column(String(80), nullable=False)
    label: Mapped[str] = mapped_column(String(150), nullable=False)
    field_type: Mapped[str] = mapped_column(String(30), nullable=False)
    options: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    classification: Mapped[str] = mapped_column(String(4), nullable=False, default="P1")
    access_roles: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SavedView(IdMixin, TimestampMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "saved_views"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    columns: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    sort: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    owner_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


for _t in (
    "contacts",
    "accounts",
    "account_contacts",
    "pipelines",
    "stages",
    "deals",
    "activities",
    "tasks",
    "sla_records",
    "notes",
    "tags",
    "custom_field_definitions",
    "saved_views",
):
    register_tenant_table(_t)
