"""Test fixtures. Integration tests run against a real PostgreSQL 16 instance."""

from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from shared.utils.ids import uuid7

APP_DB_ROLE = "airev_app_runtime"

#: Provider credentials and gates that must never reach a test process.
#:
#: `Settings` reads the environment, and the API container now carries real Meta
#: WhatsApp credentials so the founder can run a live test. Those leaked into the
#: suite and inverted every assertion about a *gated* channel: tests that check
#: "no credential, so this reports itself unavailable" started failing because a
#: credential genuinely existed. A test whose result depends on whose machine it
#: runs on is not a test.
#:
#: Cleared globally rather than patched per call site, so a suite written next
#: month inherits the isolation without having to know about it. Tests that need
#: a *configured* provider inject their own values explicitly - see
#: `tests/integration/test_whatsapp_provider_contract.py`, which constructs every
#: adapter by hand.
_PROVIDER_ENV = (
    "WHATSAPP_PHONE_NUMBER_ID",
    "WHATSAPP_ACCESS_TOKEN",
    "WHATSAPP_APP_SECRET",
    "WHATSAPP_VERIFY_TOKEN",
    "EMAIL_PROVIDER",
    "EMAIL_API_KEY",
    "EMAIL_FROM_ADDRESS",
    "VOICE_PROVIDER",
    "FEATURE_WHATSAPP_ENABLED",
    "FEATURE_EMAIL_ENABLED",
    "FEATURE_SMS_ENABLED",
    "FEATURE_VOICE_ENABLED",
    "FEATURE_PAYMENTS_ENABLED",
)


@pytest.fixture(scope="session", autouse=True)
def _no_real_provider_credentials() -> Iterator[None]:
    """Run every suite as though no provider had ever been configured."""
    removed = {name: os.environ.pop(name, None) for name in _PROVIDER_ENV}

    from shared.settings import get_settings

    get_settings.cache_clear()
    yield
    for name, value in removed.items():
        if value is not None:
            os.environ[name] = value
    get_settings.cache_clear()


TENANT_A = UUID("01890000-0000-7000-8000-00000000000a")
TENANT_B = UUID("01890000-0000-7000-8000-00000000000b")


def _bootstrap_postgres() -> str | None:
    """Start an ephemeral PostgreSQL 16 (with pgvector) for the session, if available."""
    url = os.environ.get("TEST_DATABASE_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:  # pragma: no cover - environment without pgserver
        return None
    data_dir = Path(tempfile.mkdtemp(prefix="airev-pg-"))
    server = pgserver.get_server(str(data_dir))
    server.psql("CREATE DATABASE airevenueos_test;")
    socket_dir = str(data_dir)
    pytest.pg_server = server  # type: ignore[attr-defined]
    admin = f"postgresql+psycopg://postgres@/airevenueos_test?host={socket_dir}"
    os.environ["ADMIN_DATABASE_URL"] = admin
    os.environ["ALEMBIC_DATABASE_URL"] = admin
    os.environ["PG_SOCKET_DIR"] = socket_dir
    return f"postgresql+asyncpg://{APP_DB_ROLE}@/airevenueos_test?host={socket_dir}"


@pytest.fixture(scope="session")
def database_url() -> str:
    url = _bootstrap_postgres()
    if not url:
        pytest.skip("PostgreSQL is unavailable; integration tests require it")
    os.environ["DATABASE_URL"] = url
    os.environ.setdefault("ALEMBIC_DATABASE_URL", url.replace("+asyncpg", "+psycopg"))
    return url


@pytest.fixture(scope="session")
def migrated_database(database_url: str) -> str:
    """Run the full Alembic upgrade exactly once per test session."""
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))

    admin_url = os.environ.get("ADMIN_DATABASE_URL")
    if admin_url:
        from sqlalchemy import create_engine

        # The runtime role is deliberately NOT the owner and does NOT have BYPASSRLS;
        # either would silently defeat FORCE ROW LEVEL SECURITY.
        admin = create_engine(admin_url, future=True, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text("CREATE ROLE airevenueos_app NOLOGIN NOBYPASSRLS"))
            conn.execute(
                text(f"CREATE ROLE {APP_DB_ROLE} LOGIN NOBYPASSRLS IN ROLE airevenueos_app")
            )
        admin.dispose()

    command.upgrade(cfg, "head")
    return database_url


@pytest_asyncio.fixture
async def engine(migrated_database: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(migrated_database, poolclass=NullPool, future=True)
    try:
        yield eng
    finally:
        await eng.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@pytest_asyncio.fixture
async def db(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def seeded_tenants(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[tuple[UUID, UUID]]:
    async with session_factory() as session, session.begin():
        for tid, slug in ((TENANT_A, "tenant-a"), (TENANT_B, "tenant-b")):
            await session.execute(
                text(
                    "INSERT INTO app.tenants (id, name, slug, plan_code, status, timezone,"
                    " currency, locale, settings, branding, business_hours, holidays,"
                    " billing_address, onboarding_state, version, created_at, updated_at)"
                    " VALUES (:id, :name, :slug, 'starter', 'active', 'Asia/Kolkata', 'INR',"
                    " 'en-IN', '{}', '{}', '{}', '[]', '{}', '{}', 1, now(), now())"
                    " ON CONFLICT (id) DO NOTHING"
                ),
                {"id": tid, "name": slug, "slug": slug},
            )
    yield TENANT_A, TENANT_B


@pytest.fixture
def new_id() -> Callable[..., UUID]:
    return uuid7
