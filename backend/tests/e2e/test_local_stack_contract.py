"""The contract between docker-compose.yml and the Windows launcher.

Static, deliberately: it needs no Docker daemon, so it runs in CI and on any
developer machine, and it catches the class of defect that has actually bitten
this project twice -- config drift between two files that nothing compared.

It asserts three things the launcher depends on and cannot check for itself:

  * start-up ordering is expressed through `depends_on` + health conditions, not
    hoped for;
  * the launcher starts the whole tier, and waits only on services that really
    report health;
  * nothing on the ordinary path destroys data.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import yaml

from tests.repo_layout import repository_root

# These files live above `backend/`, so the checkout has to be located rather than
# inferred from this module's position - inside a container that mounts only
# `backend/`, counting directories upwards lands on `/`.
REPO_ROOT = repository_root()
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
LAUNCHER = REPO_ROOT / "scripts" / "demo.ps1"
RESET = REPO_ROOT / "scripts" / "reset-demo.ps1"

WORKER_POOLS = ("worker-comms", "worker-ai", "worker-general", "worker-bulk")


@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    return dict(yaml.safe_load(COMPOSE_FILE.read_text()))


@pytest.fixture(scope="module")
def services(compose: dict[str, Any]) -> dict[str, Any]:
    return dict(compose["services"])


@pytest.fixture(scope="module")
def launcher() -> str:
    return LAUNCHER.read_text()


class TestStartupOrdering:
    def test_the_api_waits_for_postgres_and_redis_to_be_healthy(
        self, services: dict[str, Any]
    ) -> None:
        depends = services["api"]["depends_on"]
        assert depends["postgres"]["condition"] == "service_healthy"
        assert depends["redis"]["condition"] == "service_healthy"

    def test_every_worker_pool_waits_for_its_dependencies(self, services: dict[str, Any]) -> None:
        for pool in WORKER_POOLS:
            depends = services[pool]["depends_on"]
            assert depends["postgres"]["condition"] == "service_healthy", pool
            assert depends["redis"]["condition"] == "service_healthy", pool

    def test_beat_waits_for_a_worker_that_is_actually_ready(self, services: dict[str, Any]) -> None:
        """`service_started` only proves the process launched.

        Beat fires the outbox relay every 500 ms. Pointed at a pool that cannot
        reach PostgreSQL yet, that is a burst of retries at every start-up.
        """
        assert services["beat"]["depends_on"]["worker-general"]["condition"] == "service_healthy"

    def test_the_web_app_waits_for_a_healthy_api(self, services: dict[str, Any]) -> None:
        assert services["web"]["depends_on"]["api"]["condition"] == "service_healthy"

    def test_data_stores_and_the_api_and_pools_all_have_health_probes(
        self, services: dict[str, Any]
    ) -> None:
        for name in ("postgres", "redis", "api", *WORKER_POOLS):
            assert services[name].get("healthcheck"), f"{name} has no healthcheck"


class TestLauncherStartsTheWholeStack:
    def test_it_starts_every_service_the_demo_needs(self, launcher: str) -> None:
        block = launcher[launcher.index("$Services = @(") :]
        block = block[: block.index(")")]
        listed = set(re.findall(r"'([a-z0-9-]+)'", block))
        assert listed == {"postgres", "redis", "api", "beat", "web", *WORKER_POOLS}, listed

    def test_it_only_waits_on_services_that_report_health(
        self, launcher: str, services: dict[str, Any]
    ) -> None:
        """Waiting on Beat would hang forever: Celery Beat exposes no probe."""
        block = launcher[launcher.index("$HealthyServices = @(") :]
        block = block[: block.index(")")]
        awaited = set(re.findall(r"'([a-z0-9-]+)'", block))

        assert "beat" not in awaited, "Beat has no healthcheck; waiting on it cannot succeed"
        for name in awaited:
            assert services[name].get("healthcheck"), (
                f"launcher waits on {name}, which has no probe"
            )

    def test_the_wait_is_bounded_and_dumps_logs_on_failure(self, launcher: str) -> None:
        assert "function Wait-ForStack" in launcher
        # A deadline, not a `while ($true)`.
        assert "$deadline = (Get-Date).AddSeconds($Timeout)" in launcher
        assert "while ($true)" not in launcher
        assert "docker compose logs" in launcher


class TestNothingOnTheNormalPathDestroysData:
    def test_the_launcher_never_removes_a_volume(self, launcher: str) -> None:
        """`docker compose down -v` must not appear anywhere in the everyday path."""
        assert "'down'" not in launcher
        assert "-v" not in re.sub(r"#.*", "", launcher).replace("--", "")
        assert "Reset" not in launcher, "the destructive switch must stay out of the launcher"

    def test_the_database_lives_in_a_named_volume(self, compose: dict[str, Any]) -> None:
        """Which is why an ordinary stop and start keeps the data."""
        assert "pgdata" in compose["volumes"]
        mounts = compose["services"]["postgres"]["volumes"]
        assert any(str(m).startswith("pgdata:") for m in mounts)

    def test_reset_is_a_separate_script_that_demands_confirmation(self) -> None:
        assert RESET.exists(), "the destructive path must be its own command"
        text = RESET.read_text()
        assert "docker compose down -v" in text or "'down', '-v'" in text or "down -v" in text
        assert "Read-Host" in text
        assert "-ne 'reset'" in text, "it must require the word 'reset' to be typed"


class TestIdempotentBootstrap:
    def test_the_launcher_migrates_then_seeds_reference_data_then_demo_data(
        self, launcher: str
    ) -> None:
        order = [
            launcher.index("alembic"),
            launcher.index("src/scripts/seed.py"),
            launcher.index("src/scripts/seed_demo.py"),
        ]
        assert order == sorted(order), "migrate, then reference data, then demo data"

    def test_the_api_carries_the_owner_credential_migrations_need(
        self, services: dict[str, Any]
    ) -> None:
        env = services["api"]["environment"]
        assert "ALEMBIC_DATABASE_URL" in env
        assert "+psycopg" in env["ALEMBIC_DATABASE_URL"], "alembic runs synchronously"
        assert "airevenueos_app_login" in env["DATABASE_URL"], (
            "the runtime role must be able to log in"
        )

    def test_mfa_has_an_encryption_key_so_enrolment_does_not_fail_closed(
        self, services: dict[str, Any]
    ) -> None:
        for name in ("api", "worker-comms"):
            key = services[name]["environment"].get("ENCRYPTION_MASTER_KEY", "")
            assert len(key) >= 32, f"{name} would refuse to store a TOTP secret"
