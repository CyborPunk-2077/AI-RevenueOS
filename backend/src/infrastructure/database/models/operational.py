"""Notifications, imports/exports, integrations and dashboards."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
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
    TimestampMixin,
    VersionMixin,
    register_tenant_table,
)


class Notification(IdMixin, TimestampMixin, Base):
    """Durable, idempotent and always owned by the requesting user."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "underlying_event_key", name="user_event"),
        Index(
            "ix_notifications_user_unread",
            "tenant_id",
            "user_id",
            "created_at",
            postgresql_where="is_read = false",
        ),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    body: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    entity_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_actionable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    is_security: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    underlying_event_key: Mapped[str] = mapped_column(String(250), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ImportJob(IdMixin, TimestampMixin, Base):
    __tablename__ = "imports"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="create")
    match_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    mapping: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    defaults: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    source_file_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    created_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExportJob(IdMixin, TimestampMixin, Base):
    """Asynchronous, entitled, private and auditable. No synchronous full-data export."""

    __tablename__ = "exports"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    export_type: Mapped[str] = mapped_column(String(60), nullable=False)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntegrationConnection(IdMixin, TimestampMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", "name", name="tenant_provider_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    encrypted_config: Mapped[str | None] = mapped_column(Text, nullable=True)
    scopes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="disconnected")
    health_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sync_cursor: Mapped[str | None] = mapped_column(String(300), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Dashboard(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "dashboards"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    user_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class DashboardWidget(IdMixin, TimestampMixin, Base):
    __tablename__ = "dashboard_widgets"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    dashboard_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    widget_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    grid_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grid_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    grid_w: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    grid_h: Mapped[int] = mapped_column(Integer, nullable=False, default=3)


for _t in (
    "notifications",
    "imports",
    "exports",
    "integration_connections",
    "dashboards",
    "dashboard_widgets",
):
    register_tenant_table(_t)
