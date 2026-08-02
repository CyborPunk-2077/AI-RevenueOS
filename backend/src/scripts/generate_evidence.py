"""Render a machine-readable index of the human acceptance-evidence matrix."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MATRIX = ROOT / "docs" / "ACCEPTANCE-EVIDENCE.md"
ROW = re.compile(r"^\|\s*(\d{1,2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$")


def build_report(matrix: Path = MATRIX) -> dict[str, Any]:
    criteria: list[dict[str, Any]] = []
    for line in matrix.read_text(encoding="utf-8").splitlines():
        match = ROW.match(line)
        if not match:
            continue
        number = int(match.group(1))
        if not 1 <= number <= 30:
            continue
        criteria.append(
            {
                "criterion": number,
                "requirement": match.group(2).strip(),
                "status": match.group(3).strip(),
                "repository_evidence": match.group(4).strip(),
            }
        )
    numbers = [item["criterion"] for item in criteria]
    if numbers != list(range(1, 31)):
        raise ValueError("Acceptance evidence must contain criteria 1 through 30 exactly once.")
    counts = Counter(str(item["status"]) for item in criteria)
    return {
        "schema_version": "1.0",
        "source": matrix.relative_to(ROOT).as_posix(),
        "source_kind": "repository_evidence_index",
        "live_production_evidence_generated": False,
        "criteria_count": len(criteria),
        "status_counts": dict(sorted(counts.items())),
        "criteria": criteria,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rendered = json.dumps(build_report(), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")  # noqa: T201 - release-evidence CLI
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
