"""Channels, templates, conversations and monthly-partitioned immutable messages."""

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
    Base,
    IdMixin,
    SoftDeleteMixin,
    TimestampMixin,
    VersionMixin,
    register_tenant_table,
)
from shared.utils.ids import uuid7

CHANNEL_TYPES = ("whatsapp", "email", "web_chat", "voice", "sms")
MESSAGE_DIRECTIONS = ("inbound", "outbound")
MESSAGE_STATUSES = ("pending", "queued", "sent", "delivered", "read", "failed", "bounced")
CONTENT_TYPES = (
    "text",
    "image",
    "video",
    "audio",
    "document",
    "location",
    "template",
    "interactive",
)


class Channel(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "channels"
    __table_args__ = (
        CheckConstraint(f"channel_type IN {CHANNEL_TYPES}", name="type_valid"),
        UniqueConstraint("tenant_id", "channel_type", "identifier", name="tenant_channel"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    identifier: Mapped[str] = mapped_column(String(200), nullable=False, default="default")
    display_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    encrypted_credentials: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    health_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unconfigured")
    health_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    health_detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MessageTemplate(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "message_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel_type", "name", name="tenant_channel_name"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="utility")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    variables: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    provider_template_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Conversation(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active','resolved','archived','spam')", name="status_valid"),
        Index("ix_conversations_tenant_status_last", "tenant_id", "status", "last_message_at"),
        Index("ix_conversations_tenant_assignee", "tenant_id", "assignee_id"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    lead_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    primary_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    assignee_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    branch_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    team_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    automation_stopped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    automation_stopped_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    handoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Message(Base):
    """Monthly-partitioned and immutable in both directions. 36 month retention."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint(f"direction IN {MESSAGE_DIRECTIONS}", name="direction_valid"),
        CheckConstraint(f"status IN {MESSAGE_STATUSES}", name="status_valid"),
        CheckConstraint(f"content_type IN {CONTENT_TYPES}", name="content_type_valid"),
        Index("ix_messages_conversation_created", "tenant_id", "conversation_id", "created_at"),
        UniqueConstraint(
            "tenant_id", "channel", "external_id", "created_at", name="tenant_external"
        ),
        {"schema": SCHEMA_APP, "postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False, default="contact")
    sender_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    media: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    template_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    failure_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class CommunicationPreference(IdMixin, TimestampMixin, VersionMixin, Base):
    """Per-subject channel preference layered on top of the immutable consent ledger."""

    __tablename__ = "communication_preferences"
    __table_args__ = (
        UniqueConstraint("tenant_id", "subject_identifier", "channel", name="subject_channel"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    subject_identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quiet_hours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    frequency_cap_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    digest_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)


class SuppressionEntry(IdMixin, TimestampMixin, Base):
    __tablename__ = "suppression_entries"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", "identifier", name="channel_identifier"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    reason: Mapped[str] = mapped_column(String(80), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WebchatWidget(IdMixin, TimestampMixin, VersionMixin, Base):
    __tablename__ = "webchat_widgets"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="widget_one_per_tenant"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    public_key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    allowed_origins: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    branding: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    greeting: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    consent_copy: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    ai_suggestions_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    handoff_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WebchatSession(IdMixin, TimestampMixin, Base):
    __tablename__ = "webchat_sessions"
    __table_args__ = (
        Index("ix_webchat_sessions_tenant_created", "tenant_id", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    session_token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    origin: Mapped[str] = mapped_column(String(300), nullable=False)
    visitor_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    identified_contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    consent_granted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class VoiceCall(IdMixin, TimestampMixin, Base):
    """Present but hard-disabled until legal/consent/disclosure sign-off."""

    __tablename__ = "voice_calls"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    conversation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="none")
    external_call_id: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="created")
    from_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    disclosure_played: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recording_consent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recording_s3_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    transcript_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(60), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


for _t in (
    "channels",
    "message_templates",
    "conversations",
    "messages",
    "communication_preferences",
    "suppression_entries",
    "webchat_widgets",
    "webchat_sessions",
    "voice_calls",
):
    register_tenant_table(_t)
