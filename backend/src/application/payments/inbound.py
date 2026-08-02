"""Durable, tenant-derived processing for verified Razorpay webhooks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from application.audit.recorder import AuditRecorder
from domain.base import DomainEvent, InvalidTransition
from domain.payments.state_machine import assert_transition, sanitize_provider_payload
from infrastructure.database.models.audit import EventOutbox
from infrastructure.database.models.payments import (
    PAYMENT_METHODS,
    Payment,
    PaymentTransition,
    ProviderWebhookEvent,
)
from infrastructure.database.session import (
    bind_platform_context,
    bind_tenant,
    get_sessionmaker,
)
from infrastructure.logging.setup import get_logger
from shared.utils.timeutil import utcnow

logger = get_logger("payments.inbound")

PROVIDER = "razorpay"
VERIFIED_LOOKUP_CONTEXT = "verified_razorpay_webhook"


@dataclass(frozen=True, slots=True)
class RazorpayReceipt:
    accepted: bool
    event_id: str
    duplicate: bool
    processed: bool
    state: str
    payment_id: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


async def accept_verified_razorpay_event(
    parsed: dict[str, Any],
    *,
    correlation_id: str | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> RazorpayReceipt:
    """Persist and apply one event only after its caller verifies the raw signature.

    The tenant is resolved from a previously stored Razorpay order/payment mapping.
    Provider-controlled notes or tenant metadata are never used for authorization.
    Receipt, transition, audit and outbox state share one database transaction.
    """
    event_id = str(parsed.get("external_event_id") or "").strip()
    event_type = str(parsed.get("event") or "").strip()
    if not event_id or not event_type:
        return RazorpayReceipt(
            accepted=False,
            event_id=event_id,
            duplicate=False,
            processed=False,
            state="rejected",
            detail="a provider event id and event type are required",
        )

    factory = session_factory or get_sessionmaker()
    payload = sanitize_provider_payload(parsed)
    async with factory() as session, session.begin():
        # This exact context opens SELECT-only lookup policies. It never widens
        # payment writes, which still require the derived tenant binding below.
        await bind_platform_context(session, VERIFIED_LOOKUP_CONTEXT)
        existing = await _find_event(session, event_id, lock=False)
        if existing is not None and existing.processed_at is not None:
            return _duplicate_receipt(existing)

        payment, mapping_error = await _resolve_payment(session, parsed)
        if payment is None:
            event = await _find_event(session, event_id, lock=True) if existing else None
            event = event or await _insert_event(
                session,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                tenant_id=None,
            )
            if event is None:
                event = await _find_event(session, event_id, lock=True)
            if event is not None and event.processed_at is not None:
                return _duplicate_receipt(event)
            if event is None:  # pragma: no cover - conflict row is always visible by policy
                raise RuntimeError("durable Razorpay event could not be recovered")
            event.attempts += 1
            event.last_error = mapping_error or "payment mapping not found"
            return RazorpayReceipt(
                accepted=True,
                event_id=event_id,
                duplicate=existing is not None,
                processed=False,
                state="pending_mapping",
                detail=event.last_error,
            )

        tenant_id = payment.tenant_id
        await bind_tenant(session, tenant_id)
        payment = (
            await session.execute(select(Payment).where(Payment.id == payment.id).with_for_update())
        ).scalar_one()
        event = await _find_event(session, event_id, lock=True) if existing else None
        if event is not None and event.tenant_id not in (None, tenant_id):
            return RazorpayReceipt(
                accepted=True,
                event_id=event_id,
                duplicate=True,
                processed=event.processed_at is not None,
                state="duplicate_conflict",
                detail="provider event id is already bound to another payment tenant",
            )
        if event is None:
            event = await _insert_event(
                session,
                event_id=event_id,
                event_type=event_type,
                payload=payload,
                tenant_id=tenant_id,
            )
            if event is None:
                event = await _find_event(session, event_id, lock=True)
        if event is None:  # pragma: no cover - conflict row is always visible by policy
            raise RuntimeError("durable Razorpay event could not be recovered")
        if event.processed_at is not None:
            return _duplicate_receipt(event)

        # A previously unknown event may be rebound only after a real payment
        # mapping establishes its tenant. Migration 0007 permits exactly this move.
        event.tenant_id = tenant_id
        event.payload = payload
        event.attempts += 1
        event.last_error = None

        identity_error = _validate_provider_identity(payment, parsed)
        if identity_error:
            event.last_error = identity_error
            return RazorpayReceipt(
                accepted=True,
                event_id=event_id,
                duplicate=existing is not None,
                processed=False,
                state="pending_reconciliation",
                payment_id=str(payment.id),
                detail=identity_error,
            )

        target = parsed.get("status")
        if not isinstance(target, str):
            return _mark_ignored(
                event,
                payment,
                event_id=event_id,
                detail="unsupported Razorpay event type",
            )
        try:
            new_status = assert_transition(payment.status, target)
        except (InvalidTransition, ValueError) as exc:
            return _mark_ignored(
                event,
                payment,
                event_id=event_id,
                detail=f"out-of-order event ignored: {exc}",
            )
        if new_status.value == payment.status:
            return _mark_ignored(
                event,
                payment,
                event_id=event_id,
                detail="payment already has this status",
            )

        old_status = payment.status
        sequence = await _next_transition_sequence(session, payment.id)
        payment.status = new_status.value
        external_payment_id = parsed.get("external_payment_id")
        if external_payment_id and payment.external_payment_id is None:
            payment.external_payment_id = str(external_payment_id)
        method = str(parsed.get("method") or "unknown")
        payment.method = method if method in PAYMENT_METHODS else "unknown"
        payment.provider_payload = sanitize_provider_payload(parsed.get("entity") or {})
        payment.reconciliation_status = "matched"
        payment.reconciled_at = utcnow()
        if new_status.value == "captured":
            payment.captured_at = utcnow()

        session.add(
            PaymentTransition(
                tenant_id=tenant_id,
                payment_id=payment.id,
                sequence=sequence,
                from_status=old_status,
                to_status=new_status.value,
                source="webhook",
                provider_event_id=event_id,
                correlation_id=correlation_id,
            )
        )
        action = f"payment.{new_status.value}"
        AuditRecorder(session).record(
            action=action,
            resource_type="payment",
            resource_id=payment.id,
            tenant_id=tenant_id,
            actor_type="provider",
            actor_label=PROVIDER,
            old_values={"status": old_status},
            new_values={"status": new_status.value},
            metadata={"provider": PROVIDER, "external_event_id": event_id},
        )
        _add_outbox(
            session,
            DomainEvent(
                event_type=action,
                tenant_id=tenant_id,
                resource_type="payment",
                resource_id=payment.id,
                payload={
                    "from_status": old_status,
                    "to_status": new_status.value,
                    "provider": PROVIDER,
                    "external_event_id": event_id,
                },
                actor_type="provider",
                correlation_id=correlation_id,
            ),
        )
        event.processed_at = utcnow()
        await session.flush()
        logger.info(
            "razorpay_event_processed",
            event_type=event_type,
            payment_id=str(payment.id),
            tenant_id=str(tenant_id),
            correlation_id=correlation_id,
        )
        return RazorpayReceipt(
            accepted=True,
            event_id=event_id,
            duplicate=False,
            processed=True,
            state="applied",
            payment_id=str(payment.id),
        )


async def _find_event(
    session: AsyncSession, event_id: str, *, lock: bool
) -> ProviderWebhookEvent | None:
    statement = select(ProviderWebhookEvent).where(
        ProviderWebhookEvent.provider == PROVIDER,
        ProviderWebhookEvent.external_event_id == event_id,
    )
    if lock:
        statement = statement.with_for_update()
    return (await session.execute(statement)).scalar_one_or_none()


async def _insert_event(
    session: AsyncSession,
    *,
    event_id: str,
    event_type: str,
    payload: dict[str, Any],
    tenant_id: UUID | None,
) -> ProviderWebhookEvent | None:
    inserted_id = (
        await session.execute(
            pg_insert(ProviderWebhookEvent)
            .values(
                tenant_id=tenant_id,
                provider=PROVIDER,
                external_event_id=event_id,
                event_type=event_type,
                signature_verified=True,
                payload=payload,
                attempts=0,
            )
            .on_conflict_do_nothing(index_elements=["provider", "external_event_id"])
            .returning(ProviderWebhookEvent.id)
        )
    ).scalar_one_or_none()
    if inserted_id is None:
        return None
    return (
        await session.execute(
            select(ProviderWebhookEvent).where(ProviderWebhookEvent.id == inserted_id)
        )
    ).scalar_one()


async def _resolve_payment(
    session: AsyncSession, parsed: dict[str, Any]
) -> tuple[Payment | None, str | None]:
    external_payment_id = str(parsed.get("external_payment_id") or "").strip()
    external_order_id = str(parsed.get("external_order_id") or "").strip()
    predicates = []
    if external_payment_id:
        predicates.append(Payment.external_payment_id == external_payment_id)
    if external_order_id:
        predicates.append(Payment.external_order_id == external_order_id)
    if not predicates:
        return None, "provider event has no payment or order identifier"
    matches = list(
        (
            await session.execute(
                select(Payment).where(Payment.provider == PROVIDER, or_(*predicates)).limit(2)
            )
        )
        .scalars()
        .all()
    )
    if not matches:
        return None, "payment mapping not found"
    if len(matches) > 1:
        return None, "provider identifiers resolve to different payments"
    return matches[0], None


def _validate_provider_identity(payment: Payment, parsed: dict[str, Any]) -> str | None:
    external_payment_id = str(parsed.get("external_payment_id") or "").strip()
    if (
        payment.external_payment_id
        and external_payment_id
        and payment.external_payment_id != external_payment_id
    ):
        return "provider payment identifier does not match the stored mapping"
    amount = parsed.get("amount_minor")
    if amount is not None and (not isinstance(amount, int) or amount != payment.amount_minor):
        return "provider amount does not match the server-authoritative amount"
    currency = parsed.get("currency")
    if currency is not None and str(currency) != payment.currency:
        return "provider currency does not match the stored payment"
    return None


async def _next_transition_sequence(session: AsyncSession, payment_id: UUID) -> int:
    current = (
        await session.execute(
            select(func.coalesce(func.max(PaymentTransition.sequence), 0)).where(
                PaymentTransition.payment_id == payment_id
            )
        )
    ).scalar_one()
    return int(current) + 1


def _mark_ignored(
    event: ProviderWebhookEvent,
    payment: Payment,
    *,
    event_id: str,
    detail: str,
) -> RazorpayReceipt:
    event.processed_at = utcnow()
    event.last_error = detail
    return RazorpayReceipt(
        accepted=True,
        event_id=event_id,
        duplicate=False,
        processed=True,
        state="ignored",
        payment_id=str(payment.id),
        detail=detail,
    )


def _duplicate_receipt(event: ProviderWebhookEvent) -> RazorpayReceipt:
    return RazorpayReceipt(
        accepted=True,
        event_id=event.external_event_id,
        duplicate=True,
        processed=event.processed_at is not None,
        state="duplicate",
    )


def _add_outbox(session: AsyncSession, event: DomainEvent) -> None:
    session.add(
        EventOutbox(
            occurred_at=event.occurred_at,
            event_id=event.event_id,
            event_type=event.event_type,
            tenant_id=event.tenant_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            payload=event.to_outbox_payload(),
            correlation_id=event.correlation_id,
            attempts=0,
        )
    )


def apply_status(current: str, event_status: str | None) -> str:
    """Compatibility helper: invalid or out-of-order transitions are no-ops."""
    if event_status is None:
        return current
    try:
        return assert_transition(current, event_status).value
    except (InvalidTransition, ValueError):
        logger.warning("razorpay_out_of_order_event", current=current, incoming=event_status)
        return current
