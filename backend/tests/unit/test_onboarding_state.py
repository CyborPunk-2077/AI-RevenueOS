"""Onboarding transitions are explicit and cannot silently weaken required setup."""

from datetime import UTC, datetime

import pytest

from domain.tenants.onboarding import complete_onboarding, initial_state, transition_step
from shared.exceptions import Conflict, ValidationError

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def test_required_steps_follow_dependencies() -> None:
    state = initial_state()
    with pytest.raises(Conflict) as exc:
        transition_step(state, step_code="industry", target_status="completed", now=NOW)
    assert exc.value.details == {"missing_steps": ["tenant"]}

    for step in ("welcome", "tenant", "industry"):
        state = transition_step(state, step_code=step, target_status="completed", now=NOW)
    assert state["status"] == "in_progress"
    assert state["steps"]["industry"]["status"] == "completed"


def test_required_steps_cannot_be_skipped_or_reopened() -> None:
    with pytest.raises(ValidationError, match="cannot be skipped"):
        transition_step(initial_state(), step_code="welcome", target_status="skipped", now=NOW)

    state = transition_step(
        initial_state(), step_code="welcome", target_status="completed", now=NOW
    )
    with pytest.raises(Conflict, match="move backwards"):
        transition_step(state, step_code="welcome", target_status="in_progress", now=NOW)


def test_optional_steps_may_be_skipped() -> None:
    state = transition_step(initial_state(), step_code="team", target_status="skipped", now=NOW)
    assert state["steps"]["team"]["status"] == "skipped"
    assert state["provider_activation_claimed"] is False


def test_completion_requires_all_required_steps_and_is_terminal() -> None:
    state = initial_state()
    with pytest.raises(Conflict) as exc:
        complete_onboarding(state, now=NOW)
    assert exc.value.details["missing_steps"] == ["welcome", "tenant", "industry"]

    for step in ("welcome", "tenant", "industry"):
        state = transition_step(state, step_code=step, target_status="completed", now=NOW)
    state = complete_onboarding(state, now=NOW)
    assert state["status"] == "completed"
    assert state["completed_at"] == NOW.isoformat()
    with pytest.raises(Conflict, match="cannot be modified"):
        transition_step(state, step_code="team", target_status="skipped", now=NOW)


def test_repeating_the_same_transition_is_a_noop() -> None:
    state = transition_step(
        initial_state(), step_code="welcome", target_status="completed", now=NOW
    )
    assert transition_step(state, step_code="welcome", target_status="completed", now=NOW) == state
