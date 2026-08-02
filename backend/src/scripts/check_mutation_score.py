"""Fail closed when mutmut's completed domain score is below policy."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_RESULT = Path("mutants/mutmut-cicd-stats.json")
DEFAULT_FLOOR = 0.75
REQUIRED_COUNTS = (
    "killed",
    "survived",
    "total",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)


def evaluate_mutation_stats(stats: dict[str, Any], *, fail_under: float) -> dict[str, Any]:
    if not 0 < fail_under <= 1:
        raise ValueError("fail_under must be greater than zero and at most one")
    counts: dict[str, int] = {}
    for name in REQUIRED_COUNTS:
        value = stats.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"mutation result '{name}' must be a non-negative integer")
        counts[name] = value

    total = counts["total"]
    eligible = total - counts["skipped"]
    if total <= 0 or eligible <= 0:
        raise ValueError("mutation results contain no eligible mutants")
    if counts["check_was_interrupted_by_user"]:
        raise ValueError("mutation run was interrupted")

    classified = sum(
        counts[name]
        for name in ("killed", "survived", "no_tests", "suspicious", "timeout", "segfault")
    )
    if classified != eligible:
        raise ValueError(
            "mutation results are incomplete or contain an unsupported status "
            f"(classified={classified}, eligible={eligible})"
        )

    score = counts["killed"] / eligible
    return {
        "passed": score >= fail_under,
        "score": round(score, 6),
        "fail_under": fail_under,
        "eligible": eligible,
        **counts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stats", type=Path, default=DEFAULT_RESULT)
    parser.add_argument("--fail-under", type=float, default=DEFAULT_FLOOR)
    args = parser.parse_args()
    if not args.stats.is_file():
        parser.error(f"mutation stats not found: {args.stats}; run mutmut first")
    try:
        raw = json.loads(args.stats.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("mutation stats must be a JSON object")
        result = evaluate_mutation_stats(raw, fail_under=args.fail_under)
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
