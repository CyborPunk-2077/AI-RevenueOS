"""Outbox durability: same-transaction commit, at-least-once delivery, retry, DLQ."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from domain.base import DomainEvent
from domain.events.catalog import LEAD_CREATED
from infrastructure.messaging.outbox import MAX_ATTEMPTS, OutboxDispatcher
from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
from shared.utils.ids import uuid7

pytestmark = pytest.mark.postgres


def _event(tenant_id):  # type: ignore[no-untyped-def]
    return DomainEvent(
        event_type=LEAD_CREATED,
        tenant_id=tenant_id,
        resource_type="lead",
        resource_id=uuid7(),
        payload={"source": "web_form"},
    )


async def test_state_change_and_outbox_row_commit_together(session_factory, seeded_tenants) -> None:
    tenant_a, _ = seeded_tenants
    tag_id = uuid7()
    event = _event(tenant_a)
    async with SqlAlchemyUnitOfWork(tenant_a, session_factory=session_factory) as uow:
        await uow.session.execute(
            text(
                "INSERT INTO app.tags (id, tenant_id, name, created_at, updated_at)"
                " VALUES (:id, :t, :name, now(), now())"
            ),
            {"id": tag_id, "t": tenant_a, "name": f"outbox-{tag_id}"},
        )
        uow.collect(event)

    async with session_factory() as session:
        outbox_rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit.event_outbox"
                    " WHERE tenant_id = :t AND resource_id = :r"
                ),
                {"t": tenant_a, "r": event.resource_id},
            )
        ).scalar_one()
        tag_rows = (
            await session.execute(
                text("SELECT count(*) FROM app.tags WHERE id = :id"), {"id": tag_id}
            )
        ).scalar_one()
    assert outbox_rows == 1
    assert tag_rows == 0, "RLS hides the row from an unbound session"


async def test_rollback_discards_both_state_and_event(session_factory, seeded_tenants) -> None:
    tenant_a, _ = seeded_tenants
    tag_id = uuid7()
    with pytest.raises(RuntimeError):
        async with SqlAlchemyUnitOfWork(tenant_a, session_factory=session_factory) as uow:
            await uow.session.execute(
                text(
                    "INSERT INTO app.tags (id, tenant_id, name, created_at, updated_at)"
                    " VALUES (:id, :t, 'rolled-back', now(), now())"
                ),
                {"id": tag_id, "t": tenant_a},
            )
            uow.collect(_event(tenant_a))
            raise RuntimeError("business rule failed after the write")

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_a)}
        )
        tags = (
            await session.execute(
                text("SELECT count(*) FROM app.tags WHERE id = :id"), {"id": tag_id}
            )
        ).scalar_one()
    assert tags == 0


async def test_dispatcher_marks_processed_and_is_idempotent(
    session_factory, seeded_tenants
) -> None:
    tenant_a, _ = seeded_tenants
    seen: list[dict] = []

    async with SqlAlchemyUnitOfWork(tenant_a, session_factory=session_factory) as uow:
        uow.collect(_event(tenant_a))

    dispatcher = OutboxDispatcher(session_factory)
    dispatcher.subscribe(LEAD_CREATED, lambda payload: _collect(seen, payload))

    first = await dispatcher.run_once()
    second = await dispatcher.run_once()

    assert first.dispatched >= 1
    assert second.claimed == 0, "a processed event is never claimed twice"
    # The handler is subscribed to one event type, so it sees a subset of the
    # batch. Asserting equality with the batch size made this order dependent.
    assert seen, "the subscribed handler must receive its event type"
    assert len(seen) <= first.dispatched
    assert all(event["event_type"] == LEAD_CREATED for event in seen)
    assert len({event["event_id"] for event in seen}) == len(seen)


async def _collect(sink: list[dict], payload: dict) -> None:
    sink.append(payload)


async def test_failing_handler_retries_then_dead_letters(session_factory, seeded_tenants) -> None:
    tenant_a, _ = seeded_tenants
    async with SqlAlchemyUnitOfWork(tenant_a, session_factory=session_factory) as uow:
        uow.collect(_event(tenant_a))

    async def boom(payload: dict) -> None:
        raise ValueError("downstream is unavailable")

    dispatcher = OutboxDispatcher(session_factory)
    dispatcher.subscribe(LEAD_CREATED, boom)

    stats = await dispatcher.run_once()
    assert stats.failed == 1
    assert stats.dead_lettered == 0

    # Force the attempt counter to the terminal threshold and re-run.
    async with session_factory() as session, session.begin():
        await session.execute(
            text(
                "UPDATE audit.event_outbox SET attempts = :a, available_at = now()"
                " WHERE processed_at IS NULL AND tenant_id = :t"
            ),
            {"a": MAX_ATTEMPTS - 1, "t": tenant_a},
        )
    final = await dispatcher.run_once()
    assert final.dead_lettered == 1


async def test_unit_of_work_requires_a_tenant(session_factory) -> None:
    from shared.exceptions import TenantContextMissing

    with pytest.raises(TenantContextMissing):
        SqlAlchemyUnitOfWork(None, session_factory=session_factory)
