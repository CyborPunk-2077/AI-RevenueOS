"""Prompt registry, usage metering, evaluation sets and safe conversation summaries."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
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
    TimestampMixin,
    register_tenant_table,
)

PROMPT_STATUSES = ("draft", "staging", "production", "deprecated")


class Prompt(IdMixin, TimestampMixin, ActorMixin, Base):
    """Git-backed prompts mirrored here for audit. One production version per task."""

    __tablename__ = "prompts"
    __table_args__ = (
        CheckConstraint(f"status IN {PROMPT_STATUSES}", name="status_valid"),
        UniqueConstraint("task", "version", name="task_version"),
        Index(
            "uq_prompts_one_production",
            "task",
            unique=True,
            postgresql_where="status = 'production'",
        ),
        {"schema": SCHEMA_APP},
    )

    task: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    template: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    response_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    examples: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    model_config_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    promoted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    promoted_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    rollback_target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluation_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class AiUsageRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_usage_records"
    __table_args__ = (
        Index("ix_ai_usage_tenant_date", "tenant_id", "usage_date"),
        Index("ix_ai_usage_tenant_task", "tenant_id", "task"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(120), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_micro_inr: Mapped[int] = mapped_column(nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, default="success")
    degraded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    fallback_from: Mapped[str | None] = mapped_column(String(120), nullable=True)
    usage_date: Mapped[date] = mapped_column(Date, nullable=False)


class AiEvaluationSet(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_evaluation_sets"
    __table_args__ = (
        UniqueConstraint("task", "name", "version", name="task_name_version"),
        {"schema": SCHEMA_APP},
    )

    task: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cases: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    metric: Mapped[str] = mapped_column(String(40), nullable=False, default="f1")
    threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.85)


class AiEvaluationRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "ai_evaluation_runs"
    __table_args__ = ({"schema": SCHEMA_APP},)

    evaluation_set_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True
    )
    prompt_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    model: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    baseline_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    results: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")


class AiConversationSummary(IdMixin, TimestampMixin, Base):
    """Minimised, redacted summary retained after the 20-turn Redis window expires."""

    __tablename__ = "ai_conversation_summaries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "session_key", name="tenant_session"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    session_key: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AiReviewItem(IdMixin, TimestampMixin, Base):
    """Human accept/edit/reject/defer state for any AI output that touches business data."""

    __tablename__ = "ai_review_items"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','accepted','edited','rejected','deferred')", name="state_valid"
        ),
        Index(
            "ix_ai_review_pending", "tenant_id", "created_at", postgresql_where="state = 'pending'"
        ),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    task: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    proposal: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    evidence: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    provenance: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    decided_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    final_value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


for _t in ("ai_usage_records", "ai_conversation_summaries", "ai_review_items"):
    register_tenant_table(_t)
