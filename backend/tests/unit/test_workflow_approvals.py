from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from application.workflows.approvals import _matching_assignees, _resolved_state


def test_assignees_match_exact_user_and_current_roles() -> None:
    user_id = uuid4()
    principal = SimpleNamespace(user_id=user_id, roles=("manager", "member"))

    assert _matching_assignees([f"user:{user_id}", "role:manager", "role:owner"], principal) == {
        f"user:{user_id}",
        "role:manager",
    }


def test_any_strategy_resolves_on_first_decision() -> None:
    assert _resolved_state("any", 1, ["role:a"], [{"decision": "approved"}]) == "approved"
    assert _resolved_state("any", 1, ["role:a"], [{"decision": "rejected"}]) == "rejected"


def test_all_strategy_requires_every_assignee_and_rejection_wins() -> None:
    assignees = ["role:a", "role:b"]
    assert (
        _resolved_state(
            "all",
            1,
            assignees,
            [{"decision": "approved", "assignees": ["role:a"]}],
        )
        is None
    )
    assert (
        _resolved_state(
            "all",
            1,
            assignees,
            [
                {"decision": "approved", "assignees": ["role:a"]},
                {"decision": "approved", "assignees": ["role:b"]},
            ],
        )
        == "approved"
    )
    assert _resolved_state("all", 1, assignees, [{"decision": "rejected"}]) == "rejected"


def test_quorum_resolves_when_met_or_impossible() -> None:
    assignees = ["user:a", "user:b", "user:c"]
    assert _resolved_state("quorum", 2, assignees, [{"decision": "approved"}]) is None
    assert (
        _resolved_state(
            "quorum",
            2,
            assignees,
            [{"decision": "approved"}, {"decision": "approved"}],
        )
        == "approved"
    )
    assert (
        _resolved_state(
            "quorum",
            2,
            assignees,
            [{"decision": "rejected"}, {"decision": "rejected"}],
        )
        == "rejected"
    )
