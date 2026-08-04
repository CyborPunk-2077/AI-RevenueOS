"""Auth session mutations and their mandatory audit trail on real PostgreSQL."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.postgres


async def test_login_refresh_reuse_and_logout_commit_compact_audit_rows(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
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
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.auth.service import AuthResult, issue_session
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

    async def open_session() -> AuthResult:
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


async def test_registration_verification_and_password_reset_are_audited(
    wired_engine: Any, session_factory: Any
) -> None:
    from application.auth.registration import forgot_password, reset_password, signup, verify_email
    from application.auth.service import login
    from infrastructure.auth.tokens import TokenService, generate_keypair

    suffix = uuid4().hex[:10]
    email = f"registration-audit-{suffix}@example.in"
    password = "VerySecure-Willow-2026!"
    created = await signup(
        email=email,
        password=password,
        full_name="Registration Audit",
        organisation=f"Registration Audit {suffix}",
    )
    await verify_email(created.verification_token)

    private_key, public_key = generate_keypair()
    tokens = TokenService(
        private_key=private_key,
        public_key=public_key,
        issuer="https://registration-audit.test",
    )
    opened = await login(email, password, tokens)

    reset_token = await forgot_password(email)
    assert reset_token is not None
    await reset_password(reset_token, "Another-Maple-2026!Passphrase")

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(created.tenant_id)},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT action, new_values, metadata_json FROM audit.audit_logs "
                    "WHERE resource_id = :uid OR actor_id = :uid ORDER BY created_at"
                ),
                {"uid": created.user_id},
            )
        ).all()

    assert [row.action for row in rows] == [
        "user.created",
        "auth.email_verified",
        "auth.login",
        "auth.password_reset_requested",
        "auth.password_reset",
    ]
    assert rows[-1].new_values["sessions_revoked"] == 1

    serialized = str(rows).lower()
    assert password not in serialized
    assert reset_token not in serialized
    assert opened.refresh_token not in serialized
    assert "token_hash" not in serialized


async def test_mfa_security_mutations_are_audited_without_secrets(
    wired_engine: Any,
    seeded_tenants: Any,
    session_factory: Any,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    from application.auth.mfa import (
        complete_enrolment,
        consume_recovery_code,
        disable,
        regenerate_recovery_codes,
        start_enrolment,
    )
    from application.auth.service import issue_session
    from domain.auth.permissions import Role
    from infrastructure.auth.mfa import current_totp
    from infrastructure.auth.passwords import hash_password
    from infrastructure.auth.tokens import TokenService, generate_keypair
    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.database.models.users import User
    from shared.settings import get_settings
    from shared.utils.ids import uuid7
    from shared.utils.timeutil import utcnow

    monkeypatch.setenv("ENCRYPTION_MASTER_KEY", "mfa-audit-master-key-that-is-32-bytes+")
    get_settings.cache_clear()
    request.addfinalizer(get_settings.cache_clear)

    tenant_id, _ = seeded_tenants
    user_id = uuid7()
    email = f"mfa-audit-{uuid4()}@example.in"
    password = "MfaAudit-Willow-2026!"
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
                full_name="MFA Audit User",
                password_hash=hash_password(password),
                status="active",
                email_verified_at=utcnow(),
                is_owner=True,
                version=1,
            )
        )

    challenge = await start_enrolment(tenant_id=tenant_id, user_id=user_id, email=email)
    enrolled = await complete_enrolment(
        tenant_id=tenant_id,
        user_id=user_id,
        pending=challenge.pending,
        code=current_totp(challenge.secret),
    )
    recovery_code = enrolled["recovery_codes"][0]
    assert await consume_recovery_code(tenant_id=tenant_id, user_id=user_id, code=recovery_code)
    regenerated = await regenerate_recovery_codes(
        tenant_id=tenant_id,
        user_id=user_id,
        code=current_totp(challenge.secret),
    )

    private_key, public_key = generate_keypair()
    tokens = TokenService(
        private_key=private_key,
        public_key=public_key,
        issuer="https://mfa-audit.test",
    )
    await issue_session(
        user_id=user_id,
        tenant=tenant,
        roles=[Role.OWNER],
        email=email,
        name="MFA Audit User",
        tokens=tokens,
        mfa_verified=True,
    )
    disabled = await disable(
        tenant_id=tenant_id,
        user_id=user_id,
        password=password,
        code=current_totp(challenge.secret),
    )
    assert disabled["sessions_revoked"] is True

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT action, new_values, metadata_json FROM audit.audit_logs "
                    "WHERE resource_id = :uid AND action LIKE 'auth.mfa_%' "
                    "ORDER BY created_at"
                ),
                {"uid": user_id},
            )
        ).all()

    assert [row.action for row in rows] == [
        "auth.mfa_enabled",
        "auth.mfa_recovery_used",
        "auth.mfa_recovery_regenerated",
        "auth.mfa_disabled",
    ]
    assert rows[-1].new_values["sessions_revoked"] == 1

    serialized = str(rows)
    assert challenge.secret not in serialized
    assert challenge.pending not in serialized
    assert recovery_code not in serialized
    assert all(code not in serialized for code in regenerated["recovery_codes"])
    assert password not in serialized


async def test_api_key_reveal_and_revocation_are_audited_without_the_key(
    wired_engine: Any, seeded_tenants: Any, session_factory: Any
) -> None:
    from application.auth.api_keys import create, revoke
    from shared.utils.ids import uuid7

    tenant_id, _ = seeded_tenants
    user_id = uuid7()
    created = await create(
        tenant_id=tenant_id,
        user_id=user_id,
        name="audit test key",
        scopes=["lead:read"],
        granted_permissions=frozenset({"lead:read"}),
    )
    await revoke(tenant_id=tenant_id, user_id=user_id, key_id=created["id"])

    async with session_factory() as session, session.begin():
        await session.execute(
            text("SELECT set_config('app.tenant_id', :tid, true)"),
            {"tid": str(tenant_id)},
        )
        rows = (
            await session.execute(
                text(
                    "SELECT action, old_values, new_values, metadata_json "
                    "FROM audit.audit_logs WHERE resource_id = :rid ORDER BY created_at"
                ),
                {"rid": created["id"]},
            )
        ).all()

    assert [row.action for row in rows] == ["secret.accessed", "api_key.revoked"]
    assert rows[0].new_values["scopes"] == ["lead:read"]
    assert rows[1].new_values["revoked"] is True

    serialized = str(rows)
    assert created["key"] not in serialized
    assert "key_hash" not in serialized
