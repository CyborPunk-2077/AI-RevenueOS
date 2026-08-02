"""Mutation score policy rejects weak, missing and incomplete evidence."""

from __future__ import annotations

import pytest

from scripts.check_mutation_score import evaluate_mutation_stats


def _stats(**changes: int) -> dict[str, int]:
    result = {
        "killed": 80,
        "survived": 15,
        "total": 100,
        "no_tests": 0,
        "skipped": 5,
        "suspicious": 0,
        "timeout": 0,
        "check_was_interrupted_by_user": 0,
        "segfault": 0,
    }
    result.update(changes)
    return result


def test_mutation_policy_accepts_score_at_or_above_floor() -> None:
    result = evaluate_mutation_stats(_stats(), fail_under=0.75)
    assert result["passed"] is True
    assert result["score"] == pytest.approx(80 / 95)


def test_mutation_policy_counts_untested_and_runtime_failures_against_score() -> None:
    result = evaluate_mutation_stats(
        _stats(killed=70, survived=10, no_tests=5, timeout=5, suspicious=5), fail_under=0.75
    )
    assert result["passed"] is False
    assert result["eligible"] == 95


def test_mutation_policy_rejects_incomplete_or_interrupted_results() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        evaluate_mutation_stats(_stats(total=101), fail_under=0.75)
    with pytest.raises(ValueError, match="interrupted"):
        evaluate_mutation_stats(_stats(check_was_interrupted_by_user=1), fail_under=0.75)


@pytest.mark.parametrize("bad_floor", [0.0, -0.1, 1.01])
def test_mutation_policy_rejects_invalid_floor(bad_floor: float) -> None:
    with pytest.raises(ValueError, match="fail_under"):
        evaluate_mutation_stats(_stats(), fail_under=bad_floor)
