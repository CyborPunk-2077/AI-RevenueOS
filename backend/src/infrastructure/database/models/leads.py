"""Lead capture, source attribution, dedupe and qualification."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
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

LEAD_STATUSES = (
    "new",
    "qualified",
    "contacted",
    "nurturing",
    "converted",
    "disqualified",
    "archived",
)
LEAD_CATEGORIES = ("hot", "warm", "cold")


class Form(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "forms"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    form_type: Mapped[str] = mapped_column(String(20), nullable=False, default="embedded")
    schema_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True)
    allowed_origins: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LeadSourceEvent(IdMixin, TimestampMixin, Base):
    """Raw capture is preserved even when the lead is treated as a duplicate."""

    __tablename__ = "lead_source_events"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source", "source_idempotency_key", name="source_idem"),
        Index("ix_lead_source_events_tenant_created", "tenant_id", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    source_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    source_idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    normalized: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    utm: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    form_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    lead_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    duplicate_of_lead_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class Lead(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(f"status IN {LEAD_STATUSES}", name="status_valid"),
        CheckConstraint(
            "qualification_score IS NULL OR qualification_score BETWEEN 0 AND 100",
            name="score_range",
        ),
        Index("ix_leads_tenant_status_created", "tenant_id", "status", "created_at"),
        Index("ix_leads_tenant_assignee", "tenant_id", "assignee_id"),
        Index("ix_leads_dedupe", "tenant_id", "dedupe_key"),
        Index("ix_leads_capture", "capture", postgresql_using="gin"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    last_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="manual")
    source_channel: Mapped[str | None] = mapped_column(String(50), nullable=True)
    capture: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    utm: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    qualification_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    category: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reasoning: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    qualified_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewer_state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    reviewed_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    disqualify_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    team_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    converted_contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    converted_deal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    converted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    merged_into_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    first_response_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LeadEnrichment(IdMixin, TimestampMixin, Base):
    __tablename__ = "lead_enrichments"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    lead_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(60), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    extracted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")


class LeadDuplicateCandidate(IdMixin, TimestampMixin, Base):
    __tablename__ = "lead_duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "lead_id", "candidate_lead_id", name="lead_candidate"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    lead_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    candidate_lead_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    match_reason: Mapped[str] = mapped_column(String(60), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    resolution: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    resolved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class AssignmentRule(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "assignment_rules"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, default="lead")
    strategy: Mapped[str] = mapped_column(String(30), nullable=False, default="round_robin")
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    targets: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    cursor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


for _t in (
    "forms",
    "lead_source_events",
    "leads",
    "lead_enrichments",
    "lead_duplicate_candidates",
    "assignment_rules",
):
    register_tenant_table(_t)
