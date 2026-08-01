"""Consent, opt-out, quiet hours and frequency caps gate every outbound contact."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from domain.communications.consent_policy import (
    Block,
    Channel,
    SendContext,
    evaluate_send,
    freeform_window_open,
    in_quiet_hours,
    revocation_cancels,
)
from shared.utils.timeutil import UTC

UTC = UTC
# 14:00 IST == 08:30 UTC - inside business hours, outside quiet hours.
MIDDAY_IST = datetime(2026, 8, 3, 8, 30, tzinfo=UTC)
LATE_NIGHT_IST = datetime(2026, 8, 3, 18, 0, tzinfo=UTC)  # 23:30 IST


def ctx(**overrides) -> SendContext:  # type: ignore[no-untyped-def]
    base = {
        "channel": Channel.WHATSAPP,
        "purpose": "transactional",
        "now": MIDDAY_IST,
        "consent_granted": True,
        "last_inbound_at": MIDDAY_IST - timedelta(hours=1),
        "uses_template": False,
        "template_approved": False,
    }
    base.update(overrides)
    return SendContext(**base)  # type: ignore[arg-type]


class TestHardStops:
    def test_opt_out_blocks_even_with_consent(self) -> None:
        decision = evaluate_send(ctx(opted_out=True))
        assert decision.allowed is False
        assert decision.primary_block is Block.OPTED_OUT

    def test_suppression_blocks(self) -> None:
        assert evaluate_send(ctx(suppressed=True)).primary_block is Block.SUPPRESSED

    def test_automation_stop_blocks_automated_but_not_human_sends(self) -> None:
        blocked = evaluate_send(ctx(automation_stopped=True, is_automated=True))
        allowed = evaluate_send(ctx(automation_stopped=True, is_automated=False))
        assert blocked.primary_block is Block.AUTOMATION_STOPPED
        assert allowed.allowed is True

    def test_missing_consent_blocks(self) -> None:
        assert evaluate_send(ctx(consent_granted=False)).primary_block is Block.NO_CONSENT

    def test_expired_consent_blocks(self) -> None:
        decision = evaluate_send(ctx(consent_expires_at=MIDDAY_IST - timedelta(days=1)))
        assert decision.primary_block is Block.CONSENT_EXPIRED


class TestQuietHours:
    def test_blocks_inside_the_window(self) -> None:
        assert evaluate_send(ctx(now=LATE_NIGHT_IST)).primary_block is Block.QUIET_HOURS

    def test_wrapping_window_is_handled(self) -> None:
        quiet = {"start": "21:00", "end": "09:00", "timezone": "Asia/Kolkata"}
        assert in_quiet_hours(LATE_NIGHT_IST, quiet, "Asia/Kolkata") is True
        assert in_quiet_hours(MIDDAY_IST, quiet, "Asia/Kolkata") is False

    def test_authentication_purpose_is_exempt(self) -> None:
        decision = evaluate_send(ctx(now=LATE_NIGHT_IST, purpose="authentication"))
        assert Block.QUIET_HOURS not in decision.blocks

    def test_disabled_quiet_hours_never_block(self) -> None:
        decision = evaluate_send(ctx(now=LATE_NIGHT_IST, quiet_hours={"enabled": False}))
        assert Block.QUIET_HOURS not in decision.blocks


class TestFrequencyAndBudget:
    def test_cap_blocks_at_the_limit(self) -> None:
        assert evaluate_send(ctx(sends_today=5)).primary_block is Block.FREQUENCY_CAP

    def test_below_cap_allows(self) -> None:
        assert evaluate_send(ctx(sends_today=4)).allowed is True

    def test_null_cap_disables_the_check(self) -> None:
        assert evaluate_send(ctx(sends_today=999, frequency_cap_per_day=None)).allowed is True

    def test_budget_exhaustion_blocks(self) -> None:
        assert evaluate_send(ctx(budget_remaining=0)).primary_block is Block.BUDGET_EXHAUSTED


class TestWhatsappTemplateWindow:
    def test_freeform_allowed_inside_24h_window(self) -> None:
        assert evaluate_send(ctx()).allowed is True

    def test_freeform_blocked_outside_window(self) -> None:
        decision = evaluate_send(ctx(last_inbound_at=MIDDAY_IST - timedelta(hours=25)))
        assert decision.primary_block is Block.FREEFORM_WINDOW_CLOSED
        assert decision.requires_template is True

    def test_unapproved_template_blocked_outside_window(self) -> None:
        decision = evaluate_send(
            ctx(last_inbound_at=None, uses_template=True, template_approved=False)
        )
        assert decision.primary_block is Block.TEMPLATE_NOT_APPROVED

    def test_approved_template_allowed_outside_window(self) -> None:
        decision = evaluate_send(
            ctx(last_inbound_at=None, uses_template=True, template_approved=True)
        )
        assert decision.allowed is True

    def test_window_helper(self) -> None:
        assert freeform_window_open(MIDDAY_IST - timedelta(hours=23), MIDDAY_IST) is True
        assert freeform_window_open(None, MIDDAY_IST) is False


class TestDegradation:
    def test_unhealthy_channel_queues_rather_than_rejects(self) -> None:
        decision = evaluate_send(ctx(channel_healthy=False))
        assert decision.allowed is True
        assert decision.queued is True
        assert decision.primary_block is Block.CHANNEL_UNHEALTHY

    def test_disconnected_channel_blocks(self) -> None:
        assert evaluate_send(ctx(channel_connected=False)).primary_block is Block.CHANNEL_DISABLED

    def test_feature_flag_off_blocks(self) -> None:
        assert evaluate_send(ctx(feature_enabled=False)).primary_block is Block.FEATURE_DISABLED

    def test_hard_bounce_blocks(self) -> None:
        assert evaluate_send(ctx(channel=Channel.EMAIL, hard_bounced=True)).allowed is False


def test_blocks_are_reported_in_severity_order() -> None:
    decision = evaluate_send(ctx(opted_out=True, sends_today=99, now=LATE_NIGHT_IST))
    assert decision.blocks[0] is Block.OPTED_OUT
    assert decision.reason


def test_every_block_has_an_operator_facing_message() -> None:
    from domain.communications.consent_policy import HUMAN_MESSAGES

    assert set(HUMAN_MESSAGES) == set(Block)


@pytest.mark.parametrize(
    ("purpose", "expected"),
    [("marketing", True), ("transactional", True), ("authentication", False), ("security", False)],
)
def test_revocation_scope(purpose: str, expected: bool) -> None:
    assert revocation_cancels(purpose) is expected
