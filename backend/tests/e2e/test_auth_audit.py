"""Auth session mutations and their mandatory audit trail on real PostgreSQL."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.postgres


async def test_login_refresh_reuse_and_logout_commit_compact_audit_rows(
    wired_engine, seeded_tenants, session_factory
) -> None:
    from application.auth.service import login, logout, refresh
    from infrastructure.auth.passwords import hash_password
    from infrastructure.auth.tokens import TokenService, generate_keypair
    from infrastructure.database.models.users import User
    from shared.exceptions import Unauthenticated
    from shared.utils.ids import uuid7
    from shared.utils.timeutil import utcnow

    tenant_id, _ = seeded_tenants
    user_id = uuid7()
    email = f"auth-audit-{uuid4()}@example.in"
    password = "auth-audit-passphrase-2026"

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                full_name="Audit User",
                password_hash=hash_password(password),
                status="active",
                email_verified_at=utcnow(),
                is_owner=True,
                version=1,
            )
        )

    private_key, public_key = generate_keypair()
    tokens = TokenService(
        private_key=private_key,
        public_key=public_key,
        issuer="https://auth-audit.test",
    )

    with pytest.raises(Unauthenticated):
        await login(email, "wrong-password-here", tokens)

    first = await login(email, password, tokens)
    rotated = await refresh(first.refresh_token, tokens)
    with pytest.raises(Unauthenticated):
        await refresh(first.refresh_token, tokens)

    second = await login(email, password, tokens)
    await logout(second.refresh_token)

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT action, outcome, old_values, new_values, metadata_json "
                    "FROM audit.audit_logs "
                    "WHERE resource_id = :uid OR actor_id = :uid ORDER BY created_at"
                ),
                {"uid": user_id},
            )
        ).all()

    assert [row.action for row in rows] == [
        "auth.login_failed",
        "auth.login",
        "auth.refresh",
        "auth.refresh_reuse",
        "auth.login",
        "auth.logout",
    ]
    assert rows[0].outcome == "failure"
    assert rows[3].outcome == "blocked"
    assert rotated.refresh_token != first.refresh_token

    serialized = str(rows).lower()
    assert password not in serialized
    assert first.refresh_token not in serialized
    assert rotated.refresh_token not in serialized
    assert "token_hash" not in serialized


async def test_explicit_bulk_and_session_cap_revocations_are_audited(
    wired_engine, seeded_tenants, session_factory
) -> None:
    from application.auth.service import issue_session
    from application.auth.sessions import revoke_all, revoke_session
    from domain.auth.permissions import Role
    from infrastructure.auth.tokens import MAX_SESSIONS_PER_USER, TokenService, generate_keypair
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.database.models.users import User
    from shared.utils.ids import uuid7
    from shared.utils.timeutil import utcnow

    tenant_id, _ = seeded_tenants
    user_id = uuid7()
    email = f"session-audit-{uuid4()}@example.in"

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=email,
                full_name="Session Audit User",
                status="active",
                email_verified_at=utcnow(),
                is_owner=True,
                version=1,
            )
        )

    private_key, public_key = generate_keypair()
    tokens = TokenService(
        private_key=private_key,
        public_key=public_key,
        issuer="https://session-audit.test",
    )

    async def open_session():
        return await issue_session(
            user_id=user_id,
            tenant=tenant,
            roles=[Role.OWNER],
            email=email,
            name="Session Audit User",
            tokens=tokens,
        )

    first = await open_session()
    first_family = tokens.decode_access_token(first.access_token)["sid"]
    await revoke_session(tenant_id=tenant_id, user_id=user_id, family_id=first_family)

    await open_session()
    await open_session()
    bulk = await revoke_all(tenant_id=tenant_id, user_id=user_id)
    assert bulk["sessions_revoked"] == 2

    for _ in range(MAX_SESSIONS_PER_USER + 1):
        await open_session()

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT action, resource_type, new_values, metadata_json "
                    "FROM audit.audit_logs "
                    "WHERE (actor_id = :uid OR resource_id = :uid) "
                    "AND action IN ('auth.session_revoked', 'auth.logout') "
                    "ORDER BY created_at"
                ),
                {"uid": user_id},
            )
        ).all()

    assert [row.action for row in rows] == [
        "auth.session_revoked",
        "auth.logout",
        "auth.session_revoked",
    ]
    assert rows[0].metadata_json["reason"] == "user_revoked"
    assert rows[1].new_values["sessions_revoked"] == 2
    assert rows[2].metadata_json["reason"] == "session_cap"
    assert rows[2].new_values["families_evicted"] == 1
