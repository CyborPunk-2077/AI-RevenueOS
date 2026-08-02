"""Workflow definitions, immutable versions, executions, approvals and DLQ."""

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

EXECUTION_STATES = ("pending", "running", "waiting", "completed", "failed", "cancelled")
NODE_STATES = ("pending", "running", "retrying", "completed", "failed", "skipped")
APPROVAL_STATES = ("requested", "approved", "rejected", "escalated", "recalled")


class WorkflowDefinition(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "workflow_definitions"
    __table_args__ = (
        CheckConstraint(
            "category IN ('lead_nurture','deal_automation','notification','approval','custom')",
            name="category_valid",
        ),
        UniqueConstraint("tenant_id", "name", name="workflow_tenant_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(30), nullable=False, default="custom")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kill_switch: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active_window: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    global_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="builder")


class WorkflowVersion(IdMixin, TimestampMixin, ActorMixin, Base):
    """Immutable. Executions pin a version id and its content hash."""

    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="workflow_version"),
        Index("ix_workflow_versions_hash", "tenant_id", "content_hash"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_version_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validation_report: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class WorkflowExecution(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(f"state IN {EXECUTION_STATES}", name="state_valid"),
        UniqueConstraint("tenant_id", "idempotency_key", name="tenant_idem"),
        Index("ix_wf_exec_tenant_state_created", "tenant_id", "state", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(60), nullable=False)
    trigger_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    trigger_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    idempotency_key: Mapped[str] = mapped_column(String(250), nullable=False)
    concurrency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resume_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    error: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    replay_of_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class WorkflowNodeExecution(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_node_executions"
    __table_args__ = (
        CheckConstraint(f"state IN {NODE_STATES}", name="state_valid"),
        UniqueConstraint("execution_id", "node_id", "attempt", name="exec_node_attempt"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    action_idempotency_key: Mapped[str | None] = mapped_column(
        String(250), nullable=True, index=True
    )
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class WorkflowApproval(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_approvals"
    __table_args__ = (
        CheckConstraint(f"state IN {APPROVAL_STATES}", name="state_valid"),
        UniqueConstraint("execution_id", "node_id", name="execution_node_approval"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    execution_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(120), nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    strategy: Mapped[str] = mapped_column(String(20), nullable=False, default="any")
    quorum: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    assignees: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    decisions: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timeout_path: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowSchedule(IdMixin, TimestampMixin, Base):
    __tablename__ = "workflow_schedules"
    __table_args__ = (
        Index("ix_wf_schedule_next", "next_run_at", postgresql_where="is_active"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    workflow_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False, default="cron")
    cron_expression: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InboundWebhookConfig(IdMixin, TimestampMixin, Base):
    __tablename__ = "inbound_webhook_configs"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    workflow_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    signing_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    payload_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    ip_allowlist: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OutboundWebhookConfig(IdMixin, TimestampMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "outbound_webhook_configs"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    event_types: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    signing_secret_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboundWebhookDelivery(IdMixin, TimestampMixin, Base):
    __tablename__ = "outbound_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("config_id", "idempotency_key", name="config_idem"),
        Index("ix_owd_pending", "next_attempt_at", postgresql_where="status = 'pending'"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    config_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    event_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(250), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeadLetter(IdMixin, TimestampMixin, Base):
    __tablename__ = "dead_letters"
    __table_args__ = (
        Index("ix_dead_letters_tenant_created", "tenant_id", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    queue: Mapped[str] = mapped_column(String(60), nullable=False)
    task_name: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


for _t in (
    "workflow_definitions",
    "workflow_versions",
    "workflow_executions",
    "workflow_node_executions",
    "workflow_approvals",
    "workflow_schedules",
    "inbound_webhook_configs",
    "outbound_webhook_configs",
    "outbound_webhook_deliveries",
    "dead_letters",
):
    register_tenant_table(_t)
