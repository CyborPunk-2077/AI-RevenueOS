"""The P0-2 `/v1/auth` surface, over HTTP against real PostgreSQL.

Every test drives the endpoints rather than the service functions, because the
things most likely to be wrong are at the boundary: a route that forgets a
permission check, a response that leaks a secret a second time, a limit applied to
the wrong subject.

Redis is real (`fakeredis` speaks the same protocol for the commands used here:
sliding-window ZSET rate limits, `GETDEL` for single-use state). PostgreSQL is a
real server with RLS forced, so cross-tenant assertions mean what they say.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.postgres

DEMO_PASSWORD = "auth-surface-passphrase-2026"
ACME_EMAIL = "asha@acme.test"
GLOBEX_EMAIL = "ravi@globex.test"
MASTER_KEY = "unit-test-master-key-that-is-long-enough-32+"


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


@pytest.fixture(scope="session")
def redis_endpoint() -> str:
    """A real Redis endpoint supplied by CI, or a local redislite fallback.

    `fakeredis` cannot run the limiter's sliding-window Lua script, so the rate
    limiter fails open against it and every limit assertion would silently pass
    for the wrong reason. `GETDEL`, which makes OAuth state and MFA challenges
    single use, likewise needs a real server.
    """
    configured = os.environ.get("REDIS_URL")
    if configured:
        import redis

        server = redis.Redis.from_url(configured, decode_responses=True)
        server.ping()
        pytest._airev_auth_redis = server  # type: ignore[attr-defined]
        return configured
    try:
        import tempfile

        import redislite
    except ImportError:
        pytest.skip("A real Redis is required; set REDIS_URL on this platform.")
    server = redislite.Redis(tempfile.mktemp(suffix=".rdb"))
    pytest._airev_auth_redis = server  # type: ignore[attr-defined]
    return f"unix://{server.socket_file}"


@pytest.fixture
def fake_redis(redis_endpoint: str) -> Iterator[Any]:
    import redis.asyncio as aioredis

    from infrastructure.caching.redis import set_redis

    # Start each test from an empty keyspace, so one test's rate-limit counters
    # cannot exhaust the next test's budget. Flushed through the *synchronous*
    # handle: the async client belongs to the TestClient's event loop, which is
    # already closed by the time a teardown would run.
    pytest._airev_auth_redis.flushall()  # type: ignore[attr-defined]
    client = aioredis.from_url(redis_endpoint, decode_responses=True)
    set_redis(client)
    yield client
    set_redis(None)


@pytest.fixture
def demo_data(wired_engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)
    from scripts.seed_demo import seed

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(seed(DEMO_PASSWORD))
    finally:
        loop.close()


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Any:
    from shared.settings import Settings

    # MFA stores its secret with envelope encryption, which fails closed without a
    # master key. Supplying one here is what makes the enrolment tests meaningful.
    return Settings(
        environment="local",
        trusted_hosts=["testserver", "localhost"],
        cors_allowed_origins=["http://localhost:3000"],
        log_json=False,
        encryption_master_key=MASTER_KEY,
    )


@pytest.fixture
def client(
    wired_engine: Any, fake_redis: Any, demo_data: None, settings: Any
) -> Iterator[TestClient]:
    from api.app.factory import create_app

    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def _master_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """`application.auth.mfa` reads the process settings, not the app's."""
    monkeypatch.setenv("ENCRYPTION_MASTER_KEY", MASTER_KEY)
    from shared.settings import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def sign_in(client: TestClient, email: str, password: str = DEMO_PASSWORD) -> dict[str, Any]:
    response = client.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def bearer(session: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {session['access_token']}"}


# --- sign-up, verification and recovery -------------------------------------


class TestSignupAndVerification:
    def test_signup_creates_a_tenant_but_no_session(self, client: TestClient) -> None:
        email = f"founder-{uuid4().hex[:8]}@example.in"
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": email,
                "password": "a-perfectly-fine-passphrase",
                "full_name": "Nikhil Founder",
                "organisation": "Nikhil Realty",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()["data"]
        assert body["verification_required"] is True
        assert body["tenant_slug"].startswith("nikhil-realty")
        # The response must not contain anything that could be used as a session.
        assert "access_token" not in body
        assert "refresh_token" not in body

    def test_an_unverified_account_cannot_sign_in(self, client: TestClient) -> None:
        email = f"pending-{uuid4().hex[:8]}@example.in"
        password = "another-fine-passphrase"
        client.post(
            "/v1/auth/signup",
            json={
                "email": email,
                "password": password,
                "full_name": "Pending Person",
                "organisation": "Pending Co",
            },
        )
        refused = client.post("/v1/auth/login", json={"email": email, "password": password})
        assert refused.status_code == 401

    def test_verifying_the_email_activates_the_account(self, client: TestClient) -> None:
        email = f"newbie-{uuid4().hex[:8]}@example.in"
        password = "verify-me-passphrase-9"
        created = client.post(
            "/v1/auth/signup",
            json={
                "email": email,
                "password": password,
                "full_name": "Newbie Person",
                "organisation": "Newbie Co",
            },
        ).json()["data"]

        verified = client.post(
            "/v1/auth/verify-email", json={"token": created["verification_token"]}
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["data"]["status"] == "active"

        session = sign_in(client, email, password)
        assert session["access_token"]

    def test_a_verification_token_is_single_use(self, client: TestClient) -> None:
        email = f"once-{uuid4().hex[:8]}@example.in"
        created = client.post(
            "/v1/auth/signup",
            json={
                "email": email,
                "password": "single-use-passphrase",
                "full_name": "Once Only",
                "organisation": "Once Co",
            },
        ).json()["data"]
        token = created["verification_token"]

        assert client.post("/v1/auth/verify-email", json={"token": token}).status_code == 200
        assert client.post("/v1/auth/verify-email", json={"token": token}).status_code == 404

    def test_a_duplicate_address_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": ACME_EMAIL,
                "password": "duplicate-address-passphrase",
                "full_name": "Impostor",
                "organisation": "Impostor Co",
            },
        )
        assert response.status_code == 409

    def test_a_weak_password_is_refused_before_anything_is_created(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/v1/auth/signup",
            json={
                "email": f"weak-{uuid4().hex[:8]}@example.in",
                "password": "aaaaaaaaaaaaaa",
                "full_name": "Weak Password",
                "organisation": "Weak Co",
            },
        )
        assert response.status_code == 422


class TestPasswordRecovery:
    def test_forgot_password_does_not_reveal_whether_the_account_exists(
        self, client: TestClient
    ) -> None:
        known = client.post("/v1/auth/forgot-password", json={"email": ACME_EMAIL})
        unknown = client.post("/v1/auth/forgot-password", json={"email": "nobody@nowhere.test"})
        assert known.status_code == unknown.status_code == 200
        # Same shape, same keys; only the local-development token differs.
        assert known.json()["data"]["requested"] is True
        assert unknown.json()["data"]["requested"] is True
        assert "reset_token" not in unknown.json()["data"]

    def test_reset_sets_the_password_and_kills_every_session(self, client: TestClient) -> None:
        before = sign_in(client, ACME_EMAIL)
        assert client.get("/v1/leads", headers=bearer(before)).status_code == 200

        token = client.post("/v1/auth/forgot-password", json={"email": ACME_EMAIL}).json()["data"][
            "reset_token"
        ]
        new_password = "a-brand-new-reset-passphrase"
        done = client.post(
            "/v1/auth/reset-password", json={"token": token, "password": new_password}
        )
        assert done.status_code == 200
        assert done.json()["data"]["sessions_revoked"] is True

        # The old refresh token is dead even though its access token has not expired.
        replay = client.post("/v1/auth/refresh", json={"refresh_token": before["refresh_token"]})
        assert replay.status_code == 401

        assert sign_in(client, ACME_EMAIL, new_password)["access_token"]
        stale = client.post("/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD})
        assert stale.status_code == 401

    def test_a_reset_token_cannot_be_replayed(self, client: TestClient) -> None:
        token = client.post("/v1/auth/forgot-password", json={"email": GLOBEX_EMAIL}).json()[
            "data"
        ]["reset_token"]
        first = client.post(
            "/v1/auth/reset-password", json={"token": token, "password": "first-new-passphrase"}
        )
        assert first.status_code == 200
        second = client.post(
            "/v1/auth/reset-password", json={"token": token, "password": "second-new-passphrase"}
        )
        assert second.status_code == 404

    def test_a_forged_reset_token_for_another_tenant_finds_nothing(
        self, client: TestClient
    ) -> None:
        """The tenant id in a token is not a credential."""
        forged = f"{uuid4()}.{'x' * 43}"
        response = client.post(
            "/v1/auth/reset-password", json={"token": forged, "password": "forged-passphrase-1"}
        )
        assert response.status_code == 404


# --- lockout ----------------------------------------------------------------


class TestLockout:
    def test_repeated_failures_lock_the_account(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Account lockout, isolated from the per-IP limit that normally hides it.

        `login_ip` allows 5 attempts per 15 minutes and `MAX_FAILED_ATTEMPTS` is
        also 5, so from one address the IP limit answers 429 before the account
        ever locks. That ordering is deliberate defence in depth -- lockout is
        what protects an account from a *distributed* guess -- but it means the
        lockout itself is only observable once the IP ceiling is lifted.
        """
        from infrastructure.auth.passwords import MAX_FAILED_ATTEMPTS
        from infrastructure.caching.rate_limit import POLICIES, LimitPolicy

        monkeypatch.setitem(POLICIES, "login_ip", LimitPolicy("login_ip", 1_000, 900))

        for _ in range(MAX_FAILED_ATTEMPTS):
            client.post(
                "/v1/auth/login", json={"email": ACME_EMAIL, "password": "wrong-password-here"}
            )

        # The correct password is now refused too, and the message says why.
        locked = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        )
        assert locked.status_code == 401
        assert "locked" in locked.json()["error"]["message"].lower()

    def test_the_per_ip_limit_fires_before_the_account_ever_locks(self, client: TestClient) -> None:
        """The ordering above, asserted rather than assumed."""
        from infrastructure.caching.rate_limit import POLICIES

        statuses = [
            client.post(
                "/v1/auth/login", json={"email": ACME_EMAIL, "password": "wrong-password-here"}
            ).status_code
            for _ in range(POLICIES["login_ip"].limit + 1)
        ]
        assert statuses[-1] == 429
        assert statuses.count(401) == POLICIES["login_ip"].limit


# --- refresh rotation and session families ----------------------------------


class TestRefreshRotation:
    def test_rotation_issues_a_new_token_and_retires_the_old(self, client: TestClient) -> None:
        first = sign_in(client, ACME_EMAIL)
        rotated = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert rotated.status_code == 200
        assert rotated.json()["data"]["refresh_token"] != first["refresh_token"]

    def test_reuse_of_a_rotated_token_revokes_the_whole_family(self, client: TestClient) -> None:
        first = sign_in(client, ACME_EMAIL)
        second = client.post(
            "/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}
        ).json()["data"]

        # Replaying the retired token is treated as theft.
        replay = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert replay.status_code == 401

        # ...and the token the legitimate client holds dies with the family.
        after = client.post("/v1/auth/refresh", json={"refresh_token": second["refresh_token"]})
        assert after.status_code == 401, "family reuse must revoke every sibling"


class TestSessions:
    def test_sessions_lists_only_the_callers_own(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        sign_in(client, GLOBEX_EMAIL)

        listed = client.get("/v1/auth/sessions", headers=bearer(acme))
        assert listed.status_code == 200
        sessions = listed.json()["data"]["sessions"]
        assert len(sessions) >= 1
        assert any(entry["current"] for entry in sessions)
        # Nothing that could be replayed as a credential.
        for entry in sessions:
            assert "token" not in entry
            assert "token_hash" not in entry

    def test_revoking_a_session_kills_its_refresh_token(self, client: TestClient) -> None:
        first = sign_in(client, ACME_EMAIL)
        second = sign_in(client, ACME_EMAIL)

        listed = client.get("/v1/auth/sessions", headers=bearer(second)).json()["data"]["sessions"]
        other = next(entry for entry in listed if not entry["current"])

        revoked = client.delete(f"/v1/auth/sessions/{other['id']}", headers=bearer(second))
        assert revoked.status_code == 200

        dead = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert dead.status_code == 401

    def test_a_second_tenant_cannot_revoke_the_first_tenants_session(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)

        target = client.get("/v1/auth/sessions", headers=bearer(acme)).json()["data"]["sessions"][
            0
        ]["id"]

        cross = client.delete(f"/v1/auth/sessions/{target}", headers=bearer(globex))
        assert cross.status_code == 404, "another tenant's session must be invisible"

        # And it still works for its owner.
        assert client.get("/v1/auth/me", headers=bearer(acme)).status_code == 200

    def test_logout_all_revokes_every_session(self, client: TestClient) -> None:
        first = sign_in(client, ACME_EMAIL)
        second = sign_in(client, ACME_EMAIL)

        result = client.post("/v1/auth/logout-all", headers=bearer(second))
        assert result.status_code == 200
        assert result.json()["data"]["sessions_revoked"] >= 2

        for session in (first, second):
            assert (
                client.post(
                    "/v1/auth/refresh", json={"refresh_token": session["refresh_token"]}
                ).status_code
                == 401
            )

    def test_the_session_cap_evicts_the_oldest(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`MAX_SESSIONS_PER_USER` was documented and unenforced before P0-2.

        The per-IP limit is lifted for the same reason as in `TestLockout`: twelve
        sign-ins from one address would be refused by the limiter long before the
        cap came into play, and the cap is what is under test here.
        """
        from infrastructure.auth.tokens import MAX_SESSIONS_PER_USER
        from infrastructure.caching.rate_limit import POLICIES, LimitPolicy

        monkeypatch.setitem(POLICIES, "login_ip", LimitPolicy("login_ip", 1_000, 900))
        monkeypatch.setitem(POLICIES, "login_account", LimitPolicy("login_account", 1_000, 3600))

        opened = [sign_in(client, ACME_EMAIL) for _ in range(MAX_SESSIONS_PER_USER + 2)]

        live = client.get("/v1/auth/sessions", headers=bearer(opened[-1])).json()["data"][
            "sessions"
        ]
        assert len(live) <= MAX_SESSIONS_PER_USER

        # The oldest was evicted; the newest still works.
        assert (
            client.post(
                "/v1/auth/refresh", json={"refresh_token": opened[0]["refresh_token"]}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/v1/auth/refresh", json={"refresh_token": opened[-1]["refresh_token"]}
            ).status_code
            == 200
        )


# --- multi-factor authentication --------------------------------------------


def _totp_now(secret: str) -> str:
    from infrastructure.auth.mfa import current_totp

    return current_totp(secret)


class TestMfa:
    def _enrol(self, client: TestClient, session: dict[str, Any]) -> tuple[str, list[str]]:
        started = client.post("/v1/auth/mfa/setup", headers=bearer(session))
        assert started.status_code == 200, started.text
        body = started.json()["data"]
        assert body["otpauth_url"].startswith("otpauth://totp/")

        confirmed = client.post(
            "/v1/auth/mfa/setup/confirm",
            headers=bearer(session),
            json={"pending": body["pending"], "code": _totp_now(body["secret"])},
        )
        assert confirmed.status_code == 200, confirmed.text
        return body["secret"], confirmed.json()["data"]["recovery_codes"]

    def test_enrolment_requires_a_working_code(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        body = client.post("/v1/auth/mfa/setup", headers=bearer(session)).json()["data"]

        rejected = client.post(
            "/v1/auth/mfa/setup/confirm",
            headers=bearer(session),
            json={"pending": body["pending"], "code": "000000"},
        )
        assert rejected.status_code == 422

        # Nothing was committed, so the account is still un-enrolled.
        again = client.post("/v1/auth/mfa/setup", headers=bearer(session))
        assert again.status_code == 200

    def test_login_returns_a_challenge_once_enrolled(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        secret, _ = self._enrol(client, session)

        challenged = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        )
        assert challenged.status_code == 200
        body = challenged.json()["data"]
        assert body["mfa_required"] is True
        # Critically: no session was issued by the password alone.
        assert "access_token" not in body

        completed = client.post(
            "/v1/auth/mfa/verify",
            json={"mfa_token": body["mfa_token"], "code": _totp_now(secret)},
        )
        assert completed.status_code == 200, completed.text
        assert completed.json()["data"]["user"]["mfa_verified"] is True

    def test_a_challenge_token_is_single_use(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        secret, _ = self._enrol(client, session)

        challenge = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        ).json()["data"]["mfa_token"]

        assert (
            client.post(
                "/v1/auth/mfa/verify", json={"mfa_token": challenge, "code": _totp_now(secret)}
            ).status_code
            == 200
        )
        replay = client.post(
            "/v1/auth/mfa/verify", json={"mfa_token": challenge, "code": _totp_now(secret)}
        )
        assert replay.status_code == 401

    def test_a_recovery_code_works_once(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        _, recovery = self._enrol(client, session)
        assert len(recovery) == 8

        challenge = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        ).json()["data"]["mfa_token"]
        used = client.post(
            "/v1/auth/mfa/verify", json={"mfa_token": challenge, "code": recovery[0]}
        )
        assert used.status_code == 200

        second_challenge = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        ).json()["data"]["mfa_token"]
        reused = client.post(
            "/v1/auth/mfa/verify", json={"mfa_token": second_challenge, "code": recovery[0]}
        )
        assert reused.status_code == 401, "a recovery code must not work twice"

    def test_disabling_requires_the_password_and_a_code(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        secret, _ = self._enrol(client, session)

        wrong_password = client.post(
            "/v1/auth/mfa/disable",
            headers=bearer(session),
            json={"password": "not-the-password", "code": _totp_now(secret)},
        )
        assert wrong_password.status_code == 401

        ok = client.post(
            "/v1/auth/mfa/disable",
            headers=bearer(session),
            json={"password": DEMO_PASSWORD, "code": _totp_now(secret)},
        )
        assert ok.status_code == 200
        assert ok.json()["data"]["enabled"] is False


class TestStepUp:
    def test_creating_an_api_key_is_refused_without_a_recent_mfa_challenge(
        self, client: TestClient
    ) -> None:
        session = sign_in(client, ACME_EMAIL)
        refused = client.post(
            "/v1/auth/api-keys", headers=bearer(session), json={"name": "ci", "scopes": []}
        )
        assert refused.status_code == 403
        assert refused.json()["error"]["details"]["step_up_required"] is True

    def test_a_session_that_proved_mfa_may_create_a_key(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        started = client.post("/v1/auth/mfa/setup", headers=bearer(session)).json()["data"]
        client.post(
            "/v1/auth/mfa/setup/confirm",
            headers=bearer(session),
            json={"pending": started["pending"], "code": _totp_now(started["secret"])},
        )

        stepped_up = client.post(
            "/v1/auth/mfa/verify",
            headers=bearer(session),
            json={"code": _totp_now(started["secret"])},
        )
        assert stepped_up.status_code == 200, stepped_up.text
        elevated = stepped_up.json()["data"]
        assert elevated["user"]["mfa_verified"] is True

        created = client.post(
            "/v1/auth/api-keys",
            headers=bearer(elevated),
            json={"name": "ci", "scopes": ["lead:read"]},
        )
        assert created.status_code == 201, created.text


# --- API keys ---------------------------------------------------------------


class TestApiKeys:
    def _elevated(self, client: TestClient, email: str) -> dict[str, Any]:
        session = sign_in(client, email)
        started = client.post("/v1/auth/mfa/setup", headers=bearer(session)).json()["data"]
        client.post(
            "/v1/auth/mfa/setup/confirm",
            headers=bearer(session),
            json={"pending": started["pending"], "code": _totp_now(started["secret"])},
        )
        # A fresh TOTP window, so the step-up is not rejected as a replayed code.
        time.sleep(0)
        return dict(
            client.post(
                "/v1/auth/mfa/verify",
                headers=bearer(session),
                json={"code": _totp_now(started["secret"])},
            ).json()["data"]
        )

    def test_the_value_is_returned_once_and_never_again(self, client: TestClient) -> None:
        elevated = self._elevated(client, ACME_EMAIL)
        created = client.post(
            "/v1/auth/api-keys", headers=bearer(elevated), json={"name": "deploy", "scopes": []}
        ).json()["data"]

        assert created["key"].startswith("ak_live_")
        plaintext = created["key"]

        listed = client.get("/v1/auth/api-keys", headers=bearer(elevated)).json()["data"][
            "api_keys"
        ]
        entry = next(item for item in listed if item["id"] == created["id"])
        assert "key" not in entry
        assert entry["masked_key"] != plaintext
        assert plaintext not in str(listed), "the plaintext key must never reappear"

    def test_a_key_cannot_be_granted_permissions_the_creator_lacks(
        self, client: TestClient
    ) -> None:
        elevated = self._elevated(client, ACME_EMAIL)
        response = client.post(
            "/v1/auth/api-keys",
            headers=bearer(elevated),
            json={"name": "too-much", "scopes": ["platform:root"]},
        )
        assert response.status_code == 422
        assert "platform:root" in str(response.json()["error"]["details"])

    def test_revoking_removes_it_from_the_listing(self, client: TestClient) -> None:
        elevated = self._elevated(client, ACME_EMAIL)
        created = client.post(
            "/v1/auth/api-keys", headers=bearer(elevated), json={"name": "temp", "scopes": []}
        ).json()["data"]

        assert (
            client.delete(
                f"/v1/auth/api-keys/{created['id']}", headers=bearer(elevated)
            ).status_code
            == 200
        )
        listed = client.get("/v1/auth/api-keys", headers=bearer(elevated)).json()["data"][
            "api_keys"
        ]
        assert all(item["id"] != created["id"] for item in listed)

    def test_another_tenant_can_neither_see_nor_revoke_the_key(self, client: TestClient) -> None:
        acme = self._elevated(client, ACME_EMAIL)
        created = client.post(
            "/v1/auth/api-keys", headers=bearer(acme), json={"name": "acme-only", "scopes": []}
        ).json()["data"]

        globex = self._elevated(client, GLOBEX_EMAIL)
        listed = client.get("/v1/auth/api-keys", headers=bearer(globex)).json()["data"]["api_keys"]
        assert all(item["id"] != created["id"] for item in listed)

        cross = client.delete(f"/v1/auth/api-keys/{created['id']}", headers=bearer(globex))
        assert cross.status_code == 404


# --- Google sign-in ---------------------------------------------------------


class TestGoogleOauth:
    def test_it_is_gated_when_no_credentials_are_configured(self, client: TestClient) -> None:
        response = client.get("/v1/auth/google/authorize")
        assert response.status_code == 403
        assert response.json()["error"]["details"]["capability"] == "google_oauth"

    def test_state_is_single_use(self, fake_redis: Any) -> None:
        """Proved directly against Redis: the route needs live Google credentials."""
        import asyncio

        from application.auth.oauth import consume_state
        from infrastructure.caching.redis import global_key
        from shared.exceptions import Unauthenticated

        async def scenario() -> None:
            await fake_redis.set(global_key("oauth_state", "abc123"), '{"redirect_to": "/leads"}')
            first = await consume_state("abc123")
            assert first["redirect_to"] == "/leads"
            with pytest.raises(Unauthenticated):
                await consume_state("abc123")

        asyncio.new_event_loop().run_until_complete(scenario())

    def test_an_unknown_state_is_refused(self, fake_redis: Any) -> None:
        import asyncio

        from application.auth.oauth import consume_state
        from shared.exceptions import Unauthenticated

        async def scenario() -> None:
            with pytest.raises(Unauthenticated):
                await consume_state("never-issued")

        asyncio.new_event_loop().run_until_complete(scenario())


# --- rate limiting ----------------------------------------------------------


class TestRateLimits:
    def test_repeated_failed_logins_from_one_ip_are_throttled(self, client: TestClient) -> None:
        from infrastructure.caching.rate_limit import POLICIES

        limit = POLICIES["login_ip"].limit
        statuses = [
            client.post(
                "/v1/auth/login",
                json={"email": f"nobody-{index}@nowhere.test", "password": "x" * 14},
            ).status_code
            for index in range(limit + 2)
        ]
        assert 429 in statuses, "the login_ip policy must eventually refuse"

    def test_the_limit_response_says_when_to_retry(self, client: TestClient) -> None:
        from infrastructure.caching.rate_limit import POLICIES

        for index in range(POLICIES["login_ip"].limit + 2):
            response = client.post(
                "/v1/auth/login",
                json={"email": f"flood-{index}@nowhere.test", "password": "x" * 14},
            )
            if response.status_code == 429:
                assert response.json()["error"]["details"]["retry_after"] >= 0
                return
        pytest.fail("never hit the limit")


# --- identity ---------------------------------------------------------------


class TestMe:
    def test_me_reports_the_session_mfa_state(self, client: TestClient) -> None:
        session = sign_in(client, ACME_EMAIL)
        body = client.get("/v1/auth/me", headers=bearer(session)).json()["data"]
        assert body["email"] == ACME_EMAIL
        assert body["mfa_verified"] is False
        assert "lead:create" in body["permissions"]

    def test_every_authenticated_route_refuses_an_anonymous_caller(
        self, client: TestClient
    ) -> None:
        for method, path in (
            ("get", "/v1/auth/me"),
            ("get", "/v1/auth/sessions"),
            ("post", "/v1/auth/logout-all"),
            ("post", "/v1/auth/mfa/setup"),
            ("get", "/v1/auth/api-keys"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 401, f"{method.upper()} {path} was not protected"
