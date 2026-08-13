"""Analytics over real PostgreSQL with forced RLS and durable export intents."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.e2e.test_crm_contacts_accounts import (  # noqa: F401
    ACME_EMAIL,
    GLOBEX_EMAIL,
    client,
    demo_data,
    fake_redis,
    sign_in,
    wired_engine,
)

pytestmark = pytest.mark.postgres

#: The dashboard buckets by *tenant-local* calendar day, so "today" has to be
#: asked for in the same timezone. `date.today()` is the server's, which is UTC in
#: the container: between 18:30 UTC and midnight it names yesterday in Asia/Kolkata,
#: and a lead captured just now falls outside the range the test asked for. That
#: made these assertions pass or fail on the time of day the suite happened to run.
TENANT_TZ = ZoneInfo("Asia/Kolkata")


def tenant_today() -> date:
    return datetime.now(TENANT_TZ).date()


class TestAnalyticsHttp:
    def test_dashboard_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/v1/analytics/dashboard").status_code == 401

    def test_dashboard_has_complete_honest_sections(self, client: TestClient) -> None:
        response = client.get("/v1/analytics/dashboard", headers=sign_in(client, ACME_EMAIL))
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert set(data) == {
            "period",
            "leads",
            "revenue",
            "appointments",
            "conversations",
            "sla",
            "team_performance",
            "lead_sources",
            # Added after this assertion was written, and legitimately part of the
            # dashboard: value and count by pipeline stage.
            "pipeline_by_stage",
            "daily",
            "scope",
        }
        assert len(data["daily"]) == 30
        assert data["period"]["timezone"] == "Asia/Kolkata"

    def test_invalid_or_oversized_ranges_are_refused(self, client: TestClient) -> None:
        headers = sign_in(client, ACME_EMAIL)
        assert (
            client.get(
                "/v1/analytics/dashboard?start=2026-08-02&end=2026-08-01", headers=headers
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/v1/analytics/dashboard?start=2025-01-01&end=2026-08-01", headers=headers
            ).status_code
            == 422
        )

    def test_export_requires_mfa_step_up(self, client: TestClient) -> None:
        response = client.post("/v1/analytics/exports", headers=sign_in(client, ACME_EMAIL))
        assert response.status_code == 403
        assert response.json()["error"]["details"]["step_up_required"] is True


async def test_source_metrics_do_not_cross_tenants(
    wired_engine: Any, principal_factory: Any
) -> None:
    from application.analytics.service import AnalyticsService
    from application.leads.service import LeadService

    acme = principal_factory(tenant_id=principal_factory.tenant_a)
    globex = principal_factory(tenant_id=principal_factory.tenant_b)
    marker_a = "tenant-a-exclusive-source"
    marker_b = "tenant-b-exclusive-source"
    await LeadService.for_principal(acme).capture(
        {"first_name": "Acme", "email": f"analytics-a-{uuid4()}@example.in", "source": marker_a}
    )
    await LeadService.for_principal(globex).capture(
        {"first_name": "Globex", "email": f"analytics-b-{uuid4()}@example.in", "source": marker_b}
    )

    today = tenant_today()
    acme_data = await AnalyticsService.for_principal(acme).dashboard(today, today)
    globex_data = await AnalyticsService.for_principal(globex).dashboard(today, today)
    acme_sources = {item["source"] for item in acme_data["lead_sources"]}
    globex_sources = {item["source"] for item in globex_data["lead_sources"]}
    assert marker_a in acme_sources and marker_b not in acme_sources
    assert marker_b in globex_sources and marker_a not in globex_sources


async def test_self_scope_only_aggregates_assigned_rows(
    wired_engine: Any, principal_factory: Any
) -> None:
    from application.analytics.service import AnalyticsService
    from application.leads.service import LeadService
    from domain.auth.permissions import Role

    member = principal_factory(role=Role.MEMBER)
    admin = principal_factory(tenant_id=member.tenant_id, role=Role.ADMIN)
    await LeadService.for_principal(member).capture(
        {
            "first_name": "Mine",
            "email": f"analytics-mine-{uuid4()}@example.in",
            "source": "mine",
            "assignee_id": member.user_id,
        }
    )
    await LeadService.for_principal(admin).capture(
        {
            "first_name": "Other",
            "email": f"analytics-other-{uuid4()}@example.in",
            "source": "other",
            "assignee_id": admin.user_id,
        }
    )
    today = tenant_today()
    data = await AnalyticsService.for_principal(member).dashboard(today, today)
    sources = {item["source"] for item in data["lead_sources"]}
    assert "mine" in sources
    assert "other" not in sources
    assert data["scope"] == "self"


async def test_rollup_is_idempotent_and_tenant_bound(
    wired_engine: Any, principal_factory: Any, session_factory: Any
) -> None:
    from application.analytics.service import RollupService
    from application.leads.service import LeadService

    principal = principal_factory()
    await LeadService.for_principal(principal).capture(
        {"first_name": "Rollup", "email": f"rollup-{uuid4()}@example.in", "source": "rollup-test"}
    )
    today = tenant_today()
    service = RollupService(principal.tenant_id)
    await service.refresh_day(today)
    await service.refresh_day(today)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(principal.tenant_id)},
        )
        count = (
            await session.execute(
                text(
                    "SELECT count(*) FROM analytics.daily_lead_rollups "
                    "WHERE day=:day AND source='rollup-test'"
                ),
                {"day": today},
            )
        ).scalar_one()
    assert int(count) == 1


async def test_disabled_export_records_no_file_url_and_is_audited(
    wired_engine: Any, principal_factory: Any, session_factory: Any
) -> None:
    from application.analytics.service import AnalyticsService

    principal = principal_factory()
    today = tenant_today()
    result = await AnalyticsService.for_principal(principal).request_export(
        today - timedelta(days=7), today, storage_ready=False
    )
    assert result["status"] == "blocked"
    assert result["download_available"] is False
    assert "url" not in result and "s3_key" not in result

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(principal.tenant_id)},
        )
        audit = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.audit_logs "
                    "WHERE resource_id=:rid AND action='export.created'"
                ),
                {"rid": result["id"]},
            )
        ).scalar_one()
        outbox = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.event_outbox "
                    "WHERE resource_id=:rid AND event_type='analytics.export_requested'"
                ),
                {"rid": result["id"]},
            )
        ).scalar_one()
    assert int(audit) == 1
    assert int(outbox) == 1


async def test_export_metadata_is_not_visible_to_another_tenant(
    wired_engine: Any, principal_factory: Any
) -> None:
    from application.analytics.service import AnalyticsService
    from shared.exceptions import NotFound

    acme = principal_factory(tenant_id=principal_factory.tenant_a)
    globex = principal_factory(tenant_id=principal_factory.tenant_b)
    today = tenant_today()
    export = await AnalyticsService.for_principal(acme).request_export(
        today, today, storage_ready=False
    )
    with pytest.raises(NotFound):
        await AnalyticsService.for_principal(globex).get_export(UUID(export["id"]))
