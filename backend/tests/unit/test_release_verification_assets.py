"""Referenced release verification assets exist and fail closed."""

from __future__ import annotations

from scripts.generate_evidence import build_report
from tests.repo_layout import repository_root

ROOT = repository_root()


def test_acceptance_evidence_generator_indexes_all_criteria_without_live_claims() -> None:
    # The matrix is named explicitly rather than left to the script's own default,
    # which resolves it by counting directories up from `src/scripts/`. That is
    # right in a checkout and lands on `/docs/...` inside a container that mounts
    # only `backend/` - the same shape of bug as the prompt registry's, and it made
    # this test fail for the location it ran in rather than for anything it checks.
    report = build_report(ROOT / "docs" / "ACCEPTANCE-EVIDENCE.md")
    assert report["criteria_count"] == 30
    assert report["live_production_evidence_generated"] is False
    assert [item["criterion"] for item in report["criteria"]] == list(range(1, 31))


def test_k6_peak_and_spike_require_explicit_targets_and_keep_slos() -> None:
    peak = (ROOT / "infra" / "k6" / "peak.js").read_text(encoding="utf-8")
    spike = (ROOT / "infra" / "k6" / "spike.js").read_text(encoding="utf-8")
    assert "BASE_URL and ACCESS_TOKEN are required" in peak
    assert "target: 200" in peak and "p(95)<200" in peak and "p(95)<500" in peak
    assert "target: 400" in spike and "p(95)<300" in spike
    assert "localhost" not in peak and "localhost" not in spike


def test_zap_rules_are_explicit_release_failures() -> None:
    lines = [
        line
        for line in (ROOT / "infra" / "zap" / "rules.tsv").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert len(lines) >= 8
    for line in lines:
        rule_id, action, rationale = line.split("\t", 2)
        assert rule_id.isdigit()
        assert action == "FAIL"
        assert rationale.endswith(".")
