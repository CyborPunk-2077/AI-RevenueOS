"""Branch/team/self scope must filter list queries, not merely exist as a method.

`TenantRepository.apply_scope` was previously dead code: no service called it, so a
Member with `self` scope saw every lead in the tenant. These tests fail against that
version.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from api.deps.principal import ListQuery
from application.leads.service import LeadService
from domain.auth.permissions import Role, Scope, permissions_for

pytestmark = pytest.mark.postgres


def service_for(
    tenant_id, *, user_id=None, scope=Scope.GLOBAL, branch_ids=frozenset(), team_ids=frozenset()
) -> LeadService:
    return LeadService(
        tenant_id=tenant_id,
        user_id=user_id or uuid4(),
        permissions=permissions_for([Role.MEMBER]),
        scope=scope,
        branch_ids=branch_ids,
        team_ids=team_ids,
    )


async def _seed(admin: LeadService, **over):  # type: ignore[no-untyped-def]
    payload = {"first_name": "Scoped", "email": f"{uuid4()}@example.in"}
    payload.update(over)
    return await admin.capture(payload)


class TestSelfScope:
    async def test_member_sees_only_leads_assigned_to_them(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        mine, theirs = uuid4(), uuid4()

        await _seed(admin, first_name="Mine", assignee_id=mine)
        await _seed(admin, first_name="Theirs", assignee_id=theirs)

        member = service_for(tenant, user_id=mine, scope=Scope.SELF)
        names = {item["first_name"] for item in (await member.list_leads(ListQuery())).items}

        assert "Mine" in names
        assert "Theirs" not in names

    async def test_self_scope_excludes_unassigned_leads(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        await _seed(admin, first_name="Unassigned")

        member = service_for(tenant, user_id=uuid4(), scope=Scope.SELF)
        names = {item["first_name"] for item in (await member.list_leads(ListQuery())).items}
        assert "Unassigned" not in names

    async def test_global_scope_still_sees_everything_in_the_tenant(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        created = await _seed(admin, first_name="VisibleToAdmin", assignee_id=uuid4())

        ids = {item["id"] for item in (await admin.list_leads(ListQuery(page_size=200))).items}
        assert created["id"] in ids


class TestTeamAndBranchScope:
    async def test_team_scope_filters_to_the_principals_teams(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        my_team, other_team = uuid4(), uuid4()

        await _seed(admin, first_name="MyTeamLead", team_id=my_team)
        await _seed(admin, first_name="OtherTeamLead", team_id=other_team)

        manager = service_for(tenant, scope=Scope.TEAM, team_ids=frozenset({str(my_team)}))
        names = {item["first_name"] for item in (await manager.list_leads(ListQuery())).items}

        assert "MyTeamLead" in names
        assert "OtherTeamLead" not in names

    async def test_branch_scope_filters_to_the_principals_branches(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        my_branch, other_branch = uuid4(), uuid4()

        await _seed(admin, first_name="MyBranchLead", branch_id=my_branch)
        await _seed(admin, first_name="OtherBranchLead", branch_id=other_branch)

        viewer = service_for(tenant, scope=Scope.BRANCH, branch_ids=frozenset({str(my_branch)}))
        names = {item["first_name"] for item in (await viewer.list_leads(ListQuery())).items}

        assert "MyBranchLead" in names
        assert "OtherBranchLead" not in names


class TestScopeFailsClosed:
    async def test_team_scope_without_teams_returns_nothing(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        await _seed(service_for(tenant), first_name="Existing", team_id=uuid4())

        orphan = service_for(tenant, scope=Scope.TEAM, team_ids=frozenset())
        assert (await orphan.list_leads(ListQuery())).items == []

    async def test_branch_scope_without_branches_returns_nothing(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        await _seed(service_for(tenant), first_name="Existing", branch_id=uuid4())

        orphan = service_for(tenant, scope=Scope.BRANCH, branch_ids=frozenset())
        assert (await orphan.list_leads(ListQuery())).items == []


class TestScopeComposesWithTenantIsolation:
    async def test_scope_never_widens_past_the_tenant_boundary(
        self, wired_engine, principal_factory
    ) -> None:
        """A global-scope principal in tenant B still cannot see tenant A's rows."""
        shared_user = uuid4()
        a = service_for(principal_factory.tenant_a, user_id=shared_user)
        b = service_for(principal_factory.tenant_b, user_id=shared_user)

        secret = await _seed(a, first_name="TenantAOnly", assignee_id=shared_user)

        b_ids = {item["id"] for item in (await b.list_leads(ListQuery(page_size=200))).items}
        assert secret["id"] not in b_ids


class TestObjectLevelScope:
    """Scoping only list queries would leave an in-tenant IDOR."""

    async def test_member_cannot_read_another_users_lead_by_id(
        self, wired_engine, principal_factory
    ) -> None:
        from shared.exceptions import NotFound

        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        mine, theirs = uuid4(), uuid4()

        other = await _seed(admin, first_name="NotMine", assignee_id=theirs)

        member = service_for(tenant, user_id=mine, scope=Scope.SELF)
        with pytest.raises(NotFound):
            await member.get(other["id"])

    async def test_member_cannot_update_another_users_lead(
        self, wired_engine, principal_factory
    ) -> None:
        from shared.exceptions import NotFound

        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        theirs = uuid4()
        other = await _seed(admin, first_name="NotMine", assignee_id=theirs)

        member = service_for(tenant, user_id=uuid4(), scope=Scope.SELF)
        with pytest.raises(NotFound):
            await member.update(other["id"], {"last_name": "Hijacked"})

    async def test_member_can_read_and_update_their_own_lead(
        self, wired_engine, principal_factory
    ) -> None:
        tenant = principal_factory.tenant_a
        admin = service_for(tenant)
        mine = uuid4()
        own = await _seed(admin, first_name="Mine", assignee_id=mine)

        member = service_for(tenant, user_id=mine, scope=Scope.SELF)
        assert (await member.get(own["id"]))["id"] == own["id"]
        updated = await member.update(own["id"], {"last_name": "Verified"})
        assert updated["last_name"] == "Verified"

    async def test_out_of_scope_and_absent_are_indistinguishable(
        self, wired_engine, principal_factory
    ) -> None:
        from shared.exceptions import NotFound

        tenant = principal_factory.tenant_a
        other = await _seed(service_for(tenant), first_name="Hidden", assignee_id=uuid4())
        member = service_for(tenant, user_id=uuid4(), scope=Scope.SELF)

        with pytest.raises(NotFound) as out_of_scope:
            await member.get(other["id"])
        with pytest.raises(NotFound) as absent:
            await member.get(uuid4())
        assert str(out_of_scope.value) == str(absent.value)
