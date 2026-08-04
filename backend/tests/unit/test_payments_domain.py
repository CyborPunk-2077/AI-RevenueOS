"""Payment state machine, server-side amount authority and refund authorisation."""

from __future__ import annotations

from typing import Any

import pytest

from domain.base import InvalidTransition, PolicyViolation
from domain.payments.state_machine import (
    ALLOWED,
    REFUND_MFA_THRESHOLD,
    OrderRequest,
    PaymentStatus,
    RefundAuthorization,
    assert_transition,
    authorize_refund,
    sanitize_provider_payload,
    validate_order,
)


class TestStateMachine:
    def test_full_capture_path(self) -> None:
        assert assert_transition("created", "attempted") is PaymentStatus.ATTEMPTED
        assert assert_transition("attempted", "captured") is PaymentStatus.CAPTURED
        assert assert_transition("captured", "refunded") is PaymentStatus.REFUNDED

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            ("created", "captured"),
            ("failed", "captured"),
            ("refunded", "captured"),
            ("captured", "failed"),
            ("failed", "attempted"),
        ],
    )
    def test_illegal_transitions_rejected(self, current: str, target: str) -> None:
        with pytest.raises(InvalidTransition):
            assert_transition(current, target)

    def test_repeat_of_current_state_is_idempotent(self) -> None:
        assert assert_transition("captured", "captured") is PaymentStatus.CAPTURED

    def test_non_idempotent_mode_rejects_repeats(self) -> None:
        with pytest.raises(InvalidTransition):
            assert_transition("captured", "captured", idempotent=False)

    def test_terminal_states_have_no_exits(self) -> None:
        assert ALLOWED[PaymentStatus.FAILED] == frozenset()
        assert ALLOWED[PaymentStatus.REFUNDED] == frozenset()

    def test_every_status_is_covered(self) -> None:
        assert set(ALLOWED) == set(PaymentStatus)


class TestCardDataHygiene:
    def test_card_fields_are_stripped_from_provider_payloads(self) -> None:
        payload = {
            "id": "pay_123",
            "card": {"card_number": "4111111111111111", "cvv": "123", "network": "Visa"},
            "method": "card",
        }
        cleaned = sanitize_provider_payload(payload)
        assert cleaned["card"] == "[REMOVED]"
        assert cleaned["method"] == "card"

    def test_nested_card_number_removed(self) -> None:
        cleaned = sanitize_provider_payload({"a": {"b": {"pan": "4111111111111111"}}})
        assert cleaned["a"]["b"]["pan"] == "[REMOVED]"

    def test_serialised_payload_contains_no_pan(self) -> None:
        import json

        cleaned = sanitize_provider_payload(
            {"cardholder_name": "A Kumar", "expiry_month": 12, "amount": 1000}
        )
        assert "A Kumar" not in json.dumps(cleaned)
        assert cleaned["amount"] == 1000


class TestOrderAmountAuthority:
    def test_matching_amount_accepted(self) -> None:
        order = OrderRequest("t1", 250_000)
        assert validate_order(order, server_derived_amount_minor=250_000).amount_minor == 250_000

    def test_tampered_amount_rejected(self) -> None:
        with pytest.raises(PolicyViolation, match="does not match"):
            validate_order(OrderRequest("t1", 1), server_derived_amount_minor=250_000)

    def test_non_inr_rejected(self) -> None:
        with pytest.raises(PolicyViolation, match="INR"):
            validate_order(OrderRequest("t1", 100, "USD"), server_derived_amount_minor=100)

    def test_below_minimum_rejected(self) -> None:
        with pytest.raises(PolicyViolation, match="minimum"):
            validate_order(OrderRequest("t1", 50), server_derived_amount_minor=50)


class TestRefundAuthorisation:
    def _base(self, **over: Any) -> RefundAuthorization:
        args: dict[str, Any] = {
            "payment_status": PaymentStatus.CAPTURED,
            "payment_amount_minor": 5_000_000,
            "already_refunded_minor": 0,
            "refund_amount_minor": 100_000,
            "actor_has_permission": True,
            "mfa_verified": False,
            "approver_id": None,
        }
        args.update(over)
        return authorize_refund(**args)

    def test_small_refund_permitted_without_mfa(self) -> None:
        result = self._base()
        assert result.permitted is True and result.requires_mfa is False

    def test_uncaptured_payment_cannot_be_refunded(self) -> None:
        assert self._base(payment_status="attempted").permitted is False

    def test_over_refund_rejected(self) -> None:
        assert self._base(already_refunded_minor=4_950_000).permitted is False

    def test_missing_permission_rejected(self) -> None:
        assert self._base(actor_has_permission=False).permitted is False

    def test_high_value_requires_mfa_and_approval(self) -> None:
        result = self._base(refund_amount_minor=REFUND_MFA_THRESHOLD.amount_minor + 1)
        assert result.permitted is False
        assert result.requires_mfa is True and result.requires_approval is True

    def test_high_value_permitted_with_mfa_and_approver(self) -> None:
        result = self._base(
            refund_amount_minor=REFUND_MFA_THRESHOLD.amount_minor + 1,
            mfa_verified=True,
            approver_id="u-approver",
        )
        assert result.permitted is True

    def test_threshold_boundary_is_exclusive(self) -> None:
        assert self._base(refund_amount_minor=REFUND_MFA_THRESHOLD.amount_minor).permitted is True

    def test_zero_or_negative_rejected(self) -> None:
        assert self._base(refund_amount_minor=0).permitted is False
        assert self._base(refund_amount_minor=-5).permitted is False
