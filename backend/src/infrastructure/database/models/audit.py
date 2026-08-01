"""`audit` schema: immutable audit log, consent ledger and the transactional outbox."""

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
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import SCHEMA_AUDIT, Base, IdMixin, register_tenant_table
from shared.utils.ids import uuid7


class AuditLog(Base):
    """Monthly-partitioned, append-only. Reconstructs actor/action/context."""

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_audit_logs_resource", "tenant_id", "resource_type", "resource_id"),
        Index("ix_audit_logs_correlation", "correlation_id"),
        {"schema": SCHEMA_AUDIT, "postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    actor_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    old_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


CONSENT_TYPES = ("marketing", "communication", "data_processing", "whatsapp_optin")
CONSENT_STATUSES = ("granted", "denied", "withdrawn", "expired")


class ConsentRecord(IdMixin, Base):
    """Immutable ledger. A withdrawal is a new row that references the grant."""

    __tablename__ = "consent_records"
    __table_args__ = (
        CheckConstraint(f"consent_type IN {CONSENT_TYPES}", name="type_valid"),
        CheckConstraint(f"status IN {CONSENT_STATUSES}", name="status_valid"),
        Index("ix_consent_subject", "tenant_id", "subject_type", "subject_id", "consent_type"),
        Index("ix_consent_identifier", "tenant_id", "subject_identifier"),
        {"schema": SCHEMA_AUDIT},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    subject_identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    consent_type: Mapped[str] = mapped_column(String(30), nullable=False)
    channel: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    policy_version: Mapped[str] = mapped_column(String(30), nullable=False, default="1.0")
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="api")
    withdraws_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class EventOutbox(Base):
    """Daily-partitioned. Committed in the same transaction as the state change."""

    __tablename__ = "event_outbox"
    __table_args__ = (
        Index(
            "ix_outbox_unprocessed",
            "occurred_at",
            postgresql_where="processed_at IS NULL",
        ),
        Index("ix_outbox_tenant_type", "tenant_id", "event_type"),
        UniqueConstraint("event_id", "occurred_at", name="event_id_time"),
        {"schema": SCHEMA_AUDIT, "postgresql_partition_by": "RANGE (occurred_at)"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    resource_type: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    resource_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PrivacyRequest(IdMixin, Base):
    __tablename__ = "privacy_requests"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('access','export','delete','correction','objection')",
            name="type_valid",
        ),
        {"schema": SCHEMA_AUDIT},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    subject_identifier: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    subject_type: Mapped[str] = mapped_column(String(30), nullable=False, default="contact")
    request_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="received")
    verification: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    result_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    requested_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class IdempotencyRecord(IdMixin, Base):
    """24 hour retention for externally repeatable creates."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope", "idempotency_key", name="tenant_scope_key"),
        {"schema": SCHEMA_AUDIT},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    scope: Mapped[str] = mapped_column(String(120), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="in_progress")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


# `event_outbox` and `idempotency_records` are deliberately platform-scoped:
# the poller and reaper must observe every tenant. Both are unreachable from a
# tenant API surface. `audit_logs` is tenant data and is RLS protected.
for _t in ("consent_records", "privacy_requests", "audit_logs"):
    register_tenant_table(_t)
