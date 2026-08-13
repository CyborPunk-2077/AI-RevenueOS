"""The mutation gate is pinned, scheduled and fail-closed as one contract."""

from __future__ import annotations

import tomllib

import yaml

from tests.repo_layout import repository_root

ROOT = repository_root()


def test_mutmut_is_pinned_and_scoped_to_domain_including_auth() -> None:
    config = tomllib.loads((ROOT / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert "mutmut==3.6.0" in config["project"]["optional-dependencies"]["dev"]
    assert config["tool"]["mutmut"]["source_paths"] == ["src/domain/"]
    assert (ROOT / "backend" / "src" / "domain" / "auth").is_dir()
    assert "mutmut==3.6.0" in (ROOT / "backend" / "requirements-dev.lock").read_text(
        encoding="utf-8"
    )


def test_nightly_workflow_exports_and_enforces_raw_stats() -> None:
    workflow_path = ROOT / ".github" / "workflows" / "nightly.yml"
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    job = workflow["jobs"]["mutation"]
    commands = "\n".join(
        str(step.get("run", "")) for step in job["steps"] if isinstance(step, dict)
    )
    assert "mutmut run" in commands
    assert "mutmut export-cicd-stats" in commands
    assert "check_mutation_score.py --fail-under 0.75" in commands
    artifact = next(
        step for step in job["steps"] if step.get("name") == "Preserve mutation evidence"
    )
    assert artifact["with"]["if-no-files-found"] == "error"


def test_policy_runbook_never_claims_an_unexecuted_score() -> None:
    runbook = (ROOT / "docs" / "runbooks" / "mutation-testing.md").read_text(encoding="utf-8")
    assert "Do not claim the target" in runbook
    assert "mutmut-cicd-stats.json" in runbook
