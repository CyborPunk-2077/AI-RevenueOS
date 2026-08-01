"""The demo vertical slice, exercised over HTTP against real PostgreSQL.

Covers exactly what the browser flow does: sign in, list, create, open, edit,
re-read after the edit (persistence), and -- the point of the slice -- that a
second tenant cannot reach the first tenant's record.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.postgres

DEMO_PASSWORD = "demo-vertical-slice-passphrase"
ACME_EMAIL = "asha@acme.test"
GLOBEX_EMAIL = "ravi@globex.test"


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
def demo_data(wired_engine: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the real demo seed, so the test covers the script users actually run."""
    import asyncio

    monkeypatch.setenv("DEMO_PASSWORD", DEMO_PASSWORD)

    from scripts.seed_demo import seed

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(seed(DEMO_PASSWORD))
    finally:
        loop.close()


@pytest.fixture
def client(wired_engine: Any, fake_redis: None, demo_data: None) -> Iterator[TestClient]:
    from api.app.factory import create_app
    from shared.settings import Settings

    settings = Settings(
        environment="local",
        trusted_hosts=["testserver", "localhost"],
        cors_allowed_origins=["http://localhost:3000"],
        log_json=False,
    )
    with TestClient(create_app(settings), raise_server_exceptions=False) as test_client:
        yield test_client


def sign_in(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


class TestSignIn:
    def test_demo_user_can_sign_in(self, client: TestClient) -> None:
        response = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        )
        body = response.json()["data"]
        assert response.status_code == 200
        assert body["user"]["tenant_slug"] == "acme"
        assert body["access_token"] and body["refresh_token"]

    def test_wrong_password_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": "not-the-password"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "UNAUTHENTICATED"

    def test_unknown_email_is_indistinguishable_from_a_wrong_password(
        self, client: TestClient
    ) -> None:
        unknown = client.post(
            "/v1/auth/login", json={"email": "nobody@nowhere.test", "password": "x" * 14}
        )
        wrong = client.post("/v1/auth/login", json={"email": ACME_EMAIL, "password": "x" * 14})
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["error"]["message"] == wrong.json()["error"]["message"]

    def test_me_returns_the_signed_in_principal(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        body = client.get("/v1/auth/me", headers=headers).json()["data"]
        assert body["email"] == ACME_EMAIL
        assert body["tenant_slug"] == "acme"
        assert "lead:create" in body["permissions"]

    def test_protected_route_requires_a_session(self, client: TestClient) -> None:
        assert client.get("/v1/leads").status_code == 401

    def test_refresh_rotates_and_the_old_token_is_dead(self, client: TestClient) -> None:
        first = client.post(
            "/v1/auth/login", json={"email": ACME_EMAIL, "password": DEMO_PASSWORD}
        ).json()["data"]

        rotated = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert rotated.status_code == 200
        assert rotated.json()["data"]["refresh_token"] != first["refresh_token"]

        # Replaying the rotated token is treated as theft and refused.
        replay = client.post("/v1/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert replay.status_code == 401


class TestLeadFlow:
    def test_seeded_leads_are_listed(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        leads = client.get("/v1/leads", headers=headers).json()["data"]["leads"]
        assert len(leads) >= 2
        assert {lead["first_name"] for lead in leads} >= {"Meera", "Sunil"}

    def test_create_open_edit_and_persist(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        email = f"slice-{uuid4()}@example.in"

        created = client.post(
            "/v1/leads",
            headers=headers,
            json={"first_name": "Vertical", "last_name": "Slice", "email": email},
        )
        assert created.status_code == 201
        lead_id = created.json()["data"]["id"]

        opened = client.get(f"/v1/leads/{lead_id}", headers=headers)
        assert opened.status_code == 200
        assert opened.json()["data"]["first_name"] == "Vertical"
        etag = opened.headers["ETag"]

        edited = client.patch(
            f"/v1/leads/{lead_id}",
            headers={**headers, "If-Match": etag},
            json={"last_name": "Renamed"},
        )
        assert edited.status_code == 200

        # A fresh request -- what a browser refresh does -- sees the new value.
        reread = client.get(f"/v1/leads/{lead_id}", headers=headers).json()["data"]
        assert reread["last_name"] == "Renamed"
        assert reread["version"] == opened.json()["data"]["version"] + 1

    def test_a_stale_edit_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        created = client.post(
            "/v1/leads",
            headers=headers,
            json={"first_name": "Stale", "email": f"stale-{uuid4()}@example.in"},
        ).json()["data"]

        client.patch(
            f"/v1/leads/{created['id']}",
            headers={**headers, "If-Match": f'W/"{created["version"]}"'},
            json={"last_name": "First"},
        )
        conflict = client.patch(
            f"/v1/leads/{created['id']}",
            headers={**headers, "If-Match": f'W/"{created["version"]}"'},
            json={"last_name": "Second"},
        )
        assert conflict.status_code == 412
        assert conflict.json()["error"]["code"] == "PRECONDITION_FAILED"


class TestTenantIsolation:
    """The point of the slice: two real tenants, one database, no leakage."""

    def test_second_tenant_cannot_read_the_first_tenants_lead(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)

        lead_id = client.post(
            "/v1/leads",
            headers=acme,
            json={"first_name": "Acme", "email": f"acme-{uuid4()}@example.in"},
        ).json()["data"]["id"]

        assert client.get(f"/v1/leads/{lead_id}", headers=acme).status_code == 200

        cross = client.get(f"/v1/leads/{lead_id}", headers=globex)
        assert cross.status_code == 404, "tenant B must not read tenant A's lead"
        assert cross.json()["error"]["code"] == "NOT_FOUND"

    def test_second_tenant_cannot_edit_the_first_tenants_lead(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)

        created = client.post(
            "/v1/leads",
            headers=acme,
            json={"first_name": "Protected", "email": f"prot-{uuid4()}@example.in"},
        ).json()["data"]

        hijack = client.patch(
            f"/v1/leads/{created['id']}",
            headers={**globex, "If-Match": f'W/"{created["version"]}"'},
            json={"last_name": "Hijacked"},
        )
        assert hijack.status_code == 404

        # And the record is untouched.
        after = client.get(f"/v1/leads/{created['id']}", headers=acme).json()["data"]
        assert after["last_name"] is None
        assert after["version"] == created["version"]

    def test_each_tenants_list_contains_only_its_own_records(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)

        client.post(
            "/v1/leads",
            headers=globex,
            json={"first_name": "GlobexOnly", "email": f"gx-{uuid4()}@example.in"},
        )

        acme_names = {
            lead["first_name"]
            for lead in client.get("/v1/leads?page_size=200", headers=acme).json()["data"]["leads"]
        }
        globex_names = {
            lead["first_name"]
            for lead in client.get("/v1/leads?page_size=200", headers=globex).json()["data"][
                "leads"
            ]
        }

        assert "GlobexOnly" in globex_names
        assert "GlobexOnly" not in acme_names
        assert "Meera" in acme_names
        assert "Meera" not in globex_names

    def test_a_forged_token_for_another_tenant_is_rejected(self, client: TestClient) -> None:
        """A token signed by a different key cannot borrow another tenant's identity."""
        import jwt

        forged = jwt.encode(
            {
                "sub": str(uuid4()),
                "tenant_id": str(uuid4()),
                "jti": str(uuid4()),
                "iss": "https://api.airevenueos.io",
                "aud": "airevenueos-api",
                "exp": 9_999_999_999,
                "iat": 1,
                "permissions": ["lead:read", "lead:list"],
            },
            key="attacker-chosen-secret",
            algorithm="HS256",
        )
        response = client.get("/v1/leads", headers={"Authorization": f"Bearer {forged}"})
        assert response.status_code == 401
