"""Versioned onboarding progress with explicit, monotonic transitions."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.exceptions import Conflict, ValidationError

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class StepDefinition:
    code: str
    required: bool
    dependencies: tuple[str, ...] = ()


STEPS: tuple[StepDefinition, ...] = (
    StepDefinition("welcome", True),
    StepDefinition("tenant", True, ("welcome",)),
    StepDefinition("industry", True, ("tenant",)),
    StepDefinition("channels", False, ("industry",)),
    StepDefinition("team", False, ("tenant",)),
    StepDefinition("billing", False, ("tenant",)),
)
STEP_BY_CODE = {step.code: step for step in STEPS}
STEP_STATUSES = frozenset({"pending", "in_progress", "completed", "skipped"})


def initial_state() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "not_started",
        "provider_activation_claimed": False,
        "steps": {
            step.code: {
                "status": "pending",
                "required": step.required,
                "updated_at": None,
            }
            for step in STEPS
        },
        "completed_at": None,
    }


def normalize_state(value: dict[str, Any] | None) -> dict[str, Any]:
    """Read legacy/partial JSON safely without trusting client-shaped state."""
    state = initial_state()
    raw = value if isinstance(value, dict) else {}
    raw_steps_value = raw.get("steps")
    raw_steps: dict[str, Any] = raw_steps_value if isinstance(raw_steps_value, dict) else {}
    for definition in STEPS:
        candidate = raw_steps.get(definition.code)
        if not isinstance(candidate, dict):
            continue
        status = candidate.get("status")
        if status in STEP_STATUSES:
            state["steps"][definition.code]["status"] = status
        updated_at = candidate.get("updated_at")
        if isinstance(updated_at, str) and len(updated_at) <= 64:
            state["steps"][definition.code]["updated_at"] = updated_at

    if raw.get("status") == "completed" and all(
        state["steps"][step.code]["status"] == "completed" for step in STEPS if step.required
    ):
        state["status"] = "completed"
        completed_at = raw.get("completed_at")
        state["completed_at"] = completed_at if isinstance(completed_at, str) else None
    elif any(item["status"] != "pending" for item in state["steps"].values()):
        state["status"] = "in_progress"
    return state


def transition_step(
    value: dict[str, Any] | None,
    *,
    step_code: str,
    target_status: str,
    now: datetime,
) -> dict[str, Any]:
    state = normalize_state(value)
    if state["status"] == "completed":
        raise Conflict("Completed onboarding cannot be modified.")
    definition = STEP_BY_CODE.get(step_code)
    if definition is None:
        raise ValidationError("Unknown onboarding step.")
    if target_status not in {"in_progress", "completed", "skipped"}:
        raise ValidationError("Invalid onboarding step status.")
    if target_status == "skipped" and definition.required:
        raise ValidationError("Required onboarding steps cannot be skipped.")

    current_status = state["steps"][step_code]["status"]
    if current_status == "completed" and target_status != "completed":
        raise Conflict("Completed onboarding steps cannot move backwards.")
    if current_status == target_status:
        return state
    if target_status == "completed":
        missing = [
            dependency
            for dependency in definition.dependencies
            if state["steps"][dependency]["status"] != "completed"
        ]
        if missing:
            raise Conflict(
                "Onboarding step dependencies are incomplete.", details={"missing_steps": missing}
            )

    updated = deepcopy(state)
    updated["steps"][step_code]["status"] = target_status
    updated["steps"][step_code]["updated_at"] = now.isoformat()
    updated["status"] = "in_progress"
    return updated


def complete_onboarding(value: dict[str, Any] | None, *, now: datetime) -> dict[str, Any]:
    state = normalize_state(value)
    if state["status"] == "completed":
        return state
    missing = [
        step.code
        for step in STEPS
        if step.required and state["steps"][step.code]["status"] != "completed"
    ]
    if missing:
        raise Conflict(
            "Required onboarding steps are incomplete.", details={"missing_steps": missing}
        )
    state["status"] = "completed"
    state["completed_at"] = now.isoformat()
    return state
