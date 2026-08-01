"""`analytics` schema: materialized rollups refreshed without blocking reads."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import (
    Date,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import (
    SCHEMA_ANALYTICS,
    Base,
    IdMixin,
    TimestampMixin,
    register_tenant_table,
)


class DailyLeadRollup(IdMixin, TimestampMixin, Base):
    __tablename__ = "daily_lead_rollups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", "source", name="tenant_day_source"),
        {"schema": SCHEMA_ANALYTICS},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False, default="all")
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    qualified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    contacted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    converted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disqualified_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hot_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warm_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cold_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_first_response_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)


class DailyRevenueRollup(IdMixin, TimestampMixin, Base):
    __tablename__ = "daily_revenue_rollups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", name="tenant_day"),
        {"schema": SCHEMA_ANALYTICS},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    deals_won: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deals_lost: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    won_amount_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    pipeline_amount_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    payments_captured_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    refunds_minor: Mapped[int] = mapped_column(nullable=False, default=0)


class DailyConversationRollup(IdMixin, TimestampMixin, Base):
    __tablename__ = "daily_conversation_rollups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", "channel", name="tenant_day_channel"),
        {"schema": SCHEMA_ANALYTICS},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    inbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    outbound_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    handoff_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    opt_out_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class TenantHealthRollup(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenant_health_rollups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "day", name="health_tenant_day"),
        {"schema": SCHEMA_ANALYTICS},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    active_users: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ai_tokens: Mapped[int] = mapped_column(nullable=False, default=0)
    ai_cost_micro_inr: Mapped[int] = mapped_column(nullable=False, default=0)
    storage_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    workflow_executions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


for _t in (
    "daily_lead_rollups",
    "daily_revenue_rollups",
    "daily_conversation_rollups",
    "tenant_health_rollups",
):
    register_tenant_table(_t)
