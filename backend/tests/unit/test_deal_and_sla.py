"""Stage transitions, required fields, loss reasons and business-hours SLA."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from domain.base import InvalidTransition, PolicyViolation
from domain.deals.pipeline_policy import (
    DealStatus,
    StageMoveRequest,
    StageSpec,
    assert_status_transition,
    validate_stage_move,
    weighted_pipeline_value,
)
from domain.deals.sla_policy import (
    DEFAULT_BUSINESS_HOURS,
    DEFAULT_POLICIES,
    add_business_minutes,
    open_sla,
)
from shared.utils.timeutil import UTC

UTC = UTC

NEW = StageSpec("s1", "New", 0, 10)
QUALIFIED = StageSpec("s2", "Qualified", 1, 30, required_fields=("budget",))
NEGOTIATION = StageSpec("s3", "Negotiation", 2, 60, allow_backward=False)
WON = StageSpec("s4", "Booked", 3, 100, is_won=True)
LOST = StageSpec("s5", "Lost", 4, 0, is_lost=True)


class TestStageMoves:
    def test_forward_move_sets_probability(self) -> None:
        result = validate_stage_move(
            StageMoveRequest(NEW, QUALIFIED, deal_fields={"budget": 500_000})
        )
        assert result.stage_id == "s2"
        assert result.probability == 30
        assert result.status is DealStatus.OPEN

    def test_missing_required_field_blocks_the_move(self) -> None:
        with pytest.raises(PolicyViolation, match="budget"):
            validate_stage_move(StageMoveRequest(NEW, QUALIFIED))

    def test_empty_string_counts_as_missing(self) -> None:
        with pytest.raises(PolicyViolation):
            validate_stage_move(StageMoveRequest(NEW, QUALIFIED, deal_fields={"budget": ""}))

    def test_won_stage_sets_won_status(self) -> None:
        assert validate_stage_move(StageMoveRequest(NEGOTIATION, WON)).status is DealStatus.WON

    def test_lost_stage_requires_a_loss_reason(self) -> None:
        with pytest.raises(PolicyViolation, match="loss reason"):
            validate_stage_move(StageMoveRequest(NEGOTIATION, LOST))
        result = validate_stage_move(
            StageMoveRequest(NEGOTIATION, LOST, loss_reason="chose a competitor")
        )
        assert result.status is DealStatus.LOST

    def test_backward_move_blocked_when_configured(self) -> None:
        with pytest.raises(InvalidTransition, match="moving back"):
            validate_stage_move(StageMoveRequest(NEGOTIATION, QUALIFIED, {"budget": 1}))

    def test_closed_deal_must_be_reopened_first(self) -> None:
        with pytest.raises(InvalidTransition, match="reopened"):
            validate_stage_move(
                StageMoveRequest(WON, QUALIFIED, {"budget": 1}, status=DealStatus.WON)
            )


class TestStatusTransitions:
    def test_open_to_won(self) -> None:
        assert assert_status_transition("open", "won") is DealStatus.WON

    def test_won_to_lost_is_rejected(self) -> None:
        with pytest.raises(InvalidTransition):
            assert_status_transition(DealStatus.WON, DealStatus.LOST)

    def test_reopen_is_permitted(self) -> None:
        assert assert_status_transition("lost", "open") is DealStatus.OPEN

    def test_weighted_pipeline_excludes_closed_deals(self) -> None:
        deals = [
            {"amount_minor": 1_000_00, "probability": 50, "status": "open"},
            {"amount_minor": 9_999_00, "probability": 100, "status": "won"},
        ]
        assert weighted_pipeline_value(deals) == 50_000


class TestBusinessHoursSla:
    def test_within_the_same_working_day(self) -> None:
        # 10:00 IST Monday == 04:30 UTC.
        start = datetime(2026, 8, 3, 4, 30, tzinfo=UTC)
        due = add_business_minutes(start, 60)
        assert due == start + timedelta(minutes=60)

    def test_rolls_over_a_closed_evening(self) -> None:
        # 18:00 IST Monday == 12:30 UTC; only 30 working minutes remain that day.
        start = datetime(2026, 8, 3, 12, 30, tzinfo=UTC)
        due = add_business_minutes(start, 60)
        # Remaining 30 minutes land at 10:00 IST Tuesday == 04:30 UTC.
        assert due == datetime(2026, 8, 4, 4, 30, tzinfo=UTC)

    def test_skips_sunday(self) -> None:
        # 13:00 IST Saturday == 07:30 UTC; Saturday closes at 14:00 IST.
        start = datetime(2026, 8, 8, 7, 30, tzinfo=UTC)
        due = add_business_minutes(start, 90)
        # Continues Monday 09:30 IST + 30 min == 10:00 IST == 04:30 UTC.
        assert due == datetime(2026, 8, 10, 4, 30, tzinfo=UTC)

    def test_skips_a_configured_holiday(self) -> None:
        start = datetime(2026, 8, 13, 12, 30, tzinfo=UTC)  # Thursday 18:00 IST
        due = add_business_minutes(start, 60, holidays={date(2026, 8, 14)})
        assert due.date() == date(2026, 8, 15)

    def test_starting_before_opening_waits_for_the_window(self) -> None:
        start = datetime(2026, 8, 3, 1, 0, tzinfo=UTC)  # 06:30 IST
        due = add_business_minutes(start, 30)
        assert due == datetime(2026, 8, 3, 4, 30, tzinfo=UTC)  # 10:00 IST

    def test_sla_state_reports_breach_and_escalation(self) -> None:
        policy = DEFAULT_POLICIES["lead_first_response"]
        start = datetime(2026, 8, 3, 4, 30, tzinfo=UTC)
        state = open_sla(policy, start)
        assert state.status(start + timedelta(minutes=10)) == "on_track"
        assert state.status(start + timedelta(minutes=90)) == "breached"
        assert state.status(start + timedelta(minutes=200)) == "escalated"

    def test_resolved_within_target_is_met(self) -> None:
        policy = DEFAULT_POLICIES["lead_first_response"]
        start = datetime(2026, 8, 3, 4, 30, tzinfo=UTC)
        state = open_sla(policy, start)
        met = type(state)(
            state.policy,
            state.started_at,
            state.due_at,
            start + timedelta(minutes=5),
            state.escalate_at,
        )
        assert met.status() == "met"

    def test_default_business_hours_cover_every_weekday_key(self) -> None:
        assert len(DEFAULT_BUSINESS_HOURS) == 7
