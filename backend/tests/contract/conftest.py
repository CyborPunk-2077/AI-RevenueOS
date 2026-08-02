"""API-level fixtures: a real app, a real signing key, fake Redis, no network."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from api.app.settings import Settings
from domain.auth.permissions import Role, permissions_for, widest_scope
from infrastructure.auth.tokens import AccessClaims, TokenService, generate_keypair

TENANT_ID = uuid4()
OTHER_TENANT_ID = uuid4()
USER_ID = uuid4()
PRIVATE_KEY, PUBLIC_KEY = generate_keypair()


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(
        environment="local",
        jwt_private_key=PRIVATE_KEY,
        jwt_public_key=PUBLIC_KEY,
        jwt_issuer="https://api.test",
        cors_allowed_origins=["http://localhost:3000"],
        trusted_hosts=["testserver", "localhost"],
        redis_url="redis://localhost:6379/15",
        log_json=False,
    )


@pytest.fixture(autouse=True)
def fake_redis() -> Iterator[None]:
    import fakeredis.aioredis

    from infrastructure.caching.redis import set_redis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis(client)
    yield
    set_redis(None)


@pytest.fixture(scope="session")
def token_service(settings: Settings) -> TokenService:
    return TokenService(private_key=PRIVATE_KEY, public_key=PUBLIC_KEY, issuer=settings.jwt_issuer)


@pytest.fixture(scope="session")
def app(settings: Settings) -> Any:
    from api.app.factory import create_app

    built = create_app(settings)

    async def ignore_denial(*_: object) -> None:
        return None

    built.state.authorization_denial_auditor = ignore_denial
    return built


@pytest.fixture
def client(app: Any) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def make_token(
    token_service: TokenService,
    *,
    role: Role = Role.ADMIN,
    tenant_id: Any = TENANT_ID,
    user_id: Any = USER_ID,
    mfa: bool = True,
    permissions: list[str] | None = None,
) -> str:
    import time

    claims = AccessClaims(
        sub=str(user_id),
        tenant_id=str(tenant_id),
        tenant_slug="acme",
        email="asha@example.in",
        name="Asha",
        roles=[role.value],
        permissions=permissions if permissions is not None else sorted(permissions_for([role])),
        scope=widest_scope([role]).value,
        session_id="sess-1",
        mfa_verified=mfa,
        authenticated_at=int(time.time()),
    )
    token, _ = token_service.issue_access_token(claims)
    return token


@pytest.fixture
def auth_headers(token_service: TokenService) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(token_service)}"}


@pytest.fixture
def viewer_headers(token_service: TokenService) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(token_service, role=Role.VIEWER)}"}


@pytest.fixture
def member_headers(token_service: TokenService) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(token_service, role=Role.MEMBER)}"}


@pytest.fixture
def owner_headers(token_service: TokenService) -> dict[str, str]:
    return {"Authorization": f"Bearer {make_token(token_service, role=Role.OWNER)}"}
