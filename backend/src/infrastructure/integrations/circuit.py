"""Circuit breaker used by every provider adapter.

Defaults: five consecutive failures within 60s opens for 30s; half-open permits one
trial and closes after three successes. Anthropic uses a tighter 3-failure/15s rule.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from infrastructure.monitoring.metrics import circuit_state


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


_STATE_VALUE = {CircuitState.CLOSED: 0.0, CircuitState.HALF_OPEN: 1.0, CircuitState.OPEN: 2.0}


@dataclass(slots=True)
class CircuitPolicy:
    failure_threshold: int = 5
    failure_window_seconds: float = 60.0
    open_seconds: float = 30.0
    half_open_successes: int = 3
    half_open_max_trials: int = 1


ANTHROPIC_POLICY = CircuitPolicy(failure_threshold=3, failure_window_seconds=15.0)


class CircuitOpen(RuntimeError):
    """Raised when a call is refused because the breaker is open."""

    def __init__(self, provider: str, retry_after: float) -> None:
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(f"circuit open for {provider}; retry in {retry_after:.1f}s")


@dataclass(slots=True)
class CircuitBreaker:
    name: str
    policy: CircuitPolicy = field(default_factory=CircuitPolicy)
    state: CircuitState = CircuitState.CLOSED
    _failures: list[float] = field(default_factory=list)
    _opened_at: float = 0.0
    _half_open_successes: int = 0
    _half_open_trials: int = 0

    def _now(self) -> float:
        return time.monotonic()

    def _publish(self) -> None:
        circuit_state.labels(provider=self.name).set(_STATE_VALUE[self.state])

    def allow(self, *, now: float | None = None) -> bool:
        moment = now if now is not None else self._now()
        if self.state is CircuitState.OPEN:
            if moment - self._opened_at >= self.policy.open_seconds:
                self.state = CircuitState.HALF_OPEN
                self._half_open_successes = 0
                self._half_open_trials = 0
                self._publish()
            else:
                return False
        if self.state is CircuitState.HALF_OPEN:
            if self._half_open_trials >= self.policy.half_open_max_trials:
                return False
            self._half_open_trials += 1
        return True

    def require(self, *, now: float | None = None) -> None:
        if not self.allow(now=now):
            moment = now if now is not None else self._now()
            raise CircuitOpen(
                self.name, max(0.0, self.policy.open_seconds - (moment - self._opened_at))
            )

    def record_success(self, *, now: float | None = None) -> None:
        moment = now if now is not None else self._now()
        if self.state is CircuitState.HALF_OPEN:
            self._half_open_successes += 1
            self._half_open_trials = 0
            if self._half_open_successes >= self.policy.half_open_successes:
                self.state = CircuitState.CLOSED
                self._failures.clear()
        else:
            self._failures = [
                t for t in self._failures if moment - t < self.policy.failure_window_seconds
            ]
        self._publish()

    def record_failure(self, *, now: float | None = None) -> None:
        moment = now if now is not None else self._now()
        if self.state is CircuitState.HALF_OPEN:
            self._trip(moment)
            return
        self._failures = [
            t for t in self._failures if moment - t < self.policy.failure_window_seconds
        ]
        self._failures.append(moment)
        if len(self._failures) >= self.policy.failure_threshold:
            self._trip(moment)
        self._publish()

    def _trip(self, moment: float) -> None:
        self.state = CircuitState.OPEN
        self._opened_at = moment
        self._failures.clear()
        self._half_open_successes = 0
        self._half_open_trials = 0
        self._publish()

    def snapshot(self) -> dict[str, object]:
        return {
            "provider": self.name,
            "state": self.state.value,
            "recent_failures": len(self._failures),
            "half_open_successes": self._half_open_successes,
        }


class CircuitRegistry:
    def __init__(self) -> None:
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str, policy: CircuitPolicy | None = None) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name, policy or (ANTHROPIC_POLICY if name == "anthropic" else CircuitPolicy())
            )
        return self._breakers[name]

    def snapshot(self) -> list[dict[str, object]]:
        return [b.snapshot() for b in self._breakers.values()]

    def reset(self) -> None:
        self._breakers.clear()


registry = CircuitRegistry()
