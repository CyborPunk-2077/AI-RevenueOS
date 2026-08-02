"""Run versioned offline prompt and guard gold sets without contacting providers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from application.ai.prompt_registry import evaluate_prompt_document, load_git_prompts


def run(*, fail_under: float) -> dict[str, Any]:
    evaluations = [evaluate_prompt_document(document) for document in load_git_prompts()]
    aggregate = sum(float(item["score"]) for item in evaluations) / len(evaluations)
    passed = aggregate >= fail_under and all(bool(item["passed"]) for item in evaluations)
    return {
        "schema_version": "1.0",
        "evaluation_kind": "deterministic_prompt_and_guard_contracts",
        "provider_called": False,
        "model_quality_claimed": False,
        "prompt_count": len(evaluations),
        "aggregate_score": aggregate,
        "fail_under": fail_under,
        "passed": passed,
        "evaluations": evaluations,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fail-under", type=float, default=0.85)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not 0 <= args.fail_under <= 1:
        parser.error("--fail-under must be between 0 and 1")
    report = run(fail_under=args.fail_under)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.report:
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)  # noqa: T201 - release-gate CLI output
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
