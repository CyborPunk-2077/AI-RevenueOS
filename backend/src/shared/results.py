"""Result type used by application services that must not raise for expected failures."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Ok[T]:
    value: T

    @property
    def is_ok(self) -> bool:
        return True

    def unwrap(self) -> T:
        return self.value


@dataclass(frozen=True, slots=True)
class Err[E]:
    error: E

    @property
    def is_ok(self) -> bool:
        return False

    def unwrap(self) -> None:
        raise ValueError(f"Attempted to unwrap an Err: {self.error!r}")


type Result[T, E] = Ok[T] | Err[E]
