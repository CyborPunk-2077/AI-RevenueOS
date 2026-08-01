"""Worker tier integration tests.

These run against a **real** PostgreSQL 16 (via `pgserver`), a **real** Redis (via
`redislite`) and a **real** in-process Celery worker consuming from that broker.
Nothing here is mocked: a task is enqueued over the wire, picked up by a worker,
and its effects are asserted in the database.
"""

from __future__ import annotations

import asyncio
import tempfile
import time
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.postgres


# --- real infrastructure fixtures ----------------------------------------


@pytest.fixture(scope="session")
def redis_socket() -> str:
    """A real Redis server. `fakeredis` cannot act as a Celery broker."""
    try:
        import redislite
    except ImportError:  # pragma: no cover
        pytest.skip("redislite unavailable; the worker suite requires a real broker")
    server = redislite.Redis(tempfile.mktemp(suffix=".rdb"))
    pytest._airev_redis = server  # type: ignore[attr-defined]
    return str(server.socket_file)


@pytest.fixture
def redis_client(redis_socket: str) -> Iterator[Any]:
    import redis.asyncio as aioredis

    from infrastructure.caching.redis import set_redis

    client = aioredis.from_url(f"unix://{redis_socket}", decode_responses=True)
    set_redis(client)
    yield client
    set_redis(None)


@pytest.fixture
def wired_engine(migrated_database: str, engine: Any) -> Iterator[Any]:
    """Point the global session factory at the migrated test database."""
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import infrastructure.database.session as session_module

    session_module._engine = engine
    session_module._sessionmaker = async_sessionmaker(
        bind=engine, expire_on_commit=False, autoflush=False
    )
    yield engine
    session_module.reset_engine()


@pytest.fixture
def celery_app(redis_socket: str, wired_engine: Any) -> Any:
    """The real application object, pointed at the real broker."""
    from infrastructure.celery.app import app

    broker = f"redis+socket://{redis_socket}"
    app.conf.update(broker_url=broker, result_backend=broker, task_always_eager=False)
    return app


@pytest.fixture
def celery_worker(celery_app: Any) -> Iterator[Any]:
    """A real Celery worker consuming every declared queue."""
    from celery.contrib.testing.worker import start_worker

    from infrastructure.celery.queues import QUEUE_SPECS

    with start_worker(
        celery_app,
        queues=[q.name for q in QUEUE_SPECS],
        perform_ping_check=False,
        shutdown_timeout=30,
    ) as worker:
        yield worker


def run_async(coro: Any) -> Any:
    """Drive a coroutine from a synchronous Celery test."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# --- probe tasks -----------------------------------------------------------
# Celery resolves a task by name at import time, so a worker started by a fixture
# only knows tasks that already exist. These probes are therefore module level.

from infrastructure.celery.context import TaskContext, build_headers  # noqa: E402
from infrastructure.celery.tasks.base import airev_task  # noqa: E402

ECHO_CALLS: list[dict[str, Any]] = []
TERMINAL_ATTEMPTS: list[int] = []
TRANSIENT_CALLS: list[int] = []


@airev_task("standard.probe_echo_context", tenant_scoped=True)
async def probe_echo_context(context: TaskContext) -> dict[str, Any]:
    return {
        "tenant_id": str(context.tenant_id),
        "correlation_id": context.correlation_id,
        "actor_type": context.actor_type,
    }


@airev_task("standard.probe_requires_tenant", tenant_scoped=True, max_attempts=1)
async def probe_requires_tenant(context: TaskContext) -> str:
    return "should not reach here"


@airev_task("maintenance.probe_platform_ok", tenant_scoped=False)
async def probe_platform_ok(context: TaskContext) -> dict[str, Any]:
    return {"tenant_id": str(context.tenant_id) if context.tenant_id else None}


@airev_task("standard.probe_count_leads", tenant_scoped=True)
async def probe_count_leads(context: TaskContext) -> int:
    from infrastructure.database.session import tenant_session

    async with tenant_session(context.require_tenant()) as session:
        return int((await session.execute(text("SELECT count(*) FROM app.leads"))).scalar_one())


@airev_task("standard.probe_terminal_failure", max_attempts=5)
async def probe_terminal_failure(context: TaskContext) -> None:
    from shared.exceptions import ValidationError

    TERMINAL_ATTEMPTS.append(1)
    raise ValidationError("this payload can never succeed")


@airev_task("standard.probe_transient_failure", max_attempts=4)
async def probe_transient_failure(context: TaskContext) -> str:
    TRANSIENT_CALLS.append(1)
    if len(TRANSIENT_CALLS) < 3:
        raise ConnectionError("provider unreachable")
    return "recovered"


# --- queue topology -------------------------------------------------------


class TestQueueTopology:
    def test_queue_table_matches_the_domain_constant(self) -> None:
        """The worker's queue table and the domain's copy must never drift."""
        from application.workflows.executor import QUEUES
        from infrastructure.celery.queues import BY_NAME

        assert set(QUEUES) == set(BY_NAME)
        for name, expected in QUEUES.items():
            spec = BY_NAME[name]
            assert spec.concurrency == expected["concurrency"], name
            assert spec.spec_priority == expected["priority"], name
            assert spec.timeout_seconds == expected["timeout"], name

    def test_all_eight_queues_are_declared_to_celery(self, celery_app: Any) -> None:
        declared = {q.name for q in celery_app.conf.task_queues}
        assert len(declared) == 8
        assert "workflow-critical" in declared
        assert "workflow-maintenance" in declared

    def test_priority_translation_inverts_for_the_broker(self) -> None:
        """Spec priority 10 is most urgent; Redis priority 0 is delivered first."""
        from infrastructure.celery.queues import BY_NAME

        assert BY_NAME["workflow-critical"].spec_priority == 10
        assert BY_NAME["workflow-critical"].broker_priority == 0
        assert BY_NAME["workflow-maintenance"].spec_priority == 1
        assert BY_NAME["workflow-maintenance"].broker_priority == 9

    def test_soft_timeout_precedes_the_hard_limit(self) -> None:
        from infrastructure.celery.queues import QUEUE_SPECS

        for spec in QUEUE_SPECS:
            assert spec.soft_timeout_seconds < spec.timeout_seconds, spec.name

    def test_tasks_route_to_their_declared_queue(self) -> None:
        from infrastructure.celery.queues import route_task

        assert route_task("critical.execute_workflow")["queue"] == "workflow-critical"
        assert route_task("maintenance.nightly_cleanup")["queue"] == "workflow-maintenance"
        assert route_task("webhook.deliver")["queue"] == "workflow-webhook"
        assert route_task("something.unknown")["queue"] == "workflow-standard"

    def test_serialisation_is_json_never_pickle(self, celery_app: Any) -> None:
        assert celery_app.conf.task_serializer == "json"
        assert celery_app.conf.accept_content == ["json"]

    def test_delivery_guarantees_match_the_specification(self, celery_app: Any) -> None:
        conf = celery_app.conf
        assert conf.task_acks_late is True
        assert conf.task_reject_on_worker_lost is True
        assert conf.worker_prefetch_multiplier == 1
        assert conf.task_time_limit == 600
        assert conf.task_soft_time_limit == 480

    def test_beat_cadences_match_the_specification(self, celery_app: Any) -> None:
        schedule = celery_app.conf.beat_schedule
        assert schedule["outbox-relay"]["schedule"] == 0.5
        assert schedule["workflow-scheduler"]["schedule"] == 10.0
        assert schedule["webhook-sweep"]["schedule"] == 60.0
        assert schedule["metrics-rollup"]["schedule"] == 900.0
        assert schedule["payment-reconciliation"]["schedule"] == 1800.0
        cleanup = schedule["maintenance-cleanup"]["schedule"]
        assert cleanup.hour == {3} and cleanup.minute == {0}

    def test_worker_pools_cover_every_queue(self) -> None:
        from infrastructure.celery.queues import BY_NAME, WORKER_POOLS

        covered = {q for queues in WORKER_POOLS.values() for q in queues}
        assert covered == set(BY_NAME), "every queue must be served by some pool"


# --- tenant context propagation ------------------------------------------


class TestTenantContextPropagation:
    def test_headers_round_trip_across_the_process_boundary(
        self, celery_app: Any, celery_worker: Any, seeded_tenants: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        correlation = f"corr-{uuid4()}"

        result = probe_echo_context.apply_async(
            headers=build_headers(tenant_id=tenant_a, correlation_id=correlation, actor_type="api")
        ).get(timeout=30)

        assert result["tenant_id"] == str(tenant_a)
        assert result["correlation_id"] == correlation
        assert result["actor_type"] == "api"

    def test_tenant_scoped_task_refuses_to_run_without_a_tenant(
        self, celery_app: Any, celery_worker: Any
    ) -> None:
        """Failing closed here is what stops a worker running with no RLS predicate."""
        with pytest.raises(Exception) as exc:
            probe_requires_tenant.apply_async(headers={}).get(timeout=30)
        assert "tenant" in str(exc.value).lower()

    def test_platform_task_may_run_without_a_tenant(
        self, celery_app: Any, celery_worker: Any
    ) -> None:
        result = probe_platform_ok.apply_async(headers={}).get(timeout=30)
        assert result["tenant_id"] is None

    def test_a_non_uuid_tenant_is_rejected_at_enqueue_time(self) -> None:
        from infrastructure.celery.context import build_headers

        with pytest.raises(ValueError):
            build_headers(tenant_id="'; DROP TABLE app.leads; --")

    def test_a_worker_sees_only_its_bound_tenants_rows(
        self, celery_app: Any, celery_worker: Any, seeded_tenants: Any, wired_engine: Any
    ) -> None:
        """The bound tenant drives RLS inside the worker exactly as in the API.

        Measured as a delta rather than an absolute count. `migrated_database` is
        session-scoped, so whether tenant B already owns rows depends on which
        suites ran first -- `tests/e2e/test_lead_lifecycle.py` legitimately creates
        one for tenant B. An earlier `assert b_count == 0` therefore passed when
        this module ran alone and failed in a full-suite run, which says nothing
        about isolation. What isolation actually means here is that tenant A's new
        row does not appear in tenant B's count.
        """
        from application.leads.service import LeadService
        from domain.auth.permissions import Role, permissions_for

        tenant_a, tenant_b = seeded_tenants

        def count_for(tenant: Any) -> int:
            """Count that tenant's leads from inside a real worker process."""
            return int(
                probe_count_leads.apply_async(headers=build_headers(tenant_id=tenant)).get(
                    timeout=30
                )
            )

        a_before = count_for(tenant_a)
        b_before = count_for(tenant_b)

        service = LeadService(
            tenant_id=tenant_a, user_id=uuid4(), permissions=permissions_for([Role.ADMIN])
        )
        run_async(service.capture({"first_name": "WorkerScoped", "email": f"{uuid4()}@example.in"}))

        assert count_for(tenant_a) == a_before + 1, "the worker must see its own tenant's new row"
        assert count_for(tenant_b) == b_before, (
            "tenant B must not observe tenant A's row from a worker"
        )


# --- retry classification and dead lettering -----------------------------


class TestRetryAndDeadLetter:
    def test_terminal_failure_is_not_retried_and_is_dead_lettered(
        self, celery_app: Any, celery_worker: Any, seeded_tenants: Any, wired_engine: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        TERMINAL_ATTEMPTS.clear()

        with pytest.raises(Exception):
            probe_terminal_failure.apply_async(headers=build_headers(tenant_id=tenant_a)).get(
                timeout=30
            )

        assert len(TERMINAL_ATTEMPTS) == 1, "a terminal failure must never be retried"

        rows = run_async(_dead_letters_for("standard.probe_terminal_failure"))
        assert rows, "an exhausted task must be durably dead-lettered"
        assert rows[0]["attempts"] == 1
        assert str(rows[0]["tenant_id"]) == str(tenant_a)
        assert "ValidationError" in rows[0]["error"]

    def test_transient_failure_is_retried_then_succeeds(
        self, celery_app: Any, celery_worker: Any, seeded_tenants: Any, wired_engine: Any
    ) -> None:
        tenant_a, _ = seeded_tenants
        TRANSIENT_CALLS.clear()

        result = probe_transient_failure.apply_async(headers=build_headers(tenant_id=tenant_a)).get(
            timeout=90
        )
        assert result == "recovered"
        assert len(TRANSIENT_CALLS) == 3

    def test_retry_classification(self) -> None:
        from domain.base import InvalidTransition
        from infrastructure.celery.reliability import classify_exception
        from infrastructure.integrations.retry import RetryClass
        from shared.exceptions import (
            Forbidden,
            ProviderUnavailable,
            RateLimited,
            ValidationError,
        )

        assert classify_exception(ValidationError("x")) is RetryClass.TERMINAL
        assert classify_exception(Forbidden("x")) is RetryClass.TERMINAL
        assert classify_exception(InvalidTransition("x")) is RetryClass.TERMINAL
        assert classify_exception(ValueError("x")) is RetryClass.TERMINAL
        assert classify_exception(ProviderUnavailable("x")) is RetryClass.PROVIDER
        assert classify_exception(ConnectionError("x")) is RetryClass.PROVIDER
        assert classify_exception(TimeoutError("x")) is RetryClass.PROVIDER
        assert classify_exception(RateLimited("x")) is RetryClass.RATE_LIMITED

    def test_rate_limit_waits_at_least_the_suggested_reset(self) -> None:
        from infrastructure.celery.reliability import retry_delay
        from shared.exceptions import RateLimited

        exc = RateLimited("slow down", details={"retry_after": 42})
        assert retry_delay(exc, attempt=1) >= 42

    async def test_dead_letter_replay_is_recorded_and_single_use(
        self, wired_engine: Any, seeded_tenants: Any, redis_client: Any, celery_app: Any
    ) -> None:
        from infrastructure.celery.reliability import (
            DeadLetterRecord,
            replay_dead_letter,
            write_dead_letter,
        )

        tenant_a, _ = seeded_tenants
        dead_letter_id = await write_dead_letter(
            DeadLetterRecord(
                queue="workflow-standard",
                task_name="maintenance.reap_dead_letters",
                payload={"args": [], "kwargs": {}},
                error="boom",
                attempts=3,
                tenant_id=tenant_a,
            )
        )

        first = await replay_dead_letter(dead_letter_id)
        second = await replay_dead_letter(dead_letter_id)
        assert first["replayed"] is True
        assert second["replayed"] is False, "a dead letter must not replay twice"

    async def test_expired_dead_letters_are_reaped(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        from datetime import timedelta

        from infrastructure.celery.reliability import (
            DeadLetterRecord,
            reap_expired_dead_letters,
            write_dead_letter,
        )
        from infrastructure.database.session import platform_session
        from shared.utils.timeutil import utcnow

        tenant_a, _ = seeded_tenants
        stale = await write_dead_letter(
            DeadLetterRecord("workflow-bulk", "t", {}, "e", 1, tenant_a)
        )
        async with platform_session("test: age a dead letter") as session:
            await session.execute(
                text("UPDATE app.dead_letters SET expires_at = :e WHERE id = :i"),
                {"e": utcnow() - timedelta(days=1), "i": stale},
            )

        assert await reap_expired_dead_letters() >= 1

    async def test_dead_letter_retention_is_fourteen_days(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        from infrastructure.celery.reliability import (
            DEAD_LETTER_RETENTION_DAYS,
            DeadLetterRecord,
            write_dead_letter,
        )
        from infrastructure.database.session import platform_session

        assert DEAD_LETTER_RETENTION_DAYS == 14
        tenant_a, _ = seeded_tenants
        dead_letter_id = await write_dead_letter(
            DeadLetterRecord("workflow-standard", "t", {}, "e", 1, tenant_a)
        )
        async with platform_session("test: read retention window") as session:
            days = (
                await session.execute(
                    text(
                        "SELECT EXTRACT(day FROM (expires_at - created_at)) "
                        "FROM app.dead_letters WHERE id = :i"
                    ),
                    {"i": dead_letter_id},
                )
            ).scalar_one()
        assert int(days) == 14


async def _dead_letters_for(task_name: str) -> list[dict[str, Any]]:
    """Reading across tenants is a platform maintenance act, so it says so."""
    from infrastructure.database.session import platform_session

    async with platform_session("test: inspect dead letters") as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT tenant_id, task_name, error, attempts, queue "
                        "FROM app.dead_letters WHERE task_name = :t "
                        "ORDER BY created_at DESC"
                    ),
                    {"t": task_name},
                )
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


# --- idempotency ----------------------------------------------------------


class TestIdempotency:
    async def test_claim_is_granted_once(self, redis_client: Any) -> None:
        from infrastructure.celery.reliability import claim_once, inbound_key

        key = inbound_key("razorpay", str(uuid4()))
        assert await claim_once(key) is True
        assert await claim_once(key) is False, "a second claim must be refused"

    async def test_distinct_providers_do_not_collide(self, redis_client: Any) -> None:
        from infrastructure.celery.reliability import claim_once, inbound_key

        assert await claim_once(inbound_key("razorpay", "evt-1")) is True
        assert await claim_once(inbound_key("whatsapp", "evt-1")) is True

    async def test_released_claim_can_be_retaken(self, redis_client: Any) -> None:
        from infrastructure.celery.reliability import (
            claim_once,
            inbound_key,
            release_claim,
        )

        key = inbound_key("razorpay", str(uuid4()))
        assert await claim_once(key) is True
        await release_claim(key)
        assert await claim_once(key) is True

    async def test_claim_fails_open_when_redis_is_unavailable(self) -> None:
        """A broker outage must not stop work; the DB constraint is the durable layer."""
        import redis.asyncio as aioredis

        from infrastructure.caching.redis import set_redis
        from infrastructure.celery.reliability import claim_once, inbound_key

        set_redis(aioredis.from_url("redis://127.0.0.1:1", socket_connect_timeout=0.05))
        try:
            assert await claim_once(inbound_key("razorpay", "x")) is True
        finally:
            set_redis(None)

    def test_key_layers_are_distinct(self) -> None:
        from infrastructure.celery.reliability import (
            action_key,
            execution_key,
            inbound_key,
        )

        wf, ver, evt = uuid4(), uuid4(), uuid4()
        assert inbound_key("p", "e").scope == "inbound:p"
        assert execution_key(wf, ver, evt).scope == "execution"
        assert action_key(evt, "n1", 2).identity.endswith(":n1:2")


# --- outbox relay through a real worker ----------------------------------


class TestOutboxRelay:
    def test_relay_task_drains_the_outbox_over_the_broker(
        self,
        celery_app: Any,
        celery_worker: Any,
        seeded_tenants: Any,
        wired_engine: Any,
        redis_client: Any,
    ) -> None:
        """End to end: commit an event, let a real worker relay it, assert it drained."""
        from domain.base import DomainEvent
        from domain.events.catalog import LEAD_CREATED
        from infrastructure.celery.tasks.scheduled import relay_outbox
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.ids import uuid7

        tenant_a, _ = seeded_tenants
        resource_id = uuid7()

        async def emit() -> None:
            async with SqlAlchemyUnitOfWork(tenant_a) as uow:
                uow.collect(
                    DomainEvent(
                        event_type=LEAD_CREATED,
                        tenant_id=tenant_a,
                        resource_type="lead",
                        resource_id=resource_id,
                        payload={"source": "worker-test"},
                    )
                )

        run_async(emit())

        result = relay_outbox.apply_async().get(timeout=60)
        assert result["claimed"] >= 1
        assert result["dispatched"] >= 1

        async def unprocessed() -> int:
            from infrastructure.database.session import unscoped_session

            async with unscoped_session() as session:
                return int(
                    (
                        await session.execute(
                            text(
                                "SELECT count(*) FROM audit.event_outbox "
                                "WHERE resource_id = :r AND processed_at IS NULL"
                            ),
                            {"r": resource_id},
                        )
                    ).scalar_one()
                )

        assert run_async(unprocessed()) == 0

    def test_relay_is_idempotent_across_cycles(
        self, celery_app: Any, celery_worker: Any, wired_engine: Any, redis_client: Any
    ) -> None:
        from infrastructure.celery.tasks.scheduled import relay_outbox

        relay_outbox.apply_async().get(timeout=60)
        second = relay_outbox.apply_async().get(timeout=60)
        assert second["claimed"] == 0, "a processed row is never claimed again"


# --- maintenance ----------------------------------------------------------


class TestMaintenance:
    async def test_partition_creation_is_idempotent_and_protects_new_children(
        self, wired_engine: Any
    ) -> None:
        from infrastructure.celery.tasks.maintenance import ensure_future_partitions
        from infrastructure.database.session import unscoped_session

        await ensure_future_partitions()
        await ensure_future_partitions()  # must not raise

        async with unscoped_session() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT c.relname, c.relrowsecurity FROM pg_inherits i "
                        "JOIN pg_class c ON c.oid = i.inhrelid "
                        "JOIN pg_class p ON p.oid = i.inhparent "
                        "WHERE p.relname = 'messages'"
                    )
                )
            ).all()
        assert rows
        unprotected = [name for name, secured in rows if not secured]
        assert not unprotected, f"new partitions must enable RLS: {unprotected}"

    async def test_processed_outbox_rows_are_pruned_after_seven_days(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        from datetime import timedelta

        from domain.base import DomainEvent
        from domain.events.catalog import LEAD_UPDATED
        from infrastructure.celery.tasks.maintenance import prune_processed_outbox
        from infrastructure.database.session import unscoped_session
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.ids import uuid7
        from shared.utils.timeutil import utcnow

        tenant_a, _ = seeded_tenants
        async with SqlAlchemyUnitOfWork(tenant_a) as uow:
            uow.collect(
                DomainEvent(
                    event_type=LEAD_UPDATED,
                    tenant_id=tenant_a,
                    resource_type="lead",
                    resource_id=uuid7(),
                    occurred_at=utcnow() - timedelta(days=10),
                )
            )
        async with unscoped_session() as session:
            await session.execute(
                text("UPDATE audit.event_outbox SET processed_at = now() WHERE occurred_at < :c"),
                {"c": utcnow() - timedelta(days=7)},
            )

        assert await prune_processed_outbox() >= 1

    async def test_expired_idempotency_records_are_pruned(
        self, wired_engine: Any, seeded_tenants: Any
    ) -> None:
        from datetime import timedelta

        from infrastructure.celery.tasks.maintenance import prune_expired_idempotency
        from infrastructure.database.session import unscoped_session
        from shared.utils.ids import uuid7
        from shared.utils.timeutil import utcnow

        tenant_a, _ = seeded_tenants
        async with unscoped_session() as session:
            await session.execute(
                text(
                    "INSERT INTO audit.idempotency_records "
                    "(id, tenant_id, scope, idempotency_key, request_hash, state, "
                    " response_body, response_status, created_at, expires_at) "
                    "VALUES (:i, :t, 'test', :k, 'h', 'completed', '{}', 200, now(), :e)"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_a,
                    "k": str(uuid4()),
                    "e": utcnow() - timedelta(hours=1),
                },
            )

        assert await prune_expired_idempotency() >= 1


# --- health ---------------------------------------------------------------


class TestWorkerHealth:
    async def test_health_reports_ready_when_broker_and_database_are_up(
        self, wired_engine: Any, redis_client: Any
    ) -> None:
        from infrastructure.celery.health import check_worker

        health = await check_worker("general")
        assert health.broker_ok is True
        assert health.database_ok is True
        assert health.ready is True
        assert health.to_dict()["status"] == "ready"
        assert "workflow-standard" in health.to_dict()["queues"]

    async def test_health_is_alive_but_not_ready_when_the_database_is_down(
        self, redis_client: Any
    ) -> None:
        import infrastructure.database.session as session_module
        from infrastructure.celery.health import check_worker

        saved = session_module._engine
        from sqlalchemy.ext.asyncio import create_async_engine

        session_module._engine = create_async_engine(
            "postgresql+asyncpg://nobody@127.0.0.1:1/nothing"
        )
        try:
            health = await check_worker("comms")
            assert health.broker_ok is True
            assert health.database_ok is False
            assert health.alive is True
            assert health.ready is False
        finally:
            session_module._engine = saved

    def test_stale_heartbeat_detection(self) -> None:
        from infrastructure.celery.health import heartbeat_is_stale

        now = time.time()
        assert heartbeat_is_stale(now - 120, now=now) is True
        assert heartbeat_is_stale(now - 5, now=now) is False
