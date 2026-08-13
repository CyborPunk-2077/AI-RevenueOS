"""A pilot SME gets a workspace of its own, and nothing can reach into it.

Two claims are being pinned here, and they are the two a real business is
entitled to before it puts its enquiries into somebody else's software:

* the workspace it gets is **internally consistent** - a manager who is told they
  can see their team's work actually has a team, which is precisely what session 4
  proved does not happen by itself;
* the workspace is **unreachable** from every maintenance path that exists. Not
  because the delete is careful, but because a pilot's rows were never recorded in
  any demo manifest and therefore are not candidates for deletion at all.

Run against the real schema through `admin_session`, in tenants this file creates
and removes. The claim is about what a delete can reach in production-shaped
tables, so an in-memory stand-in would prove nothing.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text

from application.tenants.demo_data import (
    delete_recorded_rows,
    empty_manifest,
    record_manifest,
)
from application.tenants.provisioning import (
    PILOT,
    REAL_WORKSPACE_KINDS,
    TEST,
    Person,
    WorkspaceSpec,
    provision_workspace,
    workspace_kind,
)
from domain.auth.permissions import ROLE_PERMISSIONS, Role
from infrastructure.database.session import admin_session
from shared.utils.ids import uuid7

pytestmark = [pytest.mark.postgres, pytest.mark.asyncio]

PILOT_TENANT = UUID("01890000-0000-7000-8000-0000000b1101")
DEMO_TENANT = UUID("01890000-0000-7000-8000-0000000b1102")

# A password hash, not a password. Provisioning takes the hash, so no test here
# ever holds a credential.
HASH = "$2b$12$abcdefghijklmnopqrstuvwxyz0123456789ABCDEFGHIJKLMNOPQRSTUV"

PEOPLE = (
    Person(email="owner@pilot.test", full_name="Pilot Owner", role=Role.OWNER, scope="global"),
    Person(email="manager@pilot.test", full_name="Pilot Manager", role=Role.MANAGER, scope="team"),
    Person(email="sales@pilot.test", full_name="Pilot Sales", role=Role.MEMBER, scope="self"),
)


def _spec(tenant_id: UUID = PILOT_TENANT, *, kind: str = PILOT, slug: str = "pilot-under-test"):
    return WorkspaceSpec(
        tenant_id=tenant_id,
        name="Pilot Under Test",
        slug=slug,
        kind=kind,
        people=PEOPLE,
        city="Mysuru",
        state="Karnataka",
    )


async def _lead(session: Any, tenant_id: UUID, name: str) -> UUID:
    lead_id = uuid7()
    await session.execute(
        text(
            "INSERT INTO app.leads (id, tenant_id, first_name, source, capture, utm,"
            " reasoning, status, version, created_at, updated_at)"
            " VALUES (:id, :t, :name, 'manual', '{}', '{}', '{}', 'new', 1, now(), now())"
        ),
        {"id": lead_id, "t": tenant_id, "name": name},
    )
    return lead_id


async def _exists(session: Any, table: str, row_id: UUID) -> bool:
    found = await session.execute(
        text(f"SELECT 1 FROM app.{table} WHERE id = :id"),  # noqa: S608 - fixed literals
        {"id": row_id},
    )
    return found.scalar_one_or_none() is not None


@pytest.fixture
async def db() -> Any:
    async with admin_session() as session:
        yield session
        for table in ("team_members", "teams", "branches", "user_roles", "role_permissions"):
            await session.execute(
                text(f"DELETE FROM app.{table} WHERE tenant_id = ANY(:ids)"),  # noqa: S608
                {"ids": [PILOT_TENANT, DEMO_TENANT]},
            )
        for table in ("tasks", "notes", "leads", "users", "roles"):
            await session.execute(
                text(f"DELETE FROM app.{table} WHERE tenant_id = ANY(:ids)"),  # noqa: S608
                {"ids": [PILOT_TENANT, DEMO_TENANT]},
            )
        await session.execute(
            text("DELETE FROM app.tenants WHERE id = ANY(:ids)"),
            {"ids": [PILOT_TENANT, DEMO_TENANT]},
        )


class TestTheWorkspaceItself:
    async def test_a_pilot_gets_its_own_tenant_with_indian_defaults(self, db: Any) -> None:
        result = await provision_workspace(db, _spec(), password_hash=HASH)
        assert result.created_tenant

        row = (
            await db.execute(
                text("SELECT timezone, currency, locale, status FROM app.tenants WHERE id = :t"),
                {"t": PILOT_TENANT},
            )
        ).one()
        assert row.timezone == "Asia/Kolkata"
        assert row.currency == "INR"
        assert row.locale == "en-IN"
        assert row.status == "active"

    async def test_the_workspace_knows_it_is_a_pilot(self, db: Any) -> None:
        await provision_workspace(db, _spec(), password_hash=HASH)
        assert await workspace_kind(db, PILOT_TENANT) == PILOT
        # And that is what makes the destructive guards treat it as real data.
        assert PILOT in REAL_WORKSPACE_KINDS

    async def test_provisioning_is_idempotent(self, db: Any) -> None:
        first = await provision_workspace(db, _spec(), password_hash=HASH)
        second = await provision_workspace(db, _spec(), password_hash=HASH)

        assert first.created_tenant is True
        assert second.created_tenant is False
        assert second.created_users == []
        assert first.users == second.users
        assert first.team_id == second.team_id

    async def test_a_rerun_does_not_reset_a_real_persons_password(self, db: Any) -> None:
        await provision_workspace(db, _spec(), password_hash=HASH)
        # The pilot user changes their password, as they are told to.
        await db.execute(
            text("UPDATE app.users SET password_hash = :h WHERE tenant_id = :t"),
            {"h": "their-own-choice", "t": PILOT_TENANT},
        )

        await provision_workspace(db, _spec(), password_hash=HASH, reset_credentials=False)

        hashes = [
            row[0]
            for row in await db.execute(
                text("SELECT password_hash FROM app.users WHERE tenant_id = :t"),
                {"t": PILOT_TENANT},
            )
        ]
        assert set(hashes) == {"their-own-choice"}


class TestRolesAndTeams:
    async def test_each_role_gets_the_scope_it_was_asked_for(self, db: Any) -> None:
        await provision_workspace(db, _spec(), password_hash=HASH)

        scopes = {
            row.name: row.default_scope
            for row in await db.execute(
                text("SELECT name, default_scope FROM app.roles WHERE tenant_id = :t"),
                {"t": PILOT_TENANT},
            )
        }
        assert scopes == {"owner": "global", "manager": "team", "member": "self"}

    async def test_permissions_come_from_the_domain_not_from_hand(self, db: Any) -> None:
        await provision_workspace(db, _spec(), password_hash=HASH)

        for role in (Role.OWNER, Role.MANAGER, Role.MEMBER):
            granted = {
                row[0]
                for row in await db.execute(
                    text(
                        "SELECT rp.permission_code FROM app.role_permissions rp"
                        " JOIN app.roles r ON r.id = rp.role_id"
                        " WHERE rp.tenant_id = :t AND r.name = :name"
                    ),
                    {"t": PILOT_TENANT, "name": role.value},
                )
            }
            assert granted == set(ROLE_PERMISSIONS[role]), role

    async def test_a_team_scoped_manager_actually_has_a_team(self, db: Any) -> None:
        """The session-4 defect, pinned.

        A manager whose scope is `team` and who belongs to no team filters on an
        empty set and matches nothing at all - every record is "not found". A
        workspace has to be internally consistent, not merely populated.
        """
        result = await provision_workspace(db, _spec(), password_hash=HASH)

        members = {
            row[0]
            for row in await db.execute(
                text("SELECT user_id FROM app.team_members WHERE team_id = :team"),
                {"team": result.team_id},
            )
        }
        assert members == set(result.users.values())
        assert len(members) == len(PEOPLE)

    async def test_the_team_hangs_off_a_real_branch(self, db: Any) -> None:
        result = await provision_workspace(db, _spec(), password_hash=HASH)
        branch = (
            await db.execute(
                text("SELECT branch_id FROM app.teams WHERE id = :team"),
                {"team": result.team_id},
            )
        ).scalar_one()
        assert UUID(str(branch)) == result.branch_id

    async def test_only_the_owner_is_flagged_as_owner(self, db: Any) -> None:
        await provision_workspace(db, _spec(), password_hash=HASH)
        owners = [
            row[0]
            for row in await db.execute(
                text("SELECT email FROM app.users WHERE tenant_id = :t AND is_owner"),
                {"t": PILOT_TENANT},
            )
        ]
        assert owners == ["owner@pilot.test"]


class TestNothingCanReachPilotData:
    async def test_a_pilot_starts_with_no_demo_manifest(self, db: Any) -> None:
        """The whole safety argument in one assertion.

        A refresh deletes exactly what a manifest recorded. A pilot has no
        manifest, so there is nothing for a refresh to delete - the rows are safe
        by construction rather than by being recognised as real.
        """
        await provision_workspace(db, _spec(), password_hash=HASH)
        lead = await _lead(db, PILOT_TENANT, "Real Pilot Prospect")

        removed = await delete_recorded_rows(db, PILOT_TENANT)

        assert removed == {}
        assert await _exists(db, "leads", lead)

    async def test_a_demo_refresh_next_door_cannot_touch_the_pilot(self, db: Any) -> None:
        await provision_workspace(db, _spec(), password_hash=HASH)
        await provision_workspace(
            db,
            _spec(DEMO_TENANT, kind=TEST, slug="demo-next-door"),
            password_hash=HASH,
        )
        pilot_lead = await _lead(db, PILOT_TENANT, "Real Pilot Prospect")
        demo_lead = await _lead(db, DEMO_TENANT, "Sample")

        manifest = empty_manifest()
        manifest["leads"] = [str(demo_lead)]
        await record_manifest(db, DEMO_TENANT, manifest)

        await delete_recorded_rows(db, DEMO_TENANT)

        assert not await _exists(db, "leads", demo_lead)
        assert await _exists(db, "leads", pilot_lead)

    async def test_a_manifest_naming_a_pilot_row_still_cannot_delete_it(self, db: Any) -> None:
        """Defence in depth: the id list decides *what*, the tenant decides *where*."""
        await provision_workspace(db, _spec(), password_hash=HASH)
        await provision_workspace(
            db,
            _spec(DEMO_TENANT, kind=TEST, slug="demo-next-door"),
            password_hash=HASH,
        )
        pilot_lead = await _lead(db, PILOT_TENANT, "Real Pilot Prospect")

        # A corrupt or malicious manifest in the demo tenant naming the pilot's row.
        manifest = empty_manifest()
        manifest["leads"] = [str(pilot_lead)]
        await record_manifest(db, DEMO_TENANT, manifest)

        await delete_recorded_rows(db, DEMO_TENANT)

        assert await _exists(db, "leads", pilot_lead)

    async def test_row_level_security_is_forced_on_pilot_tables(self, db: Any) -> None:
        """Not "enabled" - forced. Enabled alone is bypassed by the table owner."""
        rows = await db.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class"
                " WHERE relname = ANY(:names)"
            ),
            {"names": ["leads", "tasks", "notes", "activities", "users"]},
        )
        for row in rows:
            assert row.relrowsecurity, row.relname
            assert row.relforcerowsecurity, row.relname


class TestProvisioningRefusesNonsense:
    async def test_an_unknown_workspace_kind_is_refused(self, db: Any) -> None:
        with pytest.raises(ValueError, match="Unknown workspace kind"):
            await provision_workspace(
                db,
                WorkspaceSpec(
                    tenant_id=PILOT_TENANT,
                    name="Nope",
                    slug="nope",
                    kind="production",
                    people=PEOPLE,
                ),
                password_hash=HASH,
            )
