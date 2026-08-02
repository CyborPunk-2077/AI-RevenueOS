"""Payment state machine and server-side amount authority.

The browser never determines an amount and never sees card data. Refunds are
recorded separately; a captured payment is never rewritten in place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from domain.base import InvalidTransition, PolicyViolation
from shared.utils.money import Money


class PaymentStatus(StrEnum):
    CREATED = "created"
    ATTEMPTED = "attempted"
    CAPTURED = "captured"
    FAILED = "failed"
    REFUNDED = "refunded"


class PaymentMethod(StrEnum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"
    WALLET = "wallet"
    EMI = "emi"
    UPI_INTENT = "upi_intent"
    UNKNOWN = "unknown"


ALLOWED: dict[PaymentStatus, frozenset[PaymentStatus]] = {
    PaymentStatus.CREATED: frozenset({PaymentStatus.ATTEMPTED, PaymentStatus.FAILED}),
    PaymentStatus.ATTEMPTED: frozenset({PaymentStatus.CAPTURED, PaymentStatus.FAILED}),
    PaymentStatus.CAPTURED: frozenset({PaymentStatus.REFUNDED}),
    PaymentStatus.FAILED: frozenset(),
    PaymentStatus.REFUNDED: frozenset(),
}

TERMINAL = frozenset({PaymentStatus.FAILED, PaymentStatus.REFUNDED})

# Refunds above this value require MFA plus an elevated approval.
REFUND_MFA_THRESHOLD = Money.from_major("10000", "INR")

# Fields that must never be persisted or logged, whatever the provider returns.
FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "card_number",
        "card",
        "pan",
        "cvv",
        "cvc",
        "expiry_month",
        "expiry_year",
        "cardholder_name",
        "track_data",
        "pin",
    }
)


def assert_transition(
    current: PaymentStatus | str, target: PaymentStatus | str, *, idempotent: bool = True
) -> PaymentStatus:
    """Repeating the current state is a no-op; anything else follows the machine."""
    cur, tgt = PaymentStatus(current), PaymentStatus(target)
    if cur == tgt:
        if idempotent:
            return tgt
        raise InvalidTransition(f"payment is already {cur.value}")
    if tgt not in ALLOWED[cur]:
        raise InvalidTransition(f"cannot move a payment from {cur.value} to {tgt.value}")
    return tgt


def sanitize_provider_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip anything resembling card data before the payload is persisted."""

    def clean(node: Any, depth: int = 0) -> Any:
        if depth > 6:
            return "[TRUNCATED]"
        if isinstance(node, dict):
            return {
                k: (
                    "[REMOVED]" if str(k).lower() in FORBIDDEN_PAYLOAD_KEYS else clean(v, depth + 1)
                )
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [clean(v, depth + 1) for v in node[:100]]
        return node

    cleaned: dict[str, Any] = clean(payload)
    return cleaned


@dataclass(frozen=True, slots=True)
class OrderRequest:
    """Amount and currency are derived server side from invoice or catalogue data."""

    tenant_id: str
    amount_minor: int
    currency: str = "INR"
    invoice_id: str | None = None
    contact_id: str | None = None
    notes: dict[str, Any] | None = None


def validate_order(
    request: OrderRequest, *, server_derived_amount_minor: int, min_minor: int = 100
) -> Money:
    """Reject any client-supplied amount that does not match the server calculation."""
    if request.currency != "INR":
        raise PolicyViolation("only INR collections are supported")
    if request.amount_minor != server_derived_amount_minor:
        raise PolicyViolation("the requested amount does not match the server-derived amount")
    if request.amount_minor < min_minor:
        raise PolicyViolation("the order amount is below the permitted minimum")
    return Money(request.amount_minor, request.currency)


@dataclass(frozen=True, slots=True)
class RefundAuthorization:
    permitted: bool
    requires_mfa: bool
    requires_approval: bool
    reason: str | None = None


def authorize_refund(
    *,
    payment_status: PaymentStatus | str,
    payment_amount_minor: int,
    already_refunded_minor: int,
    refund_amount_minor: int,
    actor_has_permission: bool,
    mfa_verified: bool,
    approver_id: str | None,
) -> RefundAuthorization:
    status = PaymentStatus(payment_status)
    if status is not PaymentStatus.CAPTURED:
        return RefundAuthorization(False, False, False, "only captured payments can be refunded")
    if refund_amount_minor <= 0:
        return RefundAuthorization(False, False, False, "refund amount must be positive")
    if already_refunded_minor + refund_amount_minor > payment_amount_minor:
        return RefundAuthorization(False, False, False, "refund exceeds the captured amount")
    if not actor_has_permission:
        return RefundAuthorization(False, False, False, "actor lacks payment:refund")

    high_value = refund_amount_minor > REFUND_MFA_THRESHOLD.amount_minor
    if high_value and not (mfa_verified and approver_id):
        return RefundAuthorization(
            False,
            True,
            True,
            "refunds above INR 10,000 require MFA and an elevated approval",
        )
    return RefundAuthorization(True, high_value, high_value)
