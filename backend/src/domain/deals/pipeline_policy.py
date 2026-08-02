"""Opportunity stage and status rules. Invalid stage moves fail loudly."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from domain.base import InvalidTransition, PolicyViolation


class DealStatus(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"
    ABANDONED = "abandoned"


ALLOWED_STATUS_TRANSITIONS: dict[DealStatus, frozenset[DealStatus]] = {
    DealStatus.OPEN: frozenset({DealStatus.WON, DealStatus.LOST, DealStatus.ABANDONED}),
    DealStatus.WON: frozenset({DealStatus.OPEN}),  # reopen, audited
    DealStatus.LOST: frozenset({DealStatus.OPEN}),
    DealStatus.ABANDONED: frozenset({DealStatus.OPEN}),
}

CLOSED_STATUSES = frozenset({DealStatus.WON, DealStatus.LOST, DealStatus.ABANDONED})


@dataclass(frozen=True, slots=True)
class StageSpec:
    id: str
    name: str
    position: int
    probability: int = 0
    required_fields: tuple[str, ...] = ()
    is_won: bool = False
    is_lost: bool = False
    allow_skip_forward: bool = True
    allow_backward: bool = True


@dataclass(frozen=True, slots=True)
class StageMoveRequest:
    from_stage: StageSpec
    to_stage: StageSpec
    deal_fields: dict[str, Any] = field(default_factory=dict)
    loss_reason: str | None = None
    status: DealStatus = DealStatus.OPEN


@dataclass(frozen=True, slots=True)
class StageMoveResult:
    stage_id: str
    status: DealStatus
    probability: int
    missing_required_fields: tuple[str, ...] = ()


def validate_stage_move(request: StageMoveRequest) -> StageMoveResult:
    """Enforces required fields, loss reasons and configured direction rules."""
    src, dst = request.from_stage, request.to_stage

    if request.status in CLOSED_STATUSES and not (dst.is_won or dst.is_lost):
        raise InvalidTransition("a closed opportunity must be reopened before moving stage")

    if dst.position < src.position and not src.allow_backward:
        raise InvalidTransition(f"moving back from {src.name} is not permitted")
    if dst.position > src.position + 1 and not src.allow_skip_forward:
        raise InvalidTransition(f"stages cannot be skipped after {src.name}")

    missing = tuple(
        f for f in dst.required_fields if request.deal_fields.get(f) in (None, "", [], {})
    )
    if missing:
        raise PolicyViolation(f"stage '{dst.name}' requires: {', '.join(missing)}")

    if dst.is_lost and not request.loss_reason:
        raise PolicyViolation("a loss reason is required to move to a lost stage")

    status = DealStatus.OPEN
    if dst.is_won:
        status = DealStatus.WON
    elif dst.is_lost:
        status = DealStatus.LOST

    return StageMoveResult(
        stage_id=dst.id, status=status, probability=dst.probability, missing_required_fields=()
    )


def assert_status_transition(current: DealStatus | str, target: DealStatus | str) -> DealStatus:
    cur, tgt = DealStatus(current), DealStatus(target)
    if cur == tgt:
        return tgt
    if tgt not in ALLOWED_STATUS_TRANSITIONS[cur]:
        raise InvalidTransition(f"cannot move an opportunity from {cur.value} to {tgt.value}")
    return tgt


def weighted_pipeline_value(deals: list[dict[str, Any]]) -> int:
    """Sum of amount_minor * probability for open opportunities only."""
    return sum(
        int(d.get("amount_minor", 0)) * int(d.get("probability", 0)) // 100
        for d in deals
        if DealStatus(d.get("status", "open")) is DealStatus.OPEN
    )
