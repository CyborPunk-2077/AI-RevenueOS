"""All stored instants are UTC. Display uses the user or tenant IANA timezone."""

from __future__ import annotations

from datetime import UTC as UTC
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TZ = "Asia/Kolkata"


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetime is not permitted; instants must be timezone aware")
    return value.astimezone(UTC)


def tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or DEFAULT_TZ)
    except ZoneInfoNotFoundError:
        return ZoneInfo(DEFAULT_TZ)


def to_local(value: datetime, tz_name: str | None = DEFAULT_TZ) -> datetime:
    return ensure_utc(value).astimezone(tz(tz_name))


def local_day_bounds(day: date, tz_name: str = DEFAULT_TZ) -> tuple[datetime, datetime]:
    """Return the UTC half-open interval covering a local calendar day."""
    zone = tz(tz_name)
    start_local = datetime.combine(day, time.min, tzinfo=zone)
    end_local = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def resolve_local_instant(day: date, at: time, tz_name: str) -> datetime:
    """DST-safe local -> UTC resolution.

    Nonexistent local times (spring forward) move to the next valid instant.
    Ambiguous local times (fall back) resolve to the later occurrence.
    """
    zone = tz(tz_name)
    naive = datetime.combine(day, at)
    candidate = naive.replace(tzinfo=zone)

    # Nonexistent (spring forward): the wall time does not survive a UTC round trip.
    # This must be checked before ambiguity, because both cases have two offsets.
    if candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != naive:
        probe = naive
        for _ in range(24 * 4):
            probe += timedelta(minutes=15)
            moved = probe.replace(tzinfo=zone)
            if moved.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == probe:
                return moved.astimezone(UTC)
        raise ValueError("could not resolve a valid local instant")

    # Ambiguous (fall back): prefer the later occurrence.
    later = naive.replace(tzinfo=zone, fold=1)
    if candidate.utcoffset() != later.utcoffset():
        return later.astimezone(UTC)

    return candidate.astimezone(UTC)


def iso(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")
