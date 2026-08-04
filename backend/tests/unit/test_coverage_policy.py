"""Owned coverage exceptions must be explicit, non-regressing, and unexpired."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from scripts.check_coverage_policy import check


def test_owned_exception_temporarily_satisfies_a_module_target(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    policy = tmp_path / "policy.yaml"
    coverage.write_text(
        json.dumps(
            {"files": {"src/application/example.py": {"summary": {"percent_covered": 72.5}}}}
        ),
        encoding="utf-8",
    )
    policy.write_text(
        """version: 1
default_target: 85
exceptions:
  src/application/example.py:
    owner: platform
    expires: 2026-09-30
    floor: 70
    reason: focused branches are scheduled
""",
        encoding="utf-8",
    )
    report = check(coverage, policy, today=date(2026, 8, 2))
    assert report["passed"] is True
    assert report["exceptions_used"][0]["owner"] == "platform"


def test_expired_or_regressed_exception_fails(tmp_path: Path) -> None:
    coverage = tmp_path / "coverage.json"
    policy = tmp_path / "policy.yaml"
    coverage.write_text(
        json.dumps(
            {"files": {"src/application/example.py": {"summary": {"percent_covered": 65.0}}}}
        ),
        encoding="utf-8",
    )
    policy.write_text(
        """version: 1
default_target: 85
exceptions:
  src/application/example.py:
    owner: platform
    expires: 2026-08-01
    floor: 70
    reason: focused branches are scheduled
""",
        encoding="utf-8",
    )
    report = check(coverage, policy, today=date(2026, 8, 2))
    assert report["passed"] is False
    assert "expired" in report["failures"][0]
