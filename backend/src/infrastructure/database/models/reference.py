"""`public` schema: plans, feature flags, industry templates, permissions."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, CheckConstraint, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from infrastructure.database.base import SCHEMA_PUBLIC, Base, IdMixin, TimestampMixin


class Plan(IdMixin, TimestampMixin, Base):
    __tablename__ = "plans"
    __table_args__ = (
        CheckConstraint("price_inr > 0", name="price_positive"),
        {"schema": SCHEMA_PUBLIC},
    )

    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    max_users: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    max_leads: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    price_inr: Mapped[int] = mapped_column(Integer, nullable=False)
    sort: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class FeatureFlag(IdMixin, TimestampMixin, Base):
    __tablename__ = "feature_flags"
    __table_args__ = ({"schema": SCHEMA_PUBLIC},)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    default_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    requires_external_gate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    activation_prerequisite: Mapped[str | None] = mapped_column(String(500), nullable=True)


class IndustryTemplate(IdMixin, TimestampMixin, Base):
    """Templates are versioned configuration only. No per-industry code fork exists."""

    __tablename__ = "industry_templates"
    __table_args__ = (
        UniqueConstraint("code", "version", name="code_version"),
        {"schema": SCHEMA_PUBLIC},
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    terminology: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    lead_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    qualification_rubric: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    pipeline_stages: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    message_templates: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    document_templates: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    workflow_recipes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    business_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    dashboard_presets: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    prohibited_ai_rules: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    consent_copy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Permission(IdMixin, TimestampMixin, Base):
    __tablename__ = "permissions"
    __table_args__ = ({"schema": SCHEMA_PUBLIC},)

    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    resource: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    is_owner_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
