"""Assignment: first matching rule wins, and nobody is invented as an owner."""

from __future__ import annotations

from typing import Any

import pytest

from domain.leads.assignment import rule_matches, select_assignee, validate_rule
from shared.exceptions import ValidationError

ASHA = "018f0000-0000-7000-8000-00000000000a"
RAHUL = "018f0000-0000-7000-8000-00000000000b"
PRIYA = "018f0000-0000-7000-8000-00000000000c"


def rule(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "rule-1",
        "name": "Web leads",
        "strategy": "round_robin",
        "conditions": {"all": [{"field": "source", "operator": "equals", "value": "web_form"}]},
        "targets": [ASHA, RAHUL],
        "position": 0,
        "is_active": True,
        "cursor": 0,
    }
    base.update(over)
    return base


class TestValidation:
    def test_a_rule_with_no_assignee_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_rule(strategy="round_robin", conditions={}, targets=[])

    def test_an_unknown_strategy_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_rule(strategy="astrology", conditions={}, targets=[ASHA])

    def test_a_condition_on_an_unreadable_field_is_refused(self) -> None:
        """A rule reading arbitrary capture keys stops matching when a form is renamed."""
        with pytest.raises(ValidationError):
            validate_rule(
                strategy="round_robin",
                conditions={
                    "all": [{"field": "capture.utm_term", "operator": "equals", "value": "x"}]
                },
                targets=[ASHA],
            )

    def test_a_repeated_assignee_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            validate_rule(strategy="round_robin", conditions={}, targets=[ASHA, ASHA])

    def test_a_valid_rule_normalises(self) -> None:
        conditions, targets = validate_rule(
            strategy="round_robin",
            conditions={"all": [{"field": "source", "operator": "equals", "value": "web_form"}]},
            targets=[ASHA],
        )
        assert conditions == {
            "all": [{"field": "source", "operator": "equals", "value": "web_form"}]
        }
        assert targets == [ASHA]


class TestMatching:
    def test_a_rule_with_no_conditions_is_a_catch_all(self) -> None:
        assert rule_matches(rule(conditions={}), {"source": "anything"}) is True

    def test_comparison_is_case_insensitive(self) -> None:
        """`Web` and `web` are the same source to a human."""
        assert rule_matches(rule(), {"source": "WEB_FORM"}) is True

    def test_a_missing_field_does_not_match(self) -> None:
        assert rule_matches(rule(), {}) is False

    @pytest.mark.parametrize(
        ("operator", "value", "actual", "expected"),
        [
            ("contains", "form", "web_form", True),
            ("starts_with", "web", "web_form", True),
            ("starts_with", "form", "web_form", False),
            ("in", ["web_form", "chat"], "chat", True),
            ("not_equals", "web_form", "chat", True),
            ("is_set", None, "chat", True),
            ("is_not_set", None, None, True),
        ],
    )
    def test_operators(self, operator: str, value: Any, actual: Any, expected: bool) -> None:
        matcher = rule(
            conditions={"all": [{"field": "source", "operator": operator, "value": value}]}
        )
        assert rule_matches(matcher, {"source": actual}) is expected

    def test_numeric_comparison_stays_numeric(self) -> None:
        matcher = rule(
            conditions={
                "all": [{"field": "qualification_score", "operator": "equals", "value": 80}]
            }
        )
        assert rule_matches(matcher, {"qualification_score": 80}) is True


class TestSelection:
    def test_no_match_leaves_the_lead_unassigned(self) -> None:
        """Inventing an owner is how leads end up with someone who never agreed."""
        assert select_assignee([rule()], {"source": "chat"}) is None

    def test_the_first_matching_rule_wins(self) -> None:
        first = rule(id="a", position=0, targets=[ASHA], conditions={})
        second = rule(id="b", position=1, targets=[RAHUL], conditions={})
        decision = select_assignee([second, first], {"source": "web_form"})
        assert decision is not None and decision.assignee_id == ASHA

    def test_an_inactive_rule_is_skipped(self) -> None:
        decision = select_assignee(
            [rule(is_active=False), rule(id="b", position=1, conditions={}, targets=[PRIYA])],
            {"source": "web_form"},
        )
        assert decision is not None and decision.assignee_id == PRIYA

    def test_round_robin_advances_and_wraps(self) -> None:
        first = select_assignee([rule(cursor=0)], {"source": "web_form"})
        assert first is not None and first.assignee_id == ASHA and first.next_cursor == 1

        second = select_assignee([rule(cursor=1)], {"source": "web_form"})
        assert second is not None and second.assignee_id == RAHUL and second.next_cursor == 0

    def test_load_balanced_picks_the_lightest_queue(self) -> None:
        decision = select_assignee(
            [rule(strategy="load_balanced")],
            {"source": "web_form"},
            workloads={ASHA: 12, RAHUL: 3},
        )
        assert decision is not None and decision.assignee_id == RAHUL

    def test_first_available_never_moves(self) -> None:
        decision = select_assignee(
            [rule(strategy="first_available", cursor=7)], {"source": "web_form"}
        )
        assert decision is not None
        assert decision.assignee_id == ASHA
        assert decision.next_cursor is None

    def test_a_departed_target_stops_receiving_work(self) -> None:
        decision = select_assignee([rule()], {"source": "web_form"}, eligible={RAHUL})
        assert decision is not None and decision.assignee_id == RAHUL

    def test_a_rule_whose_targets_have_all_left_is_skipped(self) -> None:
        decision = select_assignee(
            [rule(), rule(id="b", position=1, conditions={}, targets=[PRIYA])],
            {"source": "web_form"},
            eligible={PRIYA},
        )
        assert decision is not None and decision.assignee_id == PRIYA
