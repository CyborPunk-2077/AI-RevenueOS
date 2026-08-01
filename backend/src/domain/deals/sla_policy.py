"""SLA calculation over tenant business hours and holidays."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from shared.utils.timeutil import to_local, tz, utcnow

DEFAULT_BUSINESS_HOURS: dict[str, Any] = {
    "monday": {"start": "09:30", "end": "18:30"},
    "tuesday": {"start": "09:30", "end": "18:30"},
    "wednesday": {"start": "09:30", "end": "18:30"},
    "thursday": {"start": "09:30", "end": "18:30"},
    "friday": {"start": "09:30", "end": "18:30"},
    "saturday": {"start": "10:00", "end": "14:00"},
    "sunday": None,
}

WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)


@dataclass(frozen=True, slots=True)
class SlaPolicy:
    name: str
    target_minutes: int
    business_hours_only: bool = True
    escalate_after_minutes: int | None = None


DEFAULT_POLICIES: dict[str, SlaPolicy] = {
    "lead_first_response": SlaPolicy("lead_first_response", 60, True, 120),
    "conversation_first_response": SlaPolicy("conversation_first_response", 15, True, 45),
    "task_overdue": SlaPolicy("task_overdue", 0, False, 60),
    "approval_response": SlaPolicy("approval_response", 240, True, 480),
}


def _hhmm(value: str) -> time:
    h, _, m = value.partition(":")
    return time(int(h), int(m or 0))


def _window_for(day: date, business_hours: dict[str, Any]) -> tuple[time, time] | None:
    spec = business_hours.get(WEEKDAYS[day.weekday()])
    if not spec:
        return None
    return _hhmm(spec["start"]), _hhmm(spec["end"])


def add_business_minutes(
    start: datetime,
    minutes: int,
    *,
    timezone_name: str = "Asia/Kolkata",
    business_hours: dict[str, Any] | None = None,
    holidays: set[date] | None = None,
    max_days: int = 90,
) -> datetime:
    """Advance an instant by working minutes, skipping closed days and holidays."""
    hours = business_hours or DEFAULT_BUSINESS_HOURS
    holiday_set = holidays or set()
    zone = tz(timezone_name)
    cursor = to_local(start, timezone_name)
    remaining = minutes

    for _ in range(max_days * 4):
        day = cursor.date()
        window = None if day in holiday_set else _window_for(day, hours)
        if window is None:
            cursor = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
            continue
        open_at = datetime.combine(day, window[0], tzinfo=zone)
        close_at = datetime.combine(day, window[1], tzinfo=zone)
        if cursor < open_at:
            cursor = open_at
        if cursor >= close_at:
            cursor = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
            continue
        available = int((close_at - cursor).total_seconds() // 60)
        if remaining <= available:
            return (cursor + timedelta(minutes=remaining)).astimezone(to_local(start, "UTC").tzinfo)
        remaining -= available
        cursor = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)

    raise ValueError("could not resolve an SLA due time within the configured horizon")


@dataclass(frozen=True, slots=True)
class SlaState:
    policy: str
    started_at: datetime
    due_at: datetime
    resolved_at: datetime | None = None
    escalate_at: datetime | None = None

    def status(self, now: datetime | None = None) -> str:
        moment = now or utcnow()
        if self.resolved_at is not None:
            return "met" if self.resolved_at <= self.due_at else "breached"
        if moment > self.due_at:
            if self.escalate_at and moment > self.escalate_at:
                return "escalated"
            return "breached"
        if moment > self.due_at - timedelta(
            minutes=max(1, (self.due_at - self.started_at).seconds // 240)
        ):
            return "at_risk"
        return "on_track"


def open_sla(
    policy: SlaPolicy,
    started_at: datetime,
    *,
    timezone_name: str = "Asia/Kolkata",
    business_hours: dict[str, Any] | None = None,
    holidays: set[date] | None = None,
) -> SlaState:
    if policy.business_hours_only:
        due = add_business_minutes(
            started_at,
            policy.target_minutes,
            timezone_name=timezone_name,
            business_hours=business_hours,
            holidays=holidays,
        )
        escalate = (
            add_business_minutes(
                started_at,
                policy.escalate_after_minutes,
                timezone_name=timezone_name,
                business_hours=business_hours,
                holidays=holidays,
            )
            if policy.escalate_after_minutes
            else None
        )
    else:
        due = started_at + timedelta(minutes=policy.target_minutes)
        escalate = (
            started_at + timedelta(minutes=policy.escalate_after_minutes)
            if policy.escalate_after_minutes
            else None
        )
    return SlaState(policy.name, started_at, due, None, escalate)
