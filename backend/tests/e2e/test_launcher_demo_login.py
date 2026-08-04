"""The launcher's printed credential must actually sign both demo users in.

This exists because every other test signed in over a `Host: testserver` or
`Host: 127.0.0.1` request with a hard-coded passphrase, and passed, while the real
`scripts/demo.ps1` stack rejected the login it had just printed. Two things were
wrong at once and neither was visible from the suite:

1. The BFF reaches the API as ``http://api:8000``, so requests arrive with
   ``Host: api``. ``TrustedHostMiddleware`` defaults to localhost only and answered
   ``400 Invalid host header`` before the password was ever checked. The container
   still reported healthy, because its own health check calls ``localhost``.
2. Nothing asserted that the password the launcher *generates* -- random, not the
   fixed passphrase the tests used -- survives the round trip through the seed.

So these tests use a launcher-shaped generated password, run the real seed script
with it, and drive the login over the exact hostname the compose topology uses,
read out of ``docker-compose.yml`` rather than hard-coded here.
"""

from __future__ import annotations

import base64
import re
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
import yaml
from fastapi.testclient import TestClient

pytestmark = pytest.mark.postgres

REPO_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
LAUNCHER = REPO_ROOT / "scripts" / "demo.ps1"

ACME_EMAIL = "asha@acme.test"
GLOBEX_EMAIL = "ravi@globex.test"


def launcher_style_password() -> str:
    """A password shaped like the one `New-DemoPassword` in demo.ps1 produces.

    PowerShell takes 24 random bytes, base64-encodes them, strips `+/=` and keeps
    the first 20 characters behind a `demo-` prefix. Reproduced here so the test
    exercises a *generated* credential rather than a curated one.
    """
    raw = base64.b64encode(secrets.token_bytes(24)).decode()
    raw = re.sub(r"[+/=]", "", raw)
    return f"demo-{raw[:20]}"


@pytest.fixture(scope="session")
def compose() -> dict[str, Any]:
    return dict(yaml.safe_load(COMPOSE_FILE.read_text())["services"])


@pytest.fixture(scope="session")
def api_hostname_used_by_the_bff(compose: dict[str, Any]) -> str:
    """The host the web container puts in the Host header when it calls the API."""
    internal: str = compose["web"]["environment"]["API_INTERNAL_URL"]
    host = urlparse(internal).hostname
    assert host, f"could not read a hostname out of API_INTERNAL_URL={internal!r}"
    return host


@pytest.fixture(scope="session")
def api_trusted_hosts(compose: dict[str, Any]) -> list[str]:
    configured = compose["api"]["environment"].get("TRUSTED_HOSTS", "")
    return [h.strip() for h in str(configured).split(",") if h.strip()]


@pytest.fixture
def wired_engine(migrated_database: str, engine: Any) -> Iterator[Any]:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import infrastructure.database.session as session_module

    session_module._engine = engine
    session_module._sessionmaker = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )
    yield engine
    session_module.reset_engine()


@pytest.fixture
def fake_redis() -> Iterator[None]:
    import fakeredis.aioredis

    from infrastructure.caching.redis import set_redis

    set_redis(fakeredis.aioredis.FakeRedis(decode_responses=True))
    yield
    set_redis(None)


@pytest.fixture
def generated_password() -> str:
    return launcher_style_password()


@pytest.fixture
def seeded_with_generated_password(
    wired_engine: Any, generated_password: str, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Run the real seed script the launcher runs, with a generated password."""
    import asyncio

    monkeypatch.setenv("DEMO_PASSWORD", generated_password)

    from scripts.seed_demo import resolve_password, seed

    resolved, was_generated = resolve_password()
    assert resolved == generated_password, "DEMO_PASSWORD must reach the seed unchanged"
    assert not was_generated, "a supplied password must not be silently replaced"

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(seed(resolved))
    finally:
        loop.close()
    return resolved


@pytest.fixture
def client(
    wired_engine: Any,
    fake_redis: None,
    seeded_with_generated_password: str,
    api_trusted_hosts: list[str],
) -> Iterator[TestClient]:
    """An API configured exactly as docker-compose configures it."""
    from api.app.factory import create_app
    from shared.settings import Settings

    settings = Settings(
        environment="local",
        trusted_hosts=api_trusted_hosts,
        cors_allowed_origins=["http://localhost:3000"],
        log_json=False,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


class TestComposeWiring:
    """Config drift, caught without needing a Docker daemon."""

    def test_the_api_trusts_the_hostname_the_bff_calls_it_by(
        self, api_trusted_hosts: list[str], api_hostname_used_by_the_bff: str
    ) -> None:
        assert api_hostname_used_by_the_bff in api_trusted_hosts, (
            f"the web service calls the API as {api_hostname_used_by_the_bff!r}, but the api "
            f"service trusts only {api_trusted_hosts}. TrustedHostMiddleware will answer "
            f"400 'Invalid host header' and the browser will show 'Sign in failed.'"
        )

    def test_localhost_stays_trusted_for_the_container_health_check(
        self, api_trusted_hosts: list[str], compose: dict[str, Any]
    ) -> None:
        probe = " ".join(compose["api"]["healthcheck"]["test"])
        assert "localhost" in probe
        assert "localhost" in api_trusted_hosts

    def test_the_launcher_passes_its_password_to_the_seed(self) -> None:
        """The printed credential and the seeded one must come from one variable."""
        script = LAUNCHER.read_text()
        assert "DEMO_PASSWORD=$Password" in script
        assert "seed_demo.py" in script
        assert 'Write-Host "  Password    $Password"' in script


class TestBothDemoUsersCanSignIn:
    def test_acme_signs_in_with_the_generated_password(
        self, client: TestClient, generated_password: str, api_hostname_used_by_the_bff: str
    ) -> None:
        response = client.post(
            "/v1/auth/login",
            json={"email": ACME_EMAIL, "password": generated_password},
            headers={"Host": api_hostname_used_by_the_bff},
        )
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["access_token"] and data["refresh_token"]
        assert data["user"]["tenant_slug"] == "acme"

    def test_globex_signs_in_with_the_generated_password(
        self, client: TestClient, generated_password: str, api_hostname_used_by_the_bff: str
    ) -> None:
        response = client.post(
            "/v1/auth/login",
            json={"email": GLOBEX_EMAIL, "password": generated_password},
            headers={"Host": api_hostname_used_by_the_bff},
        )
        assert response.status_code == 200, response.text
        assert response.json()["data"]["user"]["tenant_slug"] == "globex"

    def test_the_bff_hostname_is_not_rejected_before_the_password_is_checked(
        self, client: TestClient, api_hostname_used_by_the_bff: str
    ) -> None:
        """The regression itself: a wrong password must reach the password check.

        A 400 here means TrustedHostMiddleware refused the request. A 401 means the
        credential was actually evaluated, which is the behaviour being protected.
        """
        response = client.post(
            "/v1/auth/login",
            json={"email": ACME_EMAIL, "password": "definitely-not-the-password"},
            headers={"Host": api_hostname_used_by_the_bff},
        )
        assert response.status_code == 401, (
            f"expected the credential to be evaluated, got {response.status_code}: {response.text}"
        )
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_an_untrusted_host_is_still_refused(self, client: TestClient) -> None:
        """Widening the list must not have turned the guard off."""
        response = client.post(
            "/v1/auth/login",
            json={"email": ACME_EMAIL, "password": "irrelevant"},
            headers={"Host": "evil.example.com"},
        )
        assert response.status_code == 400

    def test_reseeding_with_a_new_password_replaces_the_old_one(
        self,
        client: TestClient,
        generated_password: str,
        wired_engine: Any,
        api_hostname_used_by_the_bff: str,
    ) -> None:
        """Every launcher run prints a fresh password, so the seed must reset it."""
        import asyncio

        from scripts.seed_demo import seed

        second = launcher_style_password()
        assert second != generated_password

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(seed(second))
        finally:
            loop.close()

        host = {"Host": api_hostname_used_by_the_bff}
        for email in (ACME_EMAIL, GLOBEX_EMAIL):
            fresh = client.post(
                "/v1/auth/login", json={"email": email, "password": second}, headers=host
            )
            assert fresh.status_code == 200, f"{email} rejected the reseeded password"
            stale = client.post(
                "/v1/auth/login",
                json={"email": email, "password": generated_password},
                headers=host,
            )
            assert stale.status_code == 401, f"{email} still accepts the superseded password"
