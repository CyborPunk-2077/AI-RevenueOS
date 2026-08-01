"""Retry classification and exponential backoff with jitter."""

from __future__ import annotations

import random
from dataclasses import dataclass

from shared.compat import StrEnum


class RetryClass(StrEnum):
    TRANSIENT = "transient"  # retry with backoff
    PROVIDER = "provider"  # retry, respecting the circuit breaker
    TERMINAL = "terminal"  # never retry: validation, permission, business rule
    RATE_LIMITED = "rate_limited"


# HTTP status to retry classification. 400/422 payloads are never retried.
STATUS_CLASS: dict[int, RetryClass] = {
    400: RetryClass.TERMINAL,
    401: RetryClass.TERMINAL,
    403: RetryClass.TERMINAL,
    404: RetryClass.TERMINAL,
    409: RetryClass.TERMINAL,
    422: RetryClass.TERMINAL,
    408: RetryClass.TRANSIENT,
    425: RetryClass.TRANSIENT,
    429: RetryClass.RATE_LIMITED,
    500: RetryClass.PROVIDER,
    502: RetryClass.PROVIDER,
    503: RetryClass.PROVIDER,
    504: RetryClass.PROVIDER,
}


def classify_status(status: int) -> RetryClass:
    return STATUS_CLASS.get(status, RetryClass.PROVIDER if status >= 500 else RetryClass.TERMINAL)


def should_retry(retry_class: RetryClass | str, attempt: int, max_attempts: int) -> bool:
    if RetryClass(retry_class) is RetryClass.TERMINAL:
        return False
    return attempt < max_attempts


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    strategy: str = "exponential"  # fixed | exponential | linear
    initial_seconds: float = 1.0
    max_seconds: float = 60.0
    jitter: float = 0.2


def backoff_delay(
    attempt: int, policy: BackoffPolicy | None = None, *, rng: random.Random | None = None
) -> float:
    """Attempt is 1-based. Jitter is proportional and always non-negative."""
    p = policy or BackoffPolicy()
    if attempt < 1:
        raise ValueError("attempt must be 1 or greater")
    if p.strategy == "fixed":
        base = p.initial_seconds
    elif p.strategy == "linear":
        base = p.initial_seconds * attempt
    else:
        base = p.initial_seconds * (2 ** (attempt - 1))
    base = min(base, p.max_seconds)
    source = rng or random
    spread = base * p.jitter
    return max(0.0, base + source.uniform(-spread, spread))
