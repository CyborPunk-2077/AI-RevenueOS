"""Argon2id password hashing, policy and breach checking."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2 import exceptions as argon2_exceptions
from argon2.low_level import Type

from shared.utils.timeutil import utcnow

# t=3, m=65536, p=4, hash=32, salt=16 - exactly as specified.
_hasher = PasswordHasher(
    time_cost=3, memory_cost=65_536, parallelism=4, hash_len=32, salt_len=16, type=Type.ID
)

MIN_LENGTH = 12
HISTORY_SIZE = 5
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_MINUTES = 15
ADMIN_MAX_AGE_DAYS = 90

_COMMON = frozenset(
    {
        "password",
        "password123",
        "qwerty",
        "letmein",
        "welcome",
        "admin",
        "changeme",
        "iloveyou",
        "monkey",
        "dragon",
        "football",
        "abc123",
        "111111",
        "123456",
        "passw0rd",
        "welcome1",
        "india123",
        "airevenueos",
    }
)


@dataclass(slots=True)
class PasswordCheck:
    ok: bool
    problems: list[str] = field(default_factory=list)


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, plain)
    except (
        argon2_exceptions.VerifyMismatchError,
        argon2_exceptions.VerificationError,
        argon2_exceptions.InvalidHashError,
    ):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except argon2_exceptions.InvalidHashError:
        return True


def validate_password(
    plain: str, *, email: str | None = None, full_name: str | None = None
) -> PasswordCheck:
    problems: list[str] = []
    if len(plain) < MIN_LENGTH:
        problems.append(f"Password must be at least {MIN_LENGTH} characters.")
    if len(plain) > 256:
        problems.append("Password must be at most 256 characters.")
    lowered = plain.lower()
    if lowered in _COMMON:
        problems.append("This password is too common.")
    if email and email.split("@")[0].lower() in lowered and len(email.split("@")[0]) > 3:
        problems.append("Password must not contain your email address.")
    if full_name:
        for part in full_name.lower().split():
            if len(part) > 3 and part in lowered:
                problems.append("Password must not contain your name.")
                break
    if re.fullmatch(r"(.)\1+", plain):
        problems.append("Password must not be a single repeated character.")
    if len(set(plain)) < 5:
        problems.append("Password must use a wider variety of characters.")
    return PasswordCheck(not problems, problems)


def hibp_prefix(plain: str) -> tuple[str, str]:
    """k-anonymity range query: only the first five SHA-1 characters leave the system."""
    digest = hashlib.sha1(plain.encode(), usedforsecurity=False).hexdigest().upper()
    return digest[:5], digest[5:]


def is_in_history(plain: str, history: list[str]) -> bool:
    return any(verify_password(plain, previous) for previous in history[:HISTORY_SIZE])


def push_history(current_hash: str | None, history: list[str]) -> list[str]:
    updated = ([current_hash] if current_hash else []) + list(history)
    return updated[:HISTORY_SIZE]


def lockout_state(failed_count: int, locked_until: datetime | None) -> tuple[bool, int]:
    """Returns (locked, seconds_remaining).

    A lock window that has run its term is over, and an expired window no longer
    falls through to the counter below. It used to, and the counter still read
    MAX_FAILED_ATTEMPTS because only a *successful* login clears it - which the
    lock itself made impossible. A lockout advertised as temporary was therefore
    permanent, renewed silently every time it was checked.

    The window is the authority whenever one exists. The counter is consulted
    only when no window was ever opened, where it stays as a guard against a
    caller that raises the count without calling `next_lockout`.
    """
    now = utcnow()
    if locked_until is not None:
        if locked_until > now:
            return True, int((locked_until - now).total_seconds())
        return False, 0
    return failed_count >= MAX_FAILED_ATTEMPTS, 0


def effective_failed_count(failed_count: int, locked_until: datetime | None) -> int:
    """The count that the next attempt builds on.

    Serving the lockout is the penalty, so an expired window retires the counter
    that opened it. Without this, the first wrong password after an expiry would
    carry 5 to 6 and re-lock instantly - the same trap as the one above, merely
    reached one attempt later instead of zero.
    """
    if locked_until is not None and locked_until <= utcnow():
        return 0
    return failed_count


def next_lockout(failed_count: int) -> datetime | None:
    if failed_count + 1 >= MAX_FAILED_ATTEMPTS:
        return utcnow() + timedelta(minutes=LOCKOUT_MINUTES)
    return None


def password_expired(
    *, is_admin_role: bool, password_changed_at: datetime | None, now: datetime | None = None
) -> bool:
    """Admin passwords expire after 90 days; standard user passwords do not expire."""
    if not is_admin_role:
        return False
    if password_changed_at is None:
        return True
    return (now or utcnow()) - password_changed_at > timedelta(days=ADMIN_MAX_AGE_DAYS)
