"""Contacts and accounts over HTTP against real PostgreSQL with RLS forced.

Focused on the four things this scope has to guarantee and nothing else: the
usable flow, optimistic concurrency, cross-tenant denial, and that the outbox
events reach a real handler rather than a stub.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.postgres

DEMO_PASSWORD = "crm-suite-passphrase-2026"
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


def make_contact(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {
        "first_name": "Priya",
        "last_name": "Nair",
        "email": f"priya-{uuid4().hex[:10]}@example.in",
        **overrides,
    }
    response = client.post("/v1/contacts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def make_account(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {"name": f"Sharma Motors {uuid4().hex[:6]}", **overrides}
    response = client.post("/v1/accounts", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestContactFlow:
    def test_create_list_open_and_edit(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        created = make_contact(client, headers, first_name="Kavita")

        listed = client.get("/v1/contacts", headers=headers)
        assert listed.status_code == 200
        assert any(c["id"] == created["id"] for c in listed.json()["data"]["contacts"])

        opened = client.get(f"/v1/contacts/{created['id']}", headers=headers)
        assert opened.status_code == 200
        assert opened.json()["data"]["first_name"] == "Kavita"
        etag = opened.headers["ETag"]

        edited = client.patch(
            f"/v1/contacts/{created['id']}",
            headers={**headers, "If-Match": etag},
            json={"title": "Head of Sales"},
        )
        assert edited.status_code == 200

        # A fresh read -- what a browser refresh does -- sees the new value.
        reread = client.get(f"/v1/contacts/{created['id']}", headers=headers).json()["data"]
        assert reread["title"] == "Head of Sales"
        assert reread["version"] == opened.json()["data"]["version"] + 1

    def test_search_matches_name_email_and_company(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        token = uuid4().hex[:8]
        make_contact(client, headers, first_name=f"Zz{token}", company=f"Widgets{token}")

        for term in (f"zz{token}", f"widgets{token}"):
            found = client.get(f"/v1/contacts?search={term}", headers=headers).json()["data"][
                "contacts"
            ]
            assert len(found) == 1, f"search {term!r} returned {len(found)}"

    def test_search_returns_nothing_for_an_unmatched_term(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        found = client.get("/v1/contacts?search=nobodyhasthisname", headers=headers)
        assert found.status_code == 200
        assert found.json()["data"]["contacts"] == []

    def test_a_contact_needs_an_email_or_a_phone(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post("/v1/contacts", headers=headers, json={"first_name": "Anon"})
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_a_stale_edit_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        created = make_contact(client, headers)
        stale = f'W/"{created["version"]}"'

        first = client.patch(
            f"/v1/contacts/{created['id']}",
            headers={**headers, "If-Match": stale},
            json={"title": "First"},
        )
        assert first.status_code == 200

        conflict = client.patch(
            f"/v1/contacts/{created['id']}",
            headers={**headers, "If-Match": stale},
            json={"title": "Second"},
        )
        assert conflict.status_code == 412
        assert conflict.json()["error"]["code"] == "PRECONDITION_FAILED"

    def test_an_unknown_status_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        created = make_contact(client, headers)
        response = client.patch(
            f"/v1/contacts/{created['id']}", headers=headers, json={"status": "banana"}
        )
        assert response.status_code == 422


class TestAccountLinking:
    def test_a_contact_can_be_created_against_an_account(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        contact = make_contact(client, headers, account_id=account["id"])

        assert contact["account_id"] == account["id"]
        assert contact["account_name"] == account["name"]

    def test_an_existing_contact_can_be_linked_and_unlinked(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        contact = make_contact(client, headers)

        linked = client.patch(
            f"/v1/contacts/{contact['id']}", headers=headers, json={"account_id": account["id"]}
        )
        assert linked.status_code == 200
        assert linked.json()["data"]["account_name"] == account["name"]

        # Explicit null means unlink, which is why the route uses exclude_unset.
        unlinked = client.patch(
            f"/v1/contacts/{contact['id']}", headers=headers, json={"account_id": None}
        )
        assert unlinked.status_code == 200
        assert unlinked.json()["data"]["account_id"] is None

    def test_the_account_lists_its_contacts(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        first = make_contact(client, headers, account_id=account["id"])
        make_contact(client, headers)  # not linked

        response = client.get(f"/v1/accounts/{account['id']}/contacts", headers=headers)
        assert response.status_code == 200
        ids = [c["id"] for c in response.json()["data"]["contacts"]]
        assert ids == [first["id"]]

        assert (
            client.get(f"/v1/accounts/{account['id']}", headers=headers).json()["data"][
                "contact_count"
            ]
            == 1
        )

    def test_linking_to_an_unknown_account_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/contacts",
            headers=headers,
            json={
                "first_name": "Orphan",
                "email": f"orphan-{uuid4().hex[:8]}@example.in",
                "account_id": str(uuid4()),
            },
        )
        assert response.status_code == 404

    def test_a_duplicate_account_name_is_a_conflict_not_a_500(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        again = client.post("/v1/accounts", headers=headers, json={"name": account["name"]})
        assert again.status_code == 409


class TestTenantIsolation:
    """Two real tenants, one database, no leakage."""

    def test_a_second_tenant_cannot_read_the_first_tenants_contact(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme, first_name="AcmePrivate")

        assert client.get(f"/v1/contacts/{contact['id']}", headers=acme).status_code == 200
        cross = client.get(f"/v1/contacts/{contact['id']}", headers=globex)
        assert cross.status_code == 404
        assert cross.json()["error"]["code"] == "NOT_FOUND"

    def test_a_second_tenant_cannot_edit_the_first_tenants_contact(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme, title="Original")

        hijack = client.patch(
            f"/v1/contacts/{contact['id']}", headers=globex, json={"title": "Hijacked"}
        )
        assert hijack.status_code == 404

        after = client.get(f"/v1/contacts/{contact['id']}", headers=acme).json()["data"]
        assert after["title"] == "Original"

    def test_a_second_tenant_cannot_read_the_first_tenants_account(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        account = make_account(client, acme)

        assert client.get(f"/v1/accounts/{account['id']}", headers=globex).status_code == 404
        assert (
            client.get(f"/v1/accounts/{account['id']}/contacts", headers=globex).status_code == 404
        )

    def test_neither_listing_contains_the_others_records(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        acme_contact = make_contact(client, acme, first_name="AcmeOnly")
        globex_contact = make_contact(client, globex, first_name="GlobexOnly")

        acme_ids = {
            c["id"]
            for c in client.get("/v1/contacts?page_size=200", headers=acme).json()["data"][
                "contacts"
            ]
        }
        globex_ids = {
            c["id"]
            for c in client.get("/v1/contacts?page_size=200", headers=globex).json()["data"][
                "contacts"
            ]
        }
        assert acme_contact["id"] in acme_ids and acme_contact["id"] not in globex_ids
        assert globex_contact["id"] in globex_ids and globex_contact["id"] not in acme_ids

    def test_a_contact_cannot_be_linked_to_another_tenants_account(
        self, client: TestClient
    ) -> None:
        """The interesting one: a valid id that belongs to somebody else."""
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        acme_account = make_account(client, acme)

        response = client.post(
            "/v1/contacts",
            headers=globex,
            json={
                "first_name": "CrossTenant",
                "email": f"cross-{uuid4().hex[:8]}@example.in",
                "account_id": acme_account["id"],
            },
        )
        assert response.status_code == 404, "another tenant's account must be invisible"

    def test_an_anonymous_caller_is_refused_everywhere(self, client: TestClient) -> None:
        for method, path in (
            ("get", "/v1/contacts"),
            ("post", "/v1/contacts"),
            ("get", "/v1/accounts"),
            ("post", "/v1/accounts"),
        ):
            assert getattr(client, method)(path).status_code == 401, f"{method} {path}"


class TestOutboxAndAudit:
    def test_creating_a_contact_writes_an_outbox_event_and_an_audit_row(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        """Both rows land in the same transaction as the contact.

        The audit read binds `app.tenant_id` first. `audit.audit_logs` carries the
        tenant policy, so an unbound connection is shown nothing -- which is the
        policy working, and would otherwise read as a missing audit trail.
        """
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = _tenant_of(client, headers)
        contact = make_contact(client, headers)

        async def counts() -> tuple[int, int]:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                events = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox "
                        "WHERE resource_id = :rid AND event_type = 'contact.created'"
                    ),
                    {"rid": contact["id"]},
                )
                audits = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.audit_logs "
                        "WHERE resource_id = :rid AND action = 'contact.create'"
                    ),
                    {"rid": contact["id"]},
                )
                return int(events.scalar_one()), int(audits.scalar_one())

        outbox, audit = asyncio.new_event_loop().run_until_complete(counts())
        assert outbox == 1, "the state change and its event must commit together"
        assert audit == 1, "the audit trail is written in the same transaction"

    def test_the_audit_trail_is_invisible_to_another_tenant(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        """The corollary of the above: audit rows are tenant data too."""
        import asyncio

        from sqlalchemy import text

        acme = sign_in(client, ACME_EMAIL)
        globex_tenant = _tenant_of(client, sign_in(client, GLOBEX_EMAIL))
        contact = make_contact(client, acme)

        async def count_as_globex() -> int:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"),
                    {"tid": globex_tenant},
                )
                result = await conn.execute(
                    text("SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid"),
                    {"rid": contact["id"]},
                )
                return int(result.scalar_one())

        assert asyncio.new_event_loop().run_until_complete(count_as_globex()) == 0

    def test_the_handler_stamps_the_account_name_onto_the_contact(self, client: TestClient) -> None:
        """A real handler, not `pending_handler`: the effect is observable."""
        import asyncio

        from application.crm.handlers import sync_contact_company

        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        contact = make_contact(client, headers, account_id=account["id"])
        assert contact["company"] is None

        event = {
            "event_type": "contact.created",
            "tenant_id": _tenant_of(client, headers),
            "resource_id": contact["id"],
        }
        asyncio.new_event_loop().run_until_complete(sync_contact_company(event))

        after = client.get(f"/v1/contacts/{contact['id']}", headers=headers).json()["data"]
        assert after["company"] == account["name"]

    def test_renaming_an_account_propagates_to_its_contacts(self, client: TestClient) -> None:
        import asyncio

        from application.crm.handlers import propagate_account_rename, sync_contact_company

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = _tenant_of(client, headers)
        account = make_account(client, headers)
        contact = make_contact(client, headers, account_id=account["id"])

        loop = asyncio.new_event_loop()
        loop.run_until_complete(
            sync_contact_company(
                {
                    "event_type": "contact.created",
                    "tenant_id": tenant_id,
                    "resource_id": contact["id"],
                }
            )
        )

        renamed = f"Renamed {uuid4().hex[:6]}"
        client.patch(f"/v1/accounts/{account['id']}", headers=headers, json={"name": renamed})
        loop.run_until_complete(
            propagate_account_rename(
                {
                    "event_type": "account.updated",
                    "tenant_id": tenant_id,
                    "resource_id": account["id"],
                }
            )
        )

        after = client.get(f"/v1/contacts/{contact['id']}", headers=headers).json()["data"]
        assert after["company"] == renamed

    def test_the_handler_is_idempotent(self, client: TestClient) -> None:
        """The relay is at-least-once, so running twice must change nothing."""
        import asyncio

        from application.crm.handlers import sync_contact_company

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = _tenant_of(client, headers)
        account = make_account(client, headers)
        contact = make_contact(client, headers, account_id=account["id"])
        event = {
            "event_type": "contact.created",
            "tenant_id": tenant_id,
            "resource_id": contact["id"],
        }

        loop = asyncio.new_event_loop()
        loop.run_until_complete(sync_contact_company(event))
        first = client.get(f"/v1/contacts/{contact['id']}", headers=headers).json()["data"]
        loop.run_until_complete(sync_contact_company(event))
        second = client.get(f"/v1/contacts/{contact['id']}", headers=headers).json()["data"]

        assert first == second

    def test_the_handler_does_not_overwrite_a_company_a_human_set(self, client: TestClient) -> None:
        import asyncio

        from application.crm.handlers import sync_contact_company

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = _tenant_of(client, headers)
        account = make_account(client, headers)
        contact = make_contact(client, headers, account_id=account["id"], company="Chosen By Hand")

        asyncio.new_event_loop().run_until_complete(
            sync_contact_company(
                {
                    "event_type": "contact.created",
                    "tenant_id": tenant_id,
                    "resource_id": contact["id"],
                }
            )
        )
        after = client.get(f"/v1/contacts/{contact['id']}", headers=headers).json()["data"]
        assert after["company"] == "Chosen By Hand"


def _tenant_of(client: TestClient, headers: dict[str, str]) -> str:
    return str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
