"""Availability computation. Database uniqueness - not this module - stops double booking.

This module decides which slots may be offered; the concurrency guarantee comes from
the `slot_locks` unique constraint on (tenant, resource, start_at, slot_index).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from shared.utils.timeutil import ensure_utc, resolve_local_instant, tz, utcnow


@dataclass(frozen=True, slots=True)
class WorkingWindow:
    day_of_week: int  # 0 = Monday
    start_minute: int
    end_minute: int


@dataclass(frozen=True, slots=True)
class Busy:
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True, slots=True)
class SlotRules:
    duration_minutes: int = 30
    buffer_before_minutes: int = 0
    buffer_after_minutes: int = 0
    capacity: int = 1
    granularity_minutes: int = 15
    min_notice_minutes: int = 60
    max_advance_days: int = 60


@dataclass(frozen=True, slots=True)
class Slot:
    start_at: datetime
    end_at: datetime
    remaining_capacity: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "start_at": self.start_at.isoformat(),
            "end_at": self.end_at.isoformat(),
            "remaining_capacity": self.remaining_capacity,
        }


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def compute_slots(
    *,
    day: date,
    timezone_name: str,
    windows: list[WorkingWindow],
    busy: list[Busy],
    rules: SlotRules,
    holidays: set[date] | None = None,
    now: datetime | None = None,
) -> list[Slot]:
    """Generate bookable slots for one local calendar day, DST-safe."""
    moment = ensure_utc(now or utcnow())
    if holidays and day in holidays:
        return []
    if day > (moment.astimezone(tz(timezone_name)).date() + timedelta(days=rules.max_advance_days)):
        return []

    earliest = moment + timedelta(minutes=rules.min_notice_minutes)
    day_windows = [w for w in windows if w.day_of_week == day.weekday()]
    slots: list[Slot] = []

    for window in day_windows:
        cursor = window.start_minute
        while cursor + rules.duration_minutes <= window.end_minute:
            start_local = time(hour=cursor // 60, minute=cursor % 60)
            start_at = resolve_local_instant(day, start_local, timezone_name)

            # A local time that does not exist (DST spring forward) is skipped rather
            # than collapsed onto its neighbour, which would offer a duplicate slot.
            if start_at.astimezone(tz(timezone_name)).time() != start_local:
                cursor += rules.granularity_minutes
                continue

            end_at = start_at + timedelta(minutes=rules.duration_minutes)

            guard_start = start_at - timedelta(minutes=rules.buffer_before_minutes)
            guard_end = end_at + timedelta(minutes=rules.buffer_after_minutes)

            if start_at >= earliest:
                taken = sum(
                    1 for b in busy if _overlaps(guard_start, guard_end, b.start_at, b.end_at)
                )
                remaining = rules.capacity - taken
                if remaining > 0:
                    slots.append(Slot(start_at, end_at, remaining))

            cursor += rules.granularity_minutes

    return sorted(slots, key=lambda s: s.start_at)


def slot_index_for(start_at: datetime, taken: int) -> int:
    """Capacity > 1 is modelled as parallel indexed locks on the same start instant."""
    return taken


def can_reschedule(
    *,
    current_start: datetime,
    new_start: datetime,
    min_notice_minutes: int,
    now: datetime | None = None,
) -> tuple[bool, str | None]:
    moment = ensure_utc(now or utcnow())
    if ensure_utc(current_start) <= moment:
        return False, "past appointments cannot be rescheduled"
    if ensure_utc(new_start) < moment + timedelta(minutes=min_notice_minutes):
        return False, f"reschedule requires at least {min_notice_minutes} minutes notice"
    return True, None


def can_cancel(
    *, start_at: datetime, cancellation_cutoff_minutes: int = 0, now: datetime | None = None
) -> tuple[bool, str | None]:
    moment = ensure_utc(now or utcnow())
    if ensure_utc(start_at) - timedelta(minutes=cancellation_cutoff_minutes) < moment:
        return False, "the cancellation window for this appointment has closed"
    return True, None
