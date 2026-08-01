"""E2E fixtures: real PostgreSQL, real repositories, real outbox, fake Redis."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest


@pytest.fixture(autouse=True)
def fake_redis() -> Iterator[None]:
    import fakeredis.aioredis

    from infrastructure.caching.redis import set_redis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis(client)
    yield
    set_redis(None)


@pytest.fixture
def wired_engine(migrated_database: str, engine: Any) -> Any:
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
def principal_factory(seeded_tenants: tuple[Any, Any]) -> Any:
    from domain.auth.permissions import Role, permissions_for, widest_scope

    tenant_a, tenant_b = seeded_tenants

    def build(tenant_id: Any = None, role: Role = Role.ADMIN) -> Any:
        from api.deps.principal import Principal

        return Principal(
            user_id=uuid4(),
            tenant_id=tenant_id or tenant_a,
            tenant_slug="tenant-a",
            email="asha@example.in",
            name="Asha",
            roles=(role.value,),
            permissions=permissions_for([role]),
            scope=widest_scope([role]),
            mfa_verified=True,
        )

    build.tenant_a = tenant_a  # type: ignore[attr-defined]
    build.tenant_b = tenant_b  # type: ignore[attr-defined]
    return build
