"""Tasks over HTTP against real PostgreSQL with RLS forced."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from shared.utils.timeutil import utcnow
from tests.e2e.test_crm_contacts_accounts import (  # noqa: F401
    ACME_EMAIL,
    GLOBEX_EMAIL,
    client,
    demo_data,
    fake_redis,
    make_account,
    make_contact,
    sign_in,
    wired_engine,
)
from tests.e2e.test_crm_deals import make_deal

pytestmark = pytest.mark.postgres


def make_task(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {"title": f"Follow up {uuid4().hex[:6]}", **overrides}
    response = client.post("/v1/tasks", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestTaskFlow:
    def test_create_list_and_complete(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        task = make_task(client, headers, title="Call the customer")
        assert task["status"] == "open"
        assert task["assignee_name"] == "Asha Kumar"

        listed = client.get("/v1/tasks", headers=headers).json()["data"]["tasks"]
        assert any(t["id"] == task["id"] for t in listed)

        done = client.patch(
            f"/v1/tasks/{task['id']}",
            headers={**headers, "If-Match": f'W/"{task["version"]}"'},
            json={"status": "completed"},
        )
        assert done.status_code == 200
        body = done.json()["data"]
        assert body["status"] == "completed"
        # Set by the server, never accepted from the client.
        assert body["completed_at"] is not None

    def test_reopening_clears_the_completion_time(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        task = make_task(client, headers)
        client.patch(f"/v1/tasks/{task['id']}", headers=headers, json={"status": "completed"})
        reopened = client.patch(
            f"/v1/tasks/{task['id']}", headers=headers, json={"status": "open"}
        ).json()["data"]
        assert reopened["completed_at"] is None

    def test_a_task_can_hang_off_a_contact_or_a_deal(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        contact = make_contact(client, headers)
        deal = make_deal(client, headers)

        make_task(client, headers, entity_type="contact", entity_id=contact["id"])
        make_task(client, headers, entity_type="deal", entity_id=deal["id"])

        on_contact = client.get(f"/v1/contacts/{contact['id']}/tasks", headers=headers).json()[
            "data"
        ]["tasks"]
        on_deal = client.get(f"/v1/deals/{deal['id']}/tasks", headers=headers).json()["data"][
            "tasks"
        ]
        assert len(on_contact) == 1
        assert len(on_deal) == 1
        assert on_contact[0]["id"] != on_deal[0]["id"]

    def test_a_task_can_stand_alone(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        task = make_task(client, headers)
        assert task["entity_type"] is None

    def test_an_entity_type_without_an_id_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/tasks", headers=headers, json={"title": "Half a link", "entity_type": "contact"}
        )
        assert response.status_code == 422

    def test_an_unknown_priority_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        response = client.post(
            "/v1/tasks", headers=headers, json={"title": "X", "priority": "screaming"}
        )
        assert response.status_code == 422

    def test_a_stale_edit_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        task = make_task(client, headers)
        stale = f'W/"{task["version"]}"'
        assert (
            client.patch(
                f"/v1/tasks/{task['id']}",
                headers={**headers, "If-Match": stale},
                json={"title": "First"},
            ).status_code
            == 200
        )
        assert (
            client.patch(
                f"/v1/tasks/{task['id']}",
                headers={**headers, "If-Match": stale},
                json={"title": "Second"},
            ).status_code
            == 412
        )


class TestOverdue:
    def test_overdueness_is_decided_by_the_server(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        past = (utcnow() - timedelta(days=1)).isoformat()
        future = (utcnow() + timedelta(days=7)).isoformat()

        late = make_task(client, headers, title="Late one", due_at=past)
        soon = make_task(client, headers, title="Later one", due_at=future)

        assert late["is_overdue"] is True
        assert soon["is_overdue"] is False

    def test_a_completed_task_is_never_overdue(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        past = (utcnow() - timedelta(days=1)).isoformat()
        task = make_task(client, headers, due_at=past)
        assert task["is_overdue"] is True

        done = client.patch(
            f"/v1/tasks/{task['id']}", headers=headers, json={"status": "completed"}
        ).json()["data"]
        assert done["is_overdue"] is False

    def test_the_overdue_filter_matches(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        past = (utcnow() - timedelta(days=2)).isoformat()
        late = make_task(client, headers, due_at=past)
        make_task(client, headers)  # no due date

        overdue = client.get("/v1/tasks?overdue=true", headers=headers).json()["data"]["tasks"]
        ids = {t["id"] for t in overdue}
        assert late["id"] in ids
        assert all(t["is_overdue"] for t in overdue)

    def test_the_mine_filter_matches(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        task = make_task(client, headers)
        mine = client.get("/v1/tasks?mine=true", headers=headers).json()["data"]["tasks"]
        assert any(t["id"] == task["id"] for t in mine)


class TestTaskTenantIsolation:
    def test_another_tenant_cannot_read_the_task(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        task = make_task(client, acme, title="AcmeSecretTask")

        assert client.get(f"/v1/tasks/{task['id']}", headers=acme).status_code == 200
        assert client.get(f"/v1/tasks/{task['id']}", headers=globex).status_code == 404

    def test_another_tenant_cannot_complete_it(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        task = make_task(client, acme)

        assert (
            client.patch(
                f"/v1/tasks/{task['id']}", headers=globex, json={"status": "completed"}
            ).status_code
            == 404
        )
        assert (
            client.get(f"/v1/tasks/{task['id']}", headers=acme).json()["data"]["status"] == "open"
        )

    def test_a_task_cannot_be_attached_to_another_tenants_record(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        acme_contact = make_contact(client, acme)

        response = client.post(
            "/v1/tasks",
            headers=globex,
            json={
                "title": "Cross tenant",
                "entity_type": "contact",
                "entity_id": acme_contact["id"],
            },
        )
        assert response.status_code == 404

    def test_neither_listing_contains_the_others_tasks(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        task = make_task(client, acme, title="AcmeOnlyTask")

        globex_ids = {
            t["id"]
            for t in client.get("/v1/tasks?page_size=200", headers=globex).json()["data"]["tasks"]
        }
        assert task["id"] not in globex_ids

    def test_another_tenant_cannot_read_a_records_task_list(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        contact = make_contact(client, acme)
        assert client.get(f"/v1/contacts/{contact['id']}/tasks", headers=globex).status_code == 404

    def test_an_anonymous_caller_is_refused(self, client: TestClient) -> None:
        assert client.get("/v1/tasks").status_code == 401
        assert client.post("/v1/tasks", json={"title": "X"}).status_code == 401


class TestTaskEvents:
    def test_completing_emits_task_completed_not_task_updated(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        task = make_task(client, headers)
        client.patch(f"/v1/tasks/{task['id']}", headers=headers, json={"status": "completed"})

        async def counts() -> tuple[int, int, int]:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                created = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'task.created'"
                    ),
                    {"rid": task["id"]},
                )
                completed = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'task.completed'"
                    ),
                    {"rid": task["id"]},
                )
                audits = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid "
                        "AND action = 'task.complete'"
                    ),
                    {"rid": task["id"]},
                )
                return (
                    int(created.scalar_one()),
                    int(completed.scalar_one()),
                    int(audits.scalar_one()),
                )

        created, completed, audits = asyncio.new_event_loop().run_until_complete(counts())
        assert created == 1
        assert completed == 1, "completion is its own event, not a generic update"
        assert audits == 1
