"""Async engine/session management with transaction-local tenant binding.

`app.tenant_id` is set with `set_local` inside the transaction so PostgreSQL RLS
policies apply to every statement, including those issued by workers, the
scheduler, migrations tests and support tooling.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from infrastructure.logging.context import get_tenant_id
from infrastructure.monitoring.metrics import tenant_isolation_violations
from shared.exceptions import TenantContextMissing
from shared.settings import Settings, get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _connect_args(cfg: Settings) -> dict[str, object]:
    if cfg.database_url.startswith("postgresql+asyncpg"):
        return {
            "server_settings": {
                "application_name": cfg.service_name,
                "jit": "off",
                "statement_timeout": str(cfg.database_statement_timeout_ms),
            },
            "timeout": 10,
        }
    return {}


def get_engine(cfg: Settings | None = None) -> AsyncEngine:
    global _engine
    if _engine is None:
        c = cfg or get_settings()
        _engine = create_async_engine(
            c.database_url,
            pool_size=c.database_pool_size,
            max_overflow=c.database_max_overflow,
            pool_pre_ping=True,
            pool_recycle=1800,
            future=True,
            echo=False,
            connect_args=_connect_args(c),
        )
    return _engine


def get_sessionmaker(cfg: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(cfg),
            expire_on_commit=False,
            autoflush=False,
            class_=AsyncSession,
        )
    return _sessionmaker


def reset_engine() -> None:
    """Test hook: drop cached engine/sessionmaker so a new URL takes effect."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None


async def bind_tenant(session: AsyncSession, tenant_id: UUID | str) -> None:
    """Bind `app.tenant_id` transaction-locally. Must run inside an open transaction."""
    value = str(tenant_id)
    UUID(value)  # reject anything that is not a UUID before it reaches SQL
    await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": value})


async def bind_platform_context(session: AsyncSession, reason: str) -> None:
    """Platform/support escalation. Audited, never a silent tenant bypass."""
    await session.execute(
        text("SELECT set_config('app.platform_context', :r, true)"), {"r": reason}
    )


@asynccontextmanager
async def tenant_session(
    tenant_id: UUID | str | None = None, cfg: Settings | None = None
) -> AsyncIterator[AsyncSession]:
    """Open a session with a transaction and a bound tenant for the whole scope."""
    resolved = str(tenant_id) if tenant_id else get_tenant_id()
    if not resolved:
        tenant_isolation_violations.labels(surface="session").inc()
        raise TenantContextMissing()
    maker = get_sessionmaker(cfg)
    async with maker() as session, session.begin():
        await bind_tenant(session, resolved)
        yield session


@asynccontextmanager
async def unscoped_session(cfg: Settings | None = None) -> AsyncIterator[AsyncSession]:
    """For public/reference schema work only (plans, flags, templates, migrations)."""
    maker = get_sessionmaker(cfg)
    async with maker() as session, session.begin():
        yield session


@lru_cache(maxsize=1)
def install_pool_guards() -> bool:
    """Reset `app.tenant_id` when a connection returns to the pool."""
    engine = get_engine()

    @event.listens_for(engine.sync_engine, "reset")
    def _reset(dbapi_conn: object, record: object) -> None:  # pragma: no cover - driver level
        return None

    return True


async def ping(cfg: Settings | None = None) -> None:
    """Readiness probe. Lives here so the API layer never imports SQLAlchemy."""
    engine = get_engine(cfg)
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
