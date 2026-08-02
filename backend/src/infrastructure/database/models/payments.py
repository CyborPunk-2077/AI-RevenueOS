"""Immutable append-only payment history. No raw card data ever touches this system."""

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

PAYMENT_STATUSES = ("created", "attempted", "captured", "failed", "refunded")
PAYMENT_METHODS = ("upi", "card", "netbanking", "wallet", "emi", "upi_intent", "unknown")

# Enforced state machine. Refunds are recorded separately, never as a status rewrite.
ALLOWED_PAYMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"attempted", "failed"}),
    "attempted": frozenset({"captured", "failed"}),
    "captured": frozenset({"refunded"}),
    "failed": frozenset(),
    "refunded": frozenset(),
}


class Payment(IdMixin, TimestampMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint(f"status IN {PAYMENT_STATUSES}", name="status_valid"),
        CheckConstraint(f"method IN {PAYMENT_METHODS}", name="method_valid"),
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint("currency = 'INR'", name="currency_inr"),
        UniqueConstraint("external_order_id", name="external_order_unique"),
        UniqueConstraint("external_payment_id", name="external_unique"),
        Index("ix_payments_tenant_status_created", "tenant_id", "status", "created_at"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    deal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    external_order_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_minor: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="razorpay")
    provider_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reconciliation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )
    reconciled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PaymentTransition(IdMixin, TimestampMixin, Base):
    """Append-only transition history; the payment row keeps only the current status."""

    __tablename__ = "payment_transitions"
    __table_args__ = (
        UniqueConstraint("payment_id", "sequence", name="payment_sequence"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    payment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="webhook")
    provider_event_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class Refund(IdMixin, TimestampMixin, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        UniqueConstraint("external_refund_id", name="refund_external_unique"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    payment_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    external_refund_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_minor: Mapped[int] = mapped_column(nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    approved_by: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    provider_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Invoice(IdMixin, TimestampMixin, SoftDeleteMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "number", name="tenant_number"),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    number: Mapped[str] = mapped_column(String(60), nullable=False)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    deal_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    line_items: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    subtotal_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    tax_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    total_minor: Mapped[int] = mapped_column(nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gstin: Mapped[str | None] = mapped_column(String(20), nullable=True)
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)


class PaymentLink(IdMixin, TimestampMixin, VersionMixin, ActorMixin, Base):
    __tablename__ = "payment_links"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False, index=True)
    invoice_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    contact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    amount_minor: Mapped[int] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    external_link_id: Mapped[str | None] = mapped_column(String(120), nullable=True, unique=True)
    short_url: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReconciliationRun(IdMixin, TimestampMixin, Base):
    __tablename__ = "reconciliation_runs"
    __table_args__ = ({"schema": SCHEMA_APP},)

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, default="razorpay")
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    checked: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    repaired: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discrepancies: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")


class ProviderWebhookEvent(IdMixin, TimestampMixin, Base):
    """Verified, deduped inbound provider events. Business work is always async."""

    __tablename__ = "provider_webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "external_event_id", name="provider_event"),
        Index(
            "ix_provider_webhook_unprocessed", "created_at", postgresql_where="processed_at IS NULL"
        ),
        {"schema": SCHEMA_APP},
    )

    tenant_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    external_event_id: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(120), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


for _t in (
    "payments",
    "payment_transitions",
    "refunds",
    "invoices",
    "payment_links",
    "reconciliation_runs",
    "provider_webhook_events",
):
    register_tenant_table(_t)
