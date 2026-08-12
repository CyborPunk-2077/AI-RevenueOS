"""Non-production environments must differ from production only where intended.

An environment that quietly drops Multi-AZ, encryption, or the private data tier is
worse than no environment: it produces evidence that does not transfer. These tests
pin the differences that are deliberate and fail on the ones that are not.

They are static checks on the Terraform source. Nothing here proves a `plan` or an
`apply` - no AWS account exists yet, and gate 4.1 remains open.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import hcl2
import pytest

from tests.repo_layout import repository_root

ROOT = repository_root()
ENVS = ROOT / "infra" / "terraform" / "envs"
NON_PRODUCTION = ("dev", "staging", "sandbox")
ALL_ENVIRONMENTS = ("prod", *NON_PRODUCTION)

# Disposable environments must be destroyable; the durable ones must not be.
DISPOSABLE = ("dev", "sandbox")


def _document(environment: str) -> dict[str, Any]:
    with (ENVS / environment / "main.tf").open(encoding="utf-8") as handle:
        loaded: dict[str, Any] = hcl2.load(handle)
    return loaded


def _blocks(document: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [block for block in document.get(kind, []) if isinstance(block, dict)]


def _module(environment: str, name: str) -> dict[str, Any]:
    for block in _blocks(_document(environment), "module"):
        # Some hcl2 versions keep the block label quoted; accept either shape.
        for key in (name, f'"{name}"'):
            if key in block:
                body: dict[str, Any] = block[key]
                return body
    raise AssertionError(f"{environment} declares no module {name!r}")


def _source(environment: str) -> str:
    return (ENVS / environment / "main.tf").read_text(encoding="utf-8")


class TestEveryEnvironmentExists:
    @pytest.mark.parametrize("environment", ALL_ENVIRONMENTS)
    def test_the_environment_is_present_and_parses(self, environment: str) -> None:
        assert (ENVS / environment / "main.tf").is_file()
        assert _document(environment)

    @pytest.mark.parametrize("environment", NON_PRODUCTION)
    def test_variables_and_outputs_are_split_out(self, environment: str) -> None:
        assert (ENVS / environment / "variables.tf").is_file()
        assert (ENVS / environment / "outputs.tf").is_file()


class TestIsolation:
    def test_state_is_never_shared_between_environments(self) -> None:
        """Two environments sharing a state key would overwrite each other's infrastructure."""
        keys: set[str] = set()
        buckets: set[str] = set()
        for environment in ALL_ENVIRONMENTS:
            backend = _blocks(_document(environment), "terraform")[0]["backend"]
            backend_dict = backend[0] if isinstance(backend, list) else backend
            settings = backend_dict.get("s3") or backend_dict.get('"s3"')
            keys.add(settings.get("key", settings.get('"key"')))
            buckets.add(settings.get("bucket", settings.get('"bucket"')))
            assert settings.get("encrypt", settings.get('"encrypt"')) is True
            assert settings.get("dynamodb_table", settings.get('"dynamodb_table"')), (
                f"{environment} has no state lock table"
            )
        assert len(keys) == len(ALL_ENVIRONMENTS)
        assert len(buckets) == len(ALL_ENVIRONMENTS)

    def test_address_space_never_overlaps(self) -> None:
        blocks = {
            env: str(_module(env, "network").get("cidr_block", "10.0.0.0/16"))
            for env in ALL_ENVIRONMENTS
        }
        assert len(set(blocks.values())) == len(ALL_ENVIRONMENTS), blocks

    @pytest.mark.parametrize("environment", ALL_ENVIRONMENTS)
    def test_every_environment_stays_in_mumbai(self, environment: str) -> None:
        """Data residency is a compliance commitment, not a default."""
        assert 'region = "ap-south-1"' in _source(environment)
        assert '"ap-south-1"' in _source(environment)


class TestStagingMirrorsProduction:
    """Staging carries the release gates, so it must fail the way production fails."""

    def test_the_database_is_multi_az_and_protected(self) -> None:
        data = _module("staging", "data")
        assert data["multi_az"] is True
        assert data["deletion_protection"] is True
        assert data["skip_final_snapshot"] is False
        assert data["aws_backup_enabled"] is True

    def test_egress_is_not_collapsed_onto_one_gateway(self) -> None:
        """A load profile through a single NAT gateway measures the gateway."""
        assert _module("staging", "network")["single_nat_gateway"] is False

    def test_the_cache_can_still_fail_over(self) -> None:
        data = _module("staging", "data")
        assert int(data["redis_replicas_per_shard"]) >= 1
        assert data["redis_multi_az"] is True

    def test_query_statistics_remain_available(self) -> None:
        assert _module("staging", "data")["performance_insights_enabled"] is True


class TestDisposableEnvironmentsStayCheapAndDestroyable:
    @pytest.mark.parametrize("environment", DISPOSABLE)
    def test_terraform_destroy_is_not_blocked(self, environment: str) -> None:
        data = _module(environment, "data")
        assert data["deletion_protection"] is False
        assert data["skip_final_snapshot"] is True

    @pytest.mark.parametrize("environment", DISPOSABLE)
    def test_egress_is_collapsed_onto_one_nat_gateway(self, environment: str) -> None:
        assert _module(environment, "network")["single_nat_gateway"] is True

    @pytest.mark.parametrize("environment", DISPOSABLE)
    def test_retention_is_shorter_but_never_zero(self, environment: str) -> None:
        assert 0 < int(_module(environment, "data")["backup_retention_days"]) <= 14


class TestSecurityPostureIsNotRelaxedAnywhere:
    @pytest.mark.parametrize("environment", ALL_ENVIRONMENTS)
    def test_the_data_tier_uses_the_private_data_subnets(self, environment: str) -> None:
        data = _module(environment, "data")
        assert "private_data_subnet_ids" in str(data["data_subnet_ids"])

    @pytest.mark.parametrize("environment", ALL_ENVIRONMENTS)
    def test_the_edge_terminates_tls_with_a_real_certificate(self, environment: str) -> None:
        assert "certificate_arn" in _module(environment, "edge")

    @pytest.mark.parametrize("environment", ALL_ENVIRONMENTS)
    def test_alarms_have_somewhere_to_go(self, environment: str) -> None:
        for module_name in ("data", "edge"):
            assert "alarm_topic_arn" in _module(environment, module_name)
        assert "aws_sns_topic" in _source(environment)

    @pytest.mark.parametrize("environment", ALL_ENVIRONMENTS)
    def test_spend_is_capped_and_alerted(self, environment: str) -> None:
        source = _source(environment)
        assert "aws_budgets_budget" in source
        assert "subscriber_sns_topic_arns" in source


class TestNetworkModuleRouting:
    """The routing that makes the private tiers private."""

    def test_data_subnets_have_no_route_off_the_vpc(self) -> None:
        source = (ROOT / "infra" / "terraform" / "modules" / "network" / "main.tf").read_text(
            encoding="utf-8"
        )
        assert 'resource "aws_route_table" "private_data"' in source
        # A default route on the data route table would give PostgreSQL and Redis a
        # path to the internet. There must not be one.
        assert "route_table_id         = aws_route_table.private_data" not in source
        assert 'aws_route" "private_data' not in source

    def test_application_subnets_egress_through_nat_not_the_gateway(self) -> None:
        source = (ROOT / "infra" / "terraform" / "modules" / "network" / "main.tf").read_text(
            encoding="utf-8"
        )
        assert "nat_gateway_id = aws_nat_gateway.this[" in source
        assert 'resource "aws_route_table_association" "private_app"' in source

    def test_public_subnets_reach_the_internet_gateway(self) -> None:
        source = (ROOT / "infra" / "terraform" / "modules" / "network" / "main.tf").read_text(
            encoding="utf-8"
        )
        assert "gateway_id             = aws_internet_gateway.this.id" in source
        assert 'resource "aws_route_table_association" "public"' in source
