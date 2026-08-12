"""Alert rules are executable, owned and linked to a real response runbook."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import hcl2
import yaml

from tests.repo_layout import repository_root

ROOT = repository_root()
RULES_PATH = ROOT / "infra" / "monitoring" / "alerts.yml"
PROMETHEUS_PATH = ROOT / "infra" / "monitoring" / "prometheus.yml"
RUNBOOK_PATH = ROOT / "docs" / "runbooks" / "alerts.md"
DATA_TERRAFORM = ROOT / "infra" / "terraform" / "modules" / "data" / "main.tf"
EDGE_TERRAFORM = ROOT / "infra" / "terraform" / "modules" / "edge" / "main.tf"


def _rules() -> list[dict[str, Any]]:
    document = yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))
    return [rule for group in document["groups"] for rule in group["rules"]]


def test_prometheus_loads_the_repository_alert_file() -> None:
    config = yaml.safe_load(PROMETHEUS_PATH.read_text(encoding="utf-8"))
    assert "/etc/prometheus/alerts.yml" in config["rule_files"]
    assert config["scrape_configs"][0]["metrics_path"] == "/health/metrics"


def test_every_alert_has_an_owner_severity_duration_and_existing_runbook() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8").lower()
    rules = _rules()
    assert rules
    for rule in rules:
        assert rule["alert"].startswith("Airev")
        assert str(rule["expr"]).strip()
        assert rule["for"]
        assert rule["labels"]["severity"] in {"warning", "critical"}
        assert rule["labels"]["owner"].endswith("-team")
        target = rule["annotations"]["runbook"]
        path, anchor = target.split("#", maxsplit=1)
        assert path == "docs/runbooks/alerts.md"
        assert f"## {anchor.replace('-', ' ')}" in runbook


def test_required_operational_signals_have_rules() -> None:
    expressions = "\n".join(str(rule["expr"]) for rule in _rules())
    for metric in (
        "airev_http_request_seconds_bucket",
        "airev_http_requests_total",
        "airev_queue_depth",
        "airev_queue_age_seconds",
        "airev_dlq_size",
        "airev_worker_heartbeat_timestamp",
        "airev_circuit_state",
        "airev_provider_calls_total",
        "airev_ai_budget_utilization_ratio",
        "airev_tenant_isolation_violations_total",
    ):
        assert metric in expressions


def test_ai_budget_metric_is_exported_for_the_alert_expression() -> None:
    from infrastructure.monitoring.metrics import ai_budget_utilization_ratio, render_metrics

    ai_budget_utilization_ratio.labels(tenant_id="test-tenant").set(0.81)
    body, _ = render_metrics()
    rendered = body.decode("utf-8")
    assert 'airev_ai_budget_utilization_ratio{tenant_id="test-tenant"} 0.81' in rendered


def test_warning_and_critical_thresholds_exist_for_latency_depth_and_age() -> None:
    rules = _rules()
    by_prefix = {
        prefix: {rule["labels"]["severity"] for rule in rules if prefix in rule["alert"]}
        for prefix in ("ApiP95Latency", "QueueDepth", "QueueAge")
    }
    assert all(severities == {"warning", "critical"} for severities in by_prefix.values())


def test_aws_owned_backup_and_waf_signals_have_cloudwatch_alarms() -> None:
    data = DATA_TERRAFORM.read_text(encoding="utf-8")
    edge = EDGE_TERRAFORM.read_text(encoding="utf-8")
    assert 'metric_name         = "NumberOfBackupJobsFailed"' in data
    assert 'metric_name         = "NumberOfRecoveryPointsPartial"' in data
    assert "enable_continuous_backup = true" in data
    assert 'metric_name         = "BlockedRequests"' in edge
    assert 'scope = "REGIONAL"' in edge
    assert "aws_wafv2_web_acl_association" in edge
    assert "alarm_actions = [var.alarm_topic_arn]" in data
    assert "alarm_actions = [var.alarm_topic_arn]" in edge


def test_all_terraform_files_are_valid_hcl() -> None:
    terraform_root = ROOT / "infra" / "terraform"
    files = list(terraform_root.rglob("*.tf"))
    assert files
    for path in files:
        with path.open(encoding="utf-8") as handle:
            assert hcl2.load(handle)
