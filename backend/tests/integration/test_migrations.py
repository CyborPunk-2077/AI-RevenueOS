"""Migration, partition, trigger and append-only guarantees."""

from __future__ import annotations

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.postgres


async def test_all_schemas_exist(session_factory) -> None:
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT nspname FROM pg_namespace WHERE nspname IN "
                        "('public','app','audit','analytics')"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert set(rows) == {"public", "app", "audit", "analytics"}


async def test_pgvector_extension_is_installed(session_factory) -> None:
    async with session_factory() as session:
        found = (
            await session.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            )
        ).scalar_one()
    assert found == 1


@pytest.mark.parametrize(
    ("schema", "table"),
    [("audit", "audit_logs"), ("audit", "event_outbox"), ("app", "messages")],
)
async def test_tables_are_partitioned_with_children(session_factory, schema, table) -> None:
    async with session_factory() as session:
        strategy = (
            await session.execute(
                text(
                    "SELECT p.partstrat FROM pg_partitioned_table p "
                    "JOIN pg_class c ON c.oid = p.partrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relname = :t"
                ),
                {"s": schema, "t": table},
            )
        ).scalar_one()
        children = (
            await session.execute(
                text(
                    "SELECT count(*) FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhparent "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :s AND c.relname = :t"
                ),
                {"s": schema, "t": table},
            )
        ).scalar_one()
    assert (strategy.decode() if isinstance(strategy, bytes) else strategy) == "r"
    assert children >= 2


async def test_updated_at_trigger_fires(session_factory, seeded_tenants) -> None:
    tenant_a, _ = seeded_tenants
    from shared.utils.ids import uuid7

    cid = uuid7()
    async with session_factory() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
            )
            await session.execute(
                text(
                    "INSERT INTO app.tags (id, tenant_id, name, created_at, updated_at)"
                    " VALUES (:id, :t, 'vip', now() - interval '1 day', now() - interval '1 day')"
                ),
                {"id": cid, "t": tenant_a},
            )
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
            )
            await session.execute(
                text("UPDATE app.tags SET color = '#fff' WHERE id = :id"), {"id": cid}
            )
            fresh = (
                await session.execute(
                    text("SELECT updated_at > created_at FROM app.tags WHERE id = :id"), {"id": cid}
                )
            ).scalar_one()
    assert fresh is True


async def test_append_only_tables_reject_update_and_delete(session_factory, seeded_tenants) -> None:
    tenant_a, _ = seeded_tenants
    from shared.utils.ids import uuid7

    aid = uuid7()
    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
        )
        await session.execute(
            text(
                "INSERT INTO app.activities (id, tenant_id, activity_type, subject,"
                " entity_type, entity_id, actor_type, metadata_json, created_at, updated_at)"
                " VALUES (:id, :t, 'system', 'created', 'contact', :e, 'system', '{}',"
                " now(), now())"
            ),
            {"id": aid, "t": tenant_a, "e": uuid7()},
        )
    for stmt in (
        "UPDATE app.activities SET subject = 'tampered' WHERE id = :id",
        "DELETE FROM app.activities WHERE id = :id",
    ):
        async with session_factory() as session:
            with pytest.raises(Exception) as exc:
                async with session.begin():
                    await session.execute(
                        text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
                    )
                    await session.execute(text(stmt), {"id": aid})
            assert "append-only" in str(exc.value)


async def test_payment_amount_and_currency_constraints(session_factory, seeded_tenants) -> None:
    tenant_a, _ = seeded_tenants
    from shared.utils.ids import uuid7

    async with session_factory() as session:
        with pytest.raises(Exception) as exc:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
                )
                await session.execute(
                    text(
                        "INSERT INTO app.payments (id, tenant_id, amount_minor, currency, status,"
                        " method, provider, provider_payload, reconciliation_status,"
                        " created_at, updated_at)"
                        " VALUES (:id, :t, -100, 'INR', 'created', 'upi', 'razorpay', '{}',"
                        " 'pending', now(), now())"
                    ),
                    {"id": uuid7(), "t": tenant_a},
                )
    assert "amount_positive" in str(exc.value)
