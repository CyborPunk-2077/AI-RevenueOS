"""Tenancy, subscription, entitlement and feature-override tables."""

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import (
    SCHEMA_APP,
    SCHEMA_PUBLIC,
    ActorMixin,
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
    register_tenant_table,
)

TENANT_STATUSES = ("trial", "active", "suspended", "deleted")


class Tenant(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    """The tenant row itself lives in `app` but is not RLS-filtered by tenant_id;
    access is gated by authenticated membership resolution instead."""

    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(f"status IN {TENANT_STATUSES}", name="status_valid"),
        {"schema": SCHEMA_APP},
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    industry_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan_code: Mapped[str] = mapped_column(String(50), nullable=False, default="starter")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="trial")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en-IN")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    branding: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    business_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    holidays: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    billing_gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    billing_address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    onboarding_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    deletion_requested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Subscription(IdMixin, TimestampMixin, VersionMixin, Base):
    """Commercial SaaS billing. Deliberately separate from customer-collection payments."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="one_per_tenant"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    plan_code: Mapped[str] = mapped_column(String(50), nullable=False)
    razorpay_subscription_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="trialing")
    billing_period: Mapped[str] = mapped_column(String(20), nullable=False, default="monthly")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class TenantIndustryTemplate(IdMixin, TimestampMixin, Base):
    """Records applied template version, customizations and divergence.

    Applying or upgrading a template never overwrites tenant customization.
    """

    __tablename__ = "tenant_industry_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "template_code", name="tenant_template"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    template_code: Mapped[str] = mapped_column(String(50), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    customizations: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    divergence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    applied_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class UsageCounter(IdMixin, TimestampMixin, Base):
    """Metering. `source_event` uniqueness makes increments idempotent."""

    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "meter", "period", "source_event", name="meter_event"),
        Index("ix_usage_counters_tenant_meter_period", "tenant_id", "meter", "period"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    meter: Mapped[str] = mapped_column(String(80), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)  # YYYY-MM or YYYY-MM-DD
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_event: Mapped[str] = mapped_column(String(200), nullable=False)


class FeatureOverride(IdMixin, TimestampMixin, ActorMixin, Base):
    """Audited overrides at environment/tenant/plan/cohort/emergency granularity."""

    __tablename__ = "feature_overrides"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('environment','tenant','plan','cohort','emergency')", name="scope_valid"
        ),
        UniqueConstraint("scope", "scope_key", "flag_code", name="scope_flag"),
        {"schema": SCHEMA_APP},
    )

    scope: Mapped[str] = mapped_column(String(20), nullable=False)
    scope_key: Mapped[str] = mapped_column(String(120), nullable=False)
    flag_code: Mapped[str] = mapped_column(
        String(100), ForeignKey(f"{SCHEMA_PUBLIC}.feature_flags.code"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Branch(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "branches"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="tenant_code"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    address: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    is_headquarters: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class Team(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("branch_id", "name", name="branch_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    branch_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.branches.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    lead_user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class TeamMember(IdMixin, TimestampMixin, Base):
    __tablename__ = "team_members"
    __table_args__ = (
        UniqueConstraint("team_id", "user_id", name="team_user"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    team_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_APP}.teams.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)


for _t in (
    "subscriptions",
    "tenant_industry_templates",
    "usage_counters",
    "branches",
    "teams",
    "team_members",
):
    register_tenant_table(_t)
