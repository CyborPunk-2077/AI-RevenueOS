"""Enforce application coverage targets or owned, expiring exceptions."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import yaml


def _normalise(path: str) -> str:
    return path.replace("\\", "/")


def check(coverage_path: Path, policy_path: Path, *, today: date | None = None) -> dict[str, Any]:
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    if not isinstance(policy, dict) or policy.get("version") != 1:
        raise ValueError("coverage policy must have version 1")
    default_target = float(policy["default_target"])
    critical = dict(policy.get("critical_targets", {}))
    ignored = {_normalise(str(path)) for path in policy.get("ignore", [])}
    exceptions = dict(policy.get("exceptions", {}))
    observed = today or date.today()
    failures: list[str] = []
    accepted: list[dict[str, Any]] = []

    for raw_path, details in dict(coverage.get("files", {})).items():
        path = _normalise(str(raw_path))
        if (
            not path.startswith("src/application/")
            or path.endswith("/__init__.py")
            or path in ignored
        ):
            continue
        target = default_target
        for prefix, configured_target in critical.items():
            if path.startswith(_normalise(str(prefix))):
                target = float(configured_target)
        percent = float(details["summary"]["percent_covered"])
        if percent >= target:
            continue
        exception = exceptions.get(path)
        if not isinstance(exception, dict):
            failures.append(f"{path}: {percent:.1f}% is below {target:.1f}% without an exception")
            continue
        owner = str(exception.get("owner", "")).strip()
        reason = str(exception.get("reason", "")).strip()
        expiry = date.fromisoformat(str(exception.get("expires")))
        floor = float(exception.get("floor", target))
        if not owner or not reason:
            failures.append(f"{path}: exception needs an owner and reason")
        elif expiry < observed:
            failures.append(f"{path}: exception owned by {owner} expired on {expiry}")
        elif percent < floor:
            failures.append(f"{path}: {percent:.1f}% regressed below exception floor {floor:.1f}%")
        else:
            accepted.append(
                {
                    "path": path,
                    "percent": round(percent, 2),
                    "target": target,
                    "owner": owner,
                    "expires": expiry.isoformat(),
                }
            )
    return {"passed": not failures, "failures": failures, "exceptions_used": accepted}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage-json", type=Path, required=True)
    parser.add_argument(
        "--policy", type=Path, default=Path(__file__).resolve().parents[2] / "coverage-policy.yaml"
    )
    args = parser.parse_args()
    report = check(args.coverage_json, args.policy)
    print(json.dumps(report, indent=2, sort_keys=True))  # noqa: T201 - release-gate CLI
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
