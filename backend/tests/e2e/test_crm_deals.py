"""Deals and pipelines over HTTP against real PostgreSQL with RLS forced.

The stage rules live in `domain/deals/pipeline_policy.py` and are unit tested
there. These tests check that the service actually consults the policy, that a
refusal reaches the caller as a typed 422 rather than a 500, and that none of it
leaks across tenants.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

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

pytestmark = pytest.mark.postgres


def board(client: TestClient, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get("/v1/deals/board", headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.json()["data"])


def stage_named(board_data: dict[str, Any], name: str) -> dict[str, Any]:
    return next(s for s in board_data["stages"] if s["name"] == name)


def make_deal(client: TestClient, headers: dict[str, str], **overrides: Any) -> dict[str, Any]:
    payload = {"title": f"Deal {uuid4().hex[:6]}", "amount_minor": 100_000, **overrides}
    response = client.post("/v1/deals", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


class TestPipelineProvisioning:
    def test_a_default_pipeline_appears_on_first_use(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        data = board(client, headers)
        assert data["pipeline"]["name"] == "Sales"
        assert [s["name"] for s in data["stages"]] == [
            "New",
            "Qualified",
            "Proposal",
            "Negotiation",
            "Won",
            "Lost",
        ]

    def test_provisioning_is_idempotent(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        first = board(client, headers)["pipeline"]["id"]
        second = board(client, headers)["pipeline"]["id"]
        assert first == second

    def test_each_tenant_gets_its_own_pipeline(self, client: TestClient) -> None:
        acme = board(client, sign_in(client, ACME_EMAIL))["pipeline"]["id"]
        globex = board(client, sign_in(client, GLOBEX_EMAIL))["pipeline"]["id"]
        assert acme != globex


class TestDealFlow:
    def test_a_new_deal_lands_in_the_first_stage(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        assert deal["stage_name"] == "New"
        assert deal["status"] == "open"
        # Probability is inherited from the stage, not supplied by the client.
        assert deal["probability"] == 10

    def test_it_appears_on_the_board_in_its_column(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        column = stage_named(board(client, headers), "New")
        assert any(d["id"] == deal["id"] for d in column["deals"])

    def test_a_deal_can_be_linked_to_a_contact_and_an_account(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        account = make_account(client, headers)
        contact = make_contact(client, headers, first_name="Deepa")
        deal = make_deal(client, headers, account_id=account["id"], contact_id=contact["id"])

        opened = client.get(f"/v1/deals/{deal['id']}", headers=headers).json()["data"]
        assert opened["account_name"] == account["name"]
        assert opened["contact_name"].startswith("Deepa")

    def test_editing_the_amount_persists(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        edited = client.patch(
            f"/v1/deals/{deal['id']}",
            headers={**headers, "If-Match": f'W/"{deal["version"]}"'},
            json={"amount_minor": 250_000},
        )
        assert edited.status_code == 200
        assert (
            client.get(f"/v1/deals/{deal['id']}", headers=headers).json()["data"]["amount_minor"]
            == 250_000
        )

    def test_a_stale_edit_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        stale = f'W/"{deal["version"]}"'
        assert (
            client.patch(
                f"/v1/deals/{deal['id']}",
                headers={**headers, "If-Match": stale},
                json={"title": "First"},
            ).status_code
            == 200
        )
        conflict = client.patch(
            f"/v1/deals/{deal['id']}",
            headers={**headers, "If-Match": stale},
            json={"title": "Second"},
        )
        assert conflict.status_code == 412

    def test_an_unknown_status_filter_is_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        assert client.get("/v1/deals?status=banana", headers=headers).status_code == 422


class TestStageMoves:
    def test_moving_forward_updates_stage_and_probability(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        target = stage_named(board(client, headers), "Proposal")

        moved = client.post(
            f"/v1/deals/{deal['id']}/stage",
            headers={**headers, "If-Match": f'W/"{deal["version"]}"'},
            json={"stage_id": target["id"]},
        )
        assert moved.status_code == 200, moved.text
        body = moved.json()["data"]
        assert body["stage_name"] == "Proposal"
        assert body["probability"] == 60
        assert body["status"] == "open"

    def test_moving_to_the_won_stage_closes_the_deal(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        won = stage_named(board(client, headers), "Won")

        body = client.post(
            f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": won["id"]}
        ).json()["data"]
        assert body["status"] == "won"
        assert body["closed_at"] is not None
        assert body["probability"] == 100

    def test_moving_to_lost_requires_a_reason(self, client: TestClient) -> None:
        """The domain policy refuses it, and that must reach the caller as a 422."""
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        lost = stage_named(board(client, headers), "Lost")

        refused = client.post(
            f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": lost["id"]}
        )
        assert refused.status_code == 422, "a policy violation must not surface as a 500"
        assert "loss reason" in refused.json()["error"]["message"].lower()

        accepted = client.post(
            f"/v1/deals/{deal['id']}/stage",
            headers=headers,
            json={"stage_id": lost["id"], "loss_reason": "Chose a competitor"},
        )
        assert accepted.status_code == 200
        assert accepted.json()["data"]["status"] == "lost"
        assert accepted.json()["data"]["loss_reason"] == "Chose a competitor"

    def test_a_closed_deal_cannot_move_stage_until_reopened(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        data = board(client, headers)
        won = stage_named(data, "Won")
        proposal = stage_named(data, "Proposal")

        client.post(f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": won["id"]})
        blocked = client.post(
            f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": proposal["id"]}
        )
        assert blocked.status_code == 422

        reopened = client.post(f"/v1/deals/{deal['id']}/reopen", headers=headers)
        assert reopened.status_code == 200
        assert reopened.json()["data"]["status"] == "open"
        assert reopened.json()["data"]["closed_at"] is None

        assert (
            client.post(
                f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": proposal["id"]}
            ).status_code
            == 200
        )

    def test_reopening_clears_the_loss_reason(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        lost = stage_named(board(client, headers), "Lost")
        client.post(
            f"/v1/deals/{deal['id']}/stage",
            headers=headers,
            json={"stage_id": lost["id"], "loss_reason": "Budget"},
        )
        reopened = client.post(f"/v1/deals/{deal['id']}/reopen", headers=headers).json()["data"]
        assert reopened["loss_reason"] is None

    def test_an_unknown_stage_is_404(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers)
        response = client.post(
            f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": str(uuid4())}
        )
        assert response.status_code == 404


class TestBoardTotals:
    def test_weighted_value_uses_the_domain_function(self, client: TestClient) -> None:
        """Open deals only, weighted by stage probability."""
        headers = sign_in(client, ACME_EMAIL)
        deal = make_deal(client, headers, amount_minor=1_000_000)  # 10,000 rupees, stage New (10%)

        totals = board(client, headers)["totals"]
        assert totals["open_value_minor"] >= 1_000_000
        assert totals["weighted_value_minor"] >= 100_000

        # A won deal leaves the weighted figure and enters the won figure.
        won = stage_named(board(client, headers), "Won")
        client.post(f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": won["id"]})

        after = board(client, headers)["totals"]
        assert after["won_value_minor"] >= 1_000_000
        assert after["open_count"] == totals["open_count"] - 1


class TestDealTenantIsolation:
    def test_another_tenant_cannot_read_the_deal(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        deal = make_deal(client, acme, title="AcmeSecretDeal")

        assert client.get(f"/v1/deals/{deal['id']}", headers=acme).status_code == 200
        assert client.get(f"/v1/deals/{deal['id']}", headers=globex).status_code == 404

    def test_another_tenant_cannot_move_or_reopen_it(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        deal = make_deal(client, acme)
        stage = stage_named(board(client, acme), "Proposal")

        assert (
            client.post(
                f"/v1/deals/{deal['id']}/stage", headers=globex, json={"stage_id": stage["id"]}
            ).status_code
            == 404
        )
        assert client.post(f"/v1/deals/{deal['id']}/reopen", headers=globex).status_code == 404

    def test_neither_board_shows_the_others_deals(self, client: TestClient) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        deal = make_deal(client, acme, title="AcmeOnlyDeal")

        globex_ids = {
            d["id"] for column in board(client, globex)["stages"] for d in column["deals"]
        }
        assert deal["id"] not in globex_ids

    def test_a_deal_cannot_be_created_against_another_tenants_account(
        self, client: TestClient
    ) -> None:
        acme = sign_in(client, ACME_EMAIL)
        globex = sign_in(client, GLOBEX_EMAIL)
        acme_account = make_account(client, acme)

        response = client.post(
            "/v1/deals",
            headers=globex,
            json={"title": "Cross tenant", "account_id": acme_account["id"]},
        )
        assert response.status_code == 404

    def test_an_anonymous_caller_is_refused(self, client: TestClient) -> None:
        for method, path in (
            ("get", "/v1/deals"),
            ("get", "/v1/deals/board"),
            ("post", "/v1/deals"),
        ):
            assert getattr(client, method)(path).status_code == 401


class TestDealAuditAndOutbox:
    def test_a_stage_move_writes_its_events_and_audit_row(
        self, client: TestClient, wired_engine: Any
    ) -> None:
        import asyncio

        from sqlalchemy import text

        headers = sign_in(client, ACME_EMAIL)
        tenant_id = str(client.get("/v1/auth/me", headers=headers).json()["data"]["tenant_id"])
        deal = make_deal(client, headers)
        won = stage_named(board(client, headers), "Won")
        client.post(f"/v1/deals/{deal['id']}/stage", headers=headers, json={"stage_id": won["id"]})

        async def counts() -> tuple[int, int, int]:
            async with wired_engine.begin() as conn:
                await conn.execute(
                    text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                stage_changed = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'opportunity.stage_changed'"
                    ),
                    {"rid": deal["id"]},
                )
                won_event = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.event_outbox WHERE resource_id = :rid "
                        "AND event_type = 'opportunity.won'"
                    ),
                    {"rid": deal["id"]},
                )
                audits = await conn.execute(
                    text(
                        "SELECT count(*) FROM audit.audit_logs WHERE resource_id = :rid "
                        "AND action = 'deal.stage_change'"
                    ),
                    {"rid": deal["id"]},
                )
                return (
                    int(stage_changed.scalar_one()),
                    int(won_event.scalar_one()),
                    int(audits.scalar_one()),
                )

        stage_changed, won_event, audits = asyncio.new_event_loop().run_until_complete(counts())
        assert stage_changed == 1
        assert won_event == 1, "winning a deal must emit its own event"
        assert audits == 1
