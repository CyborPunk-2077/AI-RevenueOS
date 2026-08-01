"""Slot generation, buffers, capacity, notice windows, DST and holidays."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from domain.appointments.slots import (
    Busy,
    SlotRules,
    WorkingWindow,
    can_cancel,
    can_reschedule,
    compute_slots,
)
from shared.utils.timeutil import UTC

UTC = UTC
IST = "Asia/Kolkata"
# Monday 2026-08-03. 09:30-12:30 IST == 04:00-07:00 UTC.
MONDAY = date(2026, 8, 3)
WINDOWS = [WorkingWindow(day_of_week=0, start_minute=9 * 60 + 30, end_minute=12 * 60 + 30)]
EARLY = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)


def test_generates_expected_slot_count() -> None:
    slots = compute_slots(
        day=MONDAY,
        timezone_name=IST,
        windows=WINDOWS,
        busy=[],
        rules=SlotRules(duration_minutes=30, granularity_minutes=30, min_notice_minutes=0),
        now=EARLY,
    )
    assert len(slots) == 6
    assert slots[0].start_at == datetime(2026, 8, 3, 4, 0, tzinfo=UTC)


def test_busy_period_removes_the_overlapping_slot() -> None:
    busy = [Busy(datetime(2026, 8, 3, 4, 0, tzinfo=UTC), datetime(2026, 8, 3, 4, 30, tzinfo=UTC))]
    slots = compute_slots(
        day=MONDAY,
        timezone_name=IST,
        windows=WINDOWS,
        busy=busy,
        rules=SlotRules(30, granularity_minutes=30, min_notice_minutes=0),
        now=EARLY,
    )
    assert all(s.start_at != datetime(2026, 8, 3, 4, 0, tzinfo=UTC) for s in slots)


def test_buffers_widen_the_conflict_window() -> None:
    busy = [Busy(datetime(2026, 8, 3, 4, 30, tzinfo=UTC), datetime(2026, 8, 3, 5, 0, tzinfo=UTC))]
    rules = SlotRules(
        duration_minutes=30,
        buffer_before_minutes=15,
        buffer_after_minutes=15,
        granularity_minutes=30,
        min_notice_minutes=0,
    )
    slots = compute_slots(
        day=MONDAY, timezone_name=IST, windows=WINDOWS, busy=busy, rules=rules, now=EARLY
    )
    starts = {s.start_at for s in slots}
    assert datetime(2026, 8, 3, 4, 0, tzinfo=UTC) not in starts  # buffered out
    assert datetime(2026, 8, 3, 5, 0, tzinfo=UTC) not in starts


def test_capacity_greater_than_one_keeps_the_slot_until_exhausted() -> None:
    busy = [Busy(datetime(2026, 8, 3, 4, 0, tzinfo=UTC), datetime(2026, 8, 3, 4, 30, tzinfo=UTC))]
    slots = compute_slots(
        day=MONDAY,
        timezone_name=IST,
        windows=WINDOWS,
        busy=busy,
        rules=SlotRules(30, capacity=3, granularity_minutes=30, min_notice_minutes=0),
        now=EARLY,
    )
    first = next(s for s in slots if s.start_at == datetime(2026, 8, 3, 4, 0, tzinfo=UTC))
    assert first.remaining_capacity == 2


def test_minimum_notice_hides_imminent_slots() -> None:
    now = datetime(2026, 8, 3, 4, 0, tzinfo=UTC)  # 09:30 IST
    slots = compute_slots(
        day=MONDAY,
        timezone_name=IST,
        windows=WINDOWS,
        busy=[],
        rules=SlotRules(30, granularity_minutes=30, min_notice_minutes=120),
        now=now,
    )
    assert all(s.start_at >= now + timedelta(minutes=120) for s in slots)


def test_holiday_returns_no_slots() -> None:
    slots = compute_slots(
        day=MONDAY,
        timezone_name=IST,
        windows=WINDOWS,
        busy=[],
        rules=SlotRules(min_notice_minutes=0),
        holidays={MONDAY},
        now=EARLY,
    )
    assert slots == []


def test_wrong_weekday_returns_no_slots() -> None:
    slots = compute_slots(
        day=date(2026, 8, 4),
        timezone_name=IST,
        windows=WINDOWS,
        busy=[],
        rules=SlotRules(min_notice_minutes=0),
        now=EARLY,
    )
    assert slots == []


def test_max_advance_horizon_is_enforced() -> None:
    far = MONDAY + timedelta(days=400)
    slots = compute_slots(
        day=far,
        timezone_name=IST,
        windows=[WorkingWindow(far.weekday(), 600, 720)],
        busy=[],
        rules=SlotRules(max_advance_days=60, min_notice_minutes=0),
        now=EARLY,
    )
    assert slots == []


def test_slots_are_dst_safe_in_a_dst_timezone() -> None:
    # 2026-03-08 is the US spring-forward day; 02:00-03:00 local does not exist.
    slots = compute_slots(
        day=date(2026, 3, 8),
        timezone_name="America/New_York",
        windows=[WorkingWindow(6, 60, 300)],
        busy=[],
        rules=SlotRules(30, granularity_minutes=30, min_notice_minutes=0),
        now=datetime(2026, 3, 1, tzinfo=UTC),
    )
    assert len({s.start_at for s in slots}) == len(slots)
    assert slots == sorted(slots, key=lambda s: s.start_at)


class TestRescheduleAndCancel:
    NOW = datetime(2026, 8, 3, 4, 0, tzinfo=UTC)

    def test_reschedule_requires_notice(self) -> None:
        ok, reason = can_reschedule(
            current_start=self.NOW + timedelta(hours=5),
            new_start=self.NOW + timedelta(minutes=10),
            min_notice_minutes=60,
            now=self.NOW,
        )
        assert ok is False and "notice" in str(reason)

    def test_past_appointment_cannot_be_rescheduled(self) -> None:
        ok, reason = can_reschedule(
            current_start=self.NOW - timedelta(hours=1),
            new_start=self.NOW + timedelta(days=1),
            min_notice_minutes=60,
            now=self.NOW,
        )
        assert ok is False and "past" in str(reason)

    def test_valid_reschedule(self) -> None:
        ok, reason = can_reschedule(
            current_start=self.NOW + timedelta(days=1),
            new_start=self.NOW + timedelta(days=2),
            min_notice_minutes=60,
            now=self.NOW,
        )
        assert ok is True and reason is None

    def test_cancellation_cutoff(self) -> None:
        ok, _ = can_cancel(
            start_at=self.NOW + timedelta(minutes=30),
            cancellation_cutoff_minutes=60,
            now=self.NOW,
        )
        assert ok is False
        ok2, _ = can_cancel(
            start_at=self.NOW + timedelta(hours=3),
            cancellation_cutoff_minutes=60,
            now=self.NOW,
        )
        assert ok2 is True
