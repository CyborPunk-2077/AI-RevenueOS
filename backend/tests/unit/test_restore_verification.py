"""The DR orchestrator fails closed and only deletes its own scratch instance."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest


class FakeWaiter:
    def __init__(self, calls: list[tuple[str, dict[str, Any]]], name: str) -> None:
        self.calls = calls
        self.name = name

    def wait(self, **kwargs: Any) -> None:
        self.calls.append((self.name, kwargs))


class FakeRds:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.tags: list[dict[str, str]] = []
        self.target_created = False

    def describe_db_instances(self, **kwargs: Any) -> dict[str, Any]:
        identifier = kwargs["DBInstanceIdentifier"]
        if identifier == "airevenueos-prod":
            return {
                "DBInstances": [
                    {
                        "DBInstanceIdentifier": identifier,
                        "LatestRestorableTime": datetime.now(UTC),
                        "MasterUserSecret": {"SecretArn": "arn:secret:source"},
                        "Endpoint": {"Address": "source.internal", "Port": 5432},
                        "DBName": "airevenueos",
                    }
                ]
            }
        if self.target_created:
            return {
                "DBInstances": [
                    {
                        "DBInstanceIdentifier": identifier,
                        "DBInstanceArn": f"arn:rds:{identifier}",
                        "Endpoint": {"Address": "restore.internal", "Port": 5432},
                    }
                ]
            }
        return {"DBInstances": []}

    def restore_db_instance_to_point_in_time(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("restore", kwargs))
        self.tags = kwargs["Tags"]
        self.target_created = True
        return {"DBInstance": {"DBInstanceIdentifier": kwargs["TargetDBInstanceIdentifier"]}}

    def list_tags_for_resource(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("tags", kwargs))
        return {"TagList": self.tags}

    def delete_db_instance(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete", kwargs))
        return {}

    def get_waiter(self, name: str) -> FakeWaiter:
        return FakeWaiter(self.calls, name)


class FakeSecrets:
    def get_secret_value(self, **kwargs: Any) -> dict[str, str]:
        assert kwargs == {"SecretId": "arn:secret:source"}
        return {"SecretString": json.dumps({"username": "admin", "password": "secret"})}


def _config(tmp_path: Path, **overrides: str) -> Any:
    from scripts.verify_restore import load_config

    env = {
        "SOURCE_DB_INSTANCE_ID": "airevenueos-prod",
        "RESTORE_DB_SUBNET_GROUP": "airevenueos-dr-private",
        "RESTORE_DB_SECURITY_GROUP_IDS": "sg-0123abcd sg-deadbeef",
        "RESTORE_DB_INSTANCE_ID": "airevenueos-dr-unit-test",
        "DR_EVIDENCE_PATH": str(tmp_path / "evidence.json"),
        **overrides,
    }
    return load_config(env)


def test_configuration_is_explicit_and_target_is_safely_namespaced(tmp_path: Path) -> None:
    from scripts.verify_restore import load_config

    with pytest.raises(ValueError, match="missing restore configuration"):
        load_config({})
    with pytest.raises(ValueError, match="must start with airevenueos-dr"):
        _config(tmp_path, RESTORE_DB_INSTANCE_ID="production")


def test_row_reconciliation_accepts_recent_writes_but_rejects_missing_or_future_rows() -> None:
    from scripts.verify_restore import assert_counts_within_tolerance

    source = dict.fromkeys(("tenants", "contacts", "leads", "payments", "consent_records"), 10000)
    restored = dict.fromkeys(source, 9900)
    assert_counts_within_tolerance(source, restored, percent=1, absolute=10)

    with pytest.raises(RuntimeError, match="contacts"):
        assert_counts_within_tolerance(
            source, {**restored, "contacts": 9_000}, percent=1, absolute=10
        )
    with pytest.raises(RuntimeError, match="payments"):
        assert_counts_within_tolerance(
            source, {**restored, "payments": 10_001}, percent=1, absolute=10
        )


def test_complete_drill_uses_private_restore_runs_gates_and_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from scripts import verify_restore

    counts = dict.fromkeys(verify_restore.COUNT_TABLES, 10)
    gate_urls: dict[str, str] = {}
    monkeypatch.setattr(verify_restore, "_row_counts", lambda _dsn: counts.copy())
    monkeypatch.setattr(
        verify_restore,
        "_create_runtime_role",
        lambda _dsn, _run_id: ("runtime", "runtime-pass"),
    )

    def gates(*, admin_url: str, runtime_url: str) -> None:
        gate_urls.update(admin=admin_url, runtime=runtime_url)

    monkeypatch.setattr(verify_restore, "_run_database_gates", gates)
    rds = FakeRds()
    config = _config(tmp_path)
    evidence = verify_restore.run_drill(config, rds=rds, secrets_client=FakeSecrets())

    assert evidence.status == "passed"
    assert evidence.migration_head_verified is True
    assert evidence.rls_suite_verified is True
    assert evidence.cleanup_status == "deleted"
    restore = next(arguments for name, arguments in rds.calls if name == "restore")
    assert restore["PubliclyAccessible"] is False
    assert restore["MultiAZ"] is False
    assert restore["UseLatestRestorableTime"] is True
    assert gate_urls["admin"].startswith("postgresql+psycopg://")
    assert gate_urls["runtime"].startswith("postgresql+asyncpg://runtime:")
    deletion = next(arguments for name, arguments in rds.calls if name == "delete")
    assert deletion == {
        "DBInstanceIdentifier": "airevenueos-dr-unit-test",
        "SkipFinalSnapshot": True,
        "DeleteAutomatedBackups": True,
    }
    persisted = json.loads(config.evidence_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "passed"
    assert "secret" not in json.dumps(persisted)


def test_cleanup_refuses_an_instance_without_exact_ownership_tags() -> None:
    from scripts.verify_restore import _safe_cleanup

    rds = FakeRds()
    rds.target_created = True
    rds.tags = [{"Key": "purpose", "Value": "production"}]
    with pytest.raises(RuntimeError, match="refusing to delete"):
        _safe_cleanup(rds, "airevenueos-dr-unit-test", "unit-test")
    assert not any(name == "delete" for name, _ in rds.calls)


def test_nightly_restore_is_gated_to_a_private_runner_and_preserves_real_evidence() -> None:
    repository = Path(__file__).resolve().parents[3]
    workflow = (repository / ".github" / "workflows" / "nightly.yml").read_text(encoding="utf-8")
    wrapper = (repository / "infra" / "scripts" / "verify-restore.sh").read_text(encoding="utf-8")

    assert "if: vars.AWS_DR_ENABLED == 'true'" in workflow
    assert "runs-on: [self-hosted, linux, dr]" in workflow
    assert "SOURCE_DATABASE_SECRET_ARN" in workflow
    assert "if-no-files-found: error" in workflow
    assert "dr-evidence.json" in workflow
    assert "verify_restore.py" in wrapper
