"""Every tenant-owned table must prove an allow path and a deny path under RLS."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.postgres


async def _bind(session: AsyncSession, tenant_id: UUID) -> None:
    await session.execute(
        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)}
    )


# Tables that are deliberately NOT tenant-scoped. Every entry needs a reason: this
# allowlist is the only way a table can legitimately lack row level security.
PLATFORM_SCOPED: dict[str, str] = {
    "app.tenants": "the tenant registry itself; access is gated by membership resolution",
    "app.prompts": "platform-owned prompt registry, identical for every tenant",
    "app.ai_evaluation_sets": "platform-owned gold sets",
    "app.ai_evaluation_runs": "platform-owned evaluation results",
    "app.feature_overrides": "platform/environment/cohort overrides, audited separately",
    "audit.event_outbox": "the poller must observe every tenant; unreachable from a tenant API",
    "audit.idempotency_records": "the reaper must observe every tenant",
}


async def test_every_table_carrying_a_tenant_id_enforces_rls(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Asserted against the live database, including partition children.

    PostgreSQL does not propagate row level security to partitions, so a parent
    policy alone leaves `app.messages_p202608` readable directly. Both the parent
    and every child must be enabled and forced.
    """
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT n.nspname || '.' || c.relname, c.relrowsecurity, "
                    "       c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname IN ('app','audit','analytics') "
                    "  AND c.relkind IN ('r','p')"
                )
            )
        ).all()

    unprotected = {name for name, enabled, forced in rows if not (enabled and forced)}
    # Children of a platform-scoped parent inherit that classification.
    platform_prefixes = tuple(f"{name}_" for name in PLATFORM_SCOPED)
    unexpected = sorted(
        name
        for name in unprotected - set(PLATFORM_SCOPED)
        if not name.startswith(platform_prefixes)
    )
    assert not unexpected, (
        "these tables have no enforced row level security and are not on the "
        f"documented platform-scoped allowlist: {unexpected}"
    )


async def test_partition_children_are_individually_protected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A direct read of a partition must not bypass the parent's policy."""
    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT n.nspname || '.' || c.relname, c.relrowsecurity "
                    "FROM pg_inherits i "
                    "JOIN pg_class c ON c.oid = i.inhrelid "
                    "JOIN pg_class p ON p.oid = i.inhparent "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE p.relname IN ('messages','audit_logs')"
                )
            )
        ).all()
    assert rows, "expected partition children to exist"
    assert all(enabled for _, enabled in rows), (
        f"unprotected partitions: {[n for n, e in rows if not e]}"
    )


async def test_rls_is_enabled_and_forced_on_every_registered_tenant_table(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from infrastructure.database.base import TENANT_OWNED_TABLES

    async with session_factory() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname IN ('app','audit','analytics') AND c.relkind IN ('r','p')"
                )
            )
        ).all()
    state = {r[0]: (r[1], r[2]) for r in rows}

    # Every registered table must actually exist; a typo previously made this
    # assertion vacuous because absent tables were silently skipped.
    absent = sorted(t for t in TENANT_OWNED_TABLES if t not in state)
    assert not absent, f"registered for RLS but not present in the database: {absent}"

    missing = sorted(t for t in TENANT_OWNED_TABLES if not all(state[t]))
    assert not missing, f"RLS not enabled/forced on: {missing}"
    assert len(TENANT_OWNED_TABLES) >= 90


async def test_contact_allow_and_deny_path(
    session_factory: async_sessionmaker[AsyncSession], seeded_tenants: tuple[UUID, UUID]
) -> None:
    tenant_a, tenant_b = seeded_tenants
    from shared.utils.ids import uuid7

    contact_id = uuid7()
    async with session_factory() as session, session.begin():
        await _bind(session, tenant_a)
        await session.execute(
            text(
                "INSERT INTO app.contacts (id, tenant_id, first_name, email, address,"
                " custom_fields, tags, version, status, created_at, updated_at)"
                " VALUES (:id, :t, 'Asha', 'asha@example.in', '{}', '{}', '[]', 1,"
                " 'active', now(), now())"
            ),
            {"id": contact_id, "t": tenant_a},
        )

    # Allow: same tenant sees the row.
    async with session_factory() as session, session.begin():
        await _bind(session, tenant_a)
        found = (
            await session.execute(
                text("SELECT count(*) FROM app.contacts WHERE id = :id"), {"id": contact_id}
            )
        ).scalar_one()
    assert found == 1

    # Deny: another tenant cannot see it.
    async with session_factory() as session, session.begin():
        await _bind(session, tenant_b)
        found_b = (
            await session.execute(
                text("SELECT count(*) FROM app.contacts WHERE id = :id"), {"id": contact_id}
            )
        ).scalar_one()
    assert found_b == 0

    # Deny: no bound tenant sees nothing at all.
    async with session_factory() as session, session.begin():
        found_none = (await session.execute(text("SELECT count(*) FROM app.contacts"))).scalar_one()
    assert found_none == 0


async def test_cross_tenant_write_is_rejected(
    session_factory: async_sessionmaker[AsyncSession], seeded_tenants: tuple[UUID, UUID]
) -> None:
    tenant_a, tenant_b = seeded_tenants
    from shared.utils.ids import uuid7

    async with session_factory() as session:
        with pytest.raises(Exception) as exc:
            async with session.begin():
                await _bind(session, tenant_a)
                await session.execute(
                    text(
                        "INSERT INTO app.contacts (id, tenant_id, first_name, email, address,"
                        " custom_fields, tags, version, status, created_at, updated_at)"
                        " VALUES (:id, :t, 'Mallory', 'm@example.in', '{}', '{}', '[]', 1,"
                        " 'active', now(), now())"
                    ),
                    {"id": uuid7(), "t": tenant_b},
                )
    assert "row-level security" in str(exc.value).lower()


async def test_update_cannot_move_a_row_across_tenants(
    session_factory: async_sessionmaker[AsyncSession], seeded_tenants: tuple[UUID, UUID]
) -> None:
    tenant_a, tenant_b = seeded_tenants
    from shared.utils.ids import uuid7

    contact_id = uuid7()
    async with session_factory() as session, session.begin():
        await _bind(session, tenant_a)
        await session.execute(
            text(
                "INSERT INTO app.contacts (id, tenant_id, first_name, phone, address,"
                " custom_fields, tags, version, status, created_at, updated_at)"
                " VALUES (:id, :t, 'Ravi', '+919876543210', '{}', '{}', '[]', 1,"
                " 'active', now(), now())"
            ),
            {"id": contact_id, "t": tenant_a},
        )
    async with session_factory() as session:
        with pytest.raises(Exception) as exc:
            async with session.begin():
                await _bind(session, tenant_a)
                await session.execute(
                    text("UPDATE app.contacts SET tenant_id = :b WHERE id = :id"),
                    {"b": tenant_b, "id": contact_id},
                )
    assert "row-level security" in str(exc.value).lower()
