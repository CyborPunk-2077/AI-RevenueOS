"""Password login, refresh rotation, logout and session issuance.

Reuses the already-tested primitives (Argon2id, RS256, opaque rotating refresh
tokens with family-reuse revocation) rather than reimplementing them. The rest of
the surface lives beside this module: `registration`, `mfa`, `sessions`,
`api_keys` and `oauth`.

`issue_session` is the single place a session is created. Password login, a
completed MFA challenge and a Google callback all funnel through it, so the
session cap, the claim set and the audit line cannot drift between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from domain.auth.permissions import Role, widest_scope
from infrastructure.auth.passwords import (
    lockout_state,
    next_lockout,
    verify_password,
)
from infrastructure.auth.tokens import (
    AccessClaims,
    TokenService,
    evaluate_rotation,
    generate_refresh_token,
    hash_refresh_token,
    parse_refresh_token,
)
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.models.users import RefreshToken, User
from infrastructure.database.session import platform_session, tenant_session
from infrastructure.logging.setup import get_logger
from shared.exceptions import Unauthenticated
from shared.utils.ids import uuid7
from shared.utils.text import normalize_email
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth")

REFRESH_TTL_SECONDS = 604_800  # 7 days, sliding
MFA_CHALLENGE_TTL_SECONDS = 300


class MfaRequired(Exception):
    """The password was right; a second factor is still outstanding.

    Raised rather than returned so no caller can mistake a half-finished sign-in
    for a session. There is no `AuthResult` here to accidentally hand out.
    """

    def __init__(self, challenge_token: str) -> None:
        super().__init__("Multi-factor authentication is required.")
        self.challenge_token = challenge_token


async def create_mfa_challenge(*, tenant_id: UUID, user_id: UUID) -> str:
    """Park a pending sign-in in Redis for a few minutes."""
    import json
    import secrets as _secrets

    from infrastructure.caching.redis import get_redis, global_key

    token = _secrets.token_urlsafe(32)
    await get_redis().set(
        global_key("mfa_challenge", token),
        json.dumps({"user_id": str(user_id), "tenant_id": str(tenant_id)}),
        ex=MFA_CHALLENGE_TTL_SECONDS,
    )
    return token


async def consume_mfa_challenge(token: str) -> tuple[UUID, UUID]:
    """Redeem a challenge exactly once. Returns (tenant_id, user_id).

    `GETDEL` is atomic, so two racing submissions cannot both succeed -- a brute
    force gets one attempt per challenge, not unlimited attempts against one.
    """
    import json

    from infrastructure.caching.redis import get_redis, global_key

    expired = "This sign-in attempt has expired. Please start again."
    if not token:
        raise Unauthenticated(expired)
    raw = await get_redis().getdel(global_key("mfa_challenge", token))
    if not raw:
        raise Unauthenticated(expired)
    try:
        payload = json.loads(raw)
        return UUID(payload["tenant_id"]), UUID(payload["user_id"])
    except (TypeError, ValueError, KeyError) as exc:
        raise Unauthenticated(expired) from exc


async def load_principal(tenant_id: UUID, user_id: UUID) -> tuple[Tenant, list[Role], str, str]:
    """Re-read the account behind a challenge or an OAuth callback."""
    async with platform_session("authentication: reload principal") as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None or user.status != "active" or user.tenant_id != tenant_id:
            raise Unauthenticated("This account can no longer sign in.")
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        roles = await _load_roles(session, user)
        return tenant, roles, user.email, user.full_name


@dataclass(frozen=True, slots=True)
class AuthResult:
    access_token: str
    refresh_token: str
    expires_in: int
    user: dict[str, Any]


async def _load_roles(session: Any, user: User) -> list[Role]:
    """Resolve the user's roles. The demo seeds system roles by name."""
    from infrastructure.database.models.users import Role as RoleRow
    from infrastructure.database.models.users import UserRole

    rows = (
        (
            await session.execute(
                select(RoleRow.name)
                .join(UserRole, UserRole.role_id == RoleRow.id)
                .where(UserRole.user_id == user.id)
            )
        )
        .scalars()
        .all()
    )
    roles: list[Role] = []
    for name in rows:
        try:
            roles.append(Role(name))
        except ValueError:
            continue
    if not roles:
        roles = [Role.OWNER] if user.is_owner else [Role.MEMBER]
    return roles


def _claims_for_values(
    user_id: UUID,
    tenant_id: UUID,
    tenant_slug: str,
    email: str,
    name: str,
    roles: list[Role],
    session_id: str,
    mfa_verified: bool = False,
) -> AccessClaims:
    return AccessClaims(
        sub=str(user_id),
        tenant_id=str(tenant_id),
        tenant_slug=tenant_slug,
        email=email,
        name=name,
        roles=[r.value for r in roles],
        # Permissions are derived from roles at the request boundary rather than
        # embedded: the owner role alone carries ~720 codes, which made the token
        # (and therefore the session cookie) exceed the HTTP header limit.
        permissions=[],
        scope=widest_scope(roles).value,
        session_id=session_id,
        # A property of this session, not of the account: it is true only when
        # this sign-in actually completed an MFA challenge. Step-up protected
        # operations (billing, export, API-key creation, tenant deletion) consult
        # it, so setting it from `user.mfa_enabled` would defeat the purpose.
        mfa_verified=mfa_verified,
        authenticated_at=int(utcnow().timestamp()),
    )


async def login(email: str, password: str, tokens: TokenService) -> AuthResult:
    """Verify a password and issue a session.

    Two phases by necessity. Sign-in resolves the principal before a tenant is
    known, so the lookup runs under a logged platform context that migration 0004
    permits for SELECT only. Every subsequent write -- the failed-attempt counter,
    the refresh token -- runs bound to that user's tenant, so a write can never
    cross a tenant boundary.

    Failure is deliberately indistinguishable between an unknown address, a wrong
    password and an inactive account, so the endpoint cannot enumerate users.
    """
    from application.audit.recorder import AuditRecorder

    normalized = normalize_email(email)
    generic = "Email or password is incorrect."

    # --- phase 1: resolve, read only ---------------------------------------
    async with platform_session("authentication: resolve principal") as session:
        user = (
            await session.execute(
                select(User).where(User.email == normalized, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None or not user.password_hash:
            raise Unauthenticated(generic)

        locked, _ = lockout_state(user.failed_login_count, user.locked_until)
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one_or_none()
        roles = await _load_roles(session, user)

        user_id = user.id
        tenant_id = user.tenant_id
        password_hash = user.password_hash
        status = user.status
        failed_count = user.failed_login_count
        profile_email, profile_name = user.email, user.full_name

    if locked:
        async with tenant_session(tenant_id) as session:
            AuditRecorder(session).record(
                action="auth.login_failed",
                resource_type="user",
                resource_id=user_id,
                tenant_id=tenant_id,
                actor_type="anonymous",
                outcome="failure",
                metadata={"reason": "account_locked"},
            )
        raise Unauthenticated("This account is temporarily locked after repeated failed attempts.")

    password_ok = verify_password(password, password_hash)
    account_ok = status == "active" and tenant is not None and tenant.status in ("trial", "active")

    # --- phase 2: write, bound to the resolved tenant ----------------------
    if not password_ok:
        async with tenant_session(tenant_id) as session:
            row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
            row.failed_login_count = failed_count + 1
            row.locked_until = next_lockout(failed_count)
            AuditRecorder(session).record(
                action="auth.login_failed",
                resource_type="user",
                resource_id=user_id,
                tenant_id=tenant_id,
                actor_type="anonymous",
                outcome="failure",
                metadata={"reason": "invalid_credentials"},
            )
        logger.info("auth_login_failed", user_id=str(user_id))
        raise Unauthenticated(generic)

    if not account_ok:
        async with tenant_session(tenant_id) as session:
            AuditRecorder(session).record(
                action="auth.login_failed",
                resource_type="user",
                resource_id=user_id,
                tenant_id=tenant_id,
                actor_type="anonymous",
                outcome="failure",
                metadata={"reason": "account_inactive"},
            )
        raise Unauthenticated(generic)

    async with tenant_session(tenant_id) as session:
        row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        row.failed_login_count = 0
        row.locked_until = None
        row.last_login_at = utcnow()
        mfa_enabled = row.mfa_enabled

    assert tenant is not None  # narrowed by account_ok

    if mfa_enabled:
        # The password was correct but it is only the first factor, so no session
        # exists yet. The challenge is opaque, single use and short lived; it
        # carries no permissions and cannot be presented as a bearer token.
        challenge = await create_mfa_challenge(tenant_id=tenant_id, user_id=user_id)
        logger.info("auth_login_mfa_required", user_id=str(user_id))
        raise MfaRequired(challenge)

    logger.info("auth_login", user_id=str(user_id), tenant_id=str(tenant_id))
    return await issue_session(
        user_id=user_id,
        tenant=tenant,
        roles=roles,
        email=profile_email,
        name=profile_name,
        tokens=tokens,
        mfa_verified=False,
    )


async def issue_session(
    *,
    user_id: UUID,
    tenant: Tenant,
    roles: list[Role],
    email: str,
    name: str,
    tokens: TokenService,
    mfa_verified: bool = False,
) -> AuthResult:
    """Open a new refresh-token family and mint the matching access token.

    Enforces the per-user session cap first. `sessions_to_evict` returns what must
    go to make room for one more, so it runs before the insert rather than after.
    """
    from application.audit.recorder import AuditRecorder
    from application.auth.sessions import enforce_session_cap

    tenant_id = tenant.id
    await enforce_session_cap(tenant_id=tenant_id, user_id=user_id)

    plaintext, token_hash, jti = generate_refresh_token()
    family_id = uuid7()
    async with tenant_session(tenant_id) as session:
        session.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=user_id,
                jti=jti,
                token_hash=token_hash,
                family_id=family_id,
                expires_at=utcnow() + timedelta(seconds=REFRESH_TTL_SECONDS),
            )
        )
        AuditRecorder(session).record(
            action="auth.login",
            resource_type="auth_session",
            resource_id=family_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"mfa_verified": mfa_verified},
        )

    access_token, expires_at = tokens.issue_access_token(
        _claims_for_values(
            user_id,
            tenant_id,
            tenant.slug,
            email,
            name,
            roles,
            str(family_id),
            mfa_verified=mfa_verified,
        )
    )
    return AuthResult(
        access_token=access_token,
        refresh_token=plaintext,
        expires_in=int((expires_at - utcnow()).total_seconds()),
        user={
            "id": str(user_id),
            "email": email,
            "name": name,
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant.slug,
            "tenant_name": tenant.name,
            "roles": [r.value for r in roles],
            "mfa_verified": mfa_verified,
        },
    )


async def refresh(refresh_token: str, tokens: TokenService) -> AuthResult:
    """Rotate a refresh token. Reuse of a rotated token revokes the whole family."""
    from application.audit.recorder import AuditRecorder

    jti = parse_refresh_token(refresh_token)
    presented = hash_refresh_token(refresh_token)
    expired = "This session is no longer valid. Please sign in again."

    async with platform_session("authentication: resolve refresh token") as session:
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.jti == jti))
        ).scalar_one_or_none()
        outcome = evaluate_rotation(
            stored_hash=row.token_hash if row else None,
            presented_hash=presented,
            revoked_at=row.revoked_at if row else None,
            expires_at=row.expires_at if row else None,
            family_id=row.family_id if row else None,
        )
        if row is not None:
            tenant_id, family_id, user_id, current_jti = (
                row.tenant_id,
                row.family_id,
                row.user_id,
                row.jti,
            )

    if outcome.reuse_detected and row is not None:
        # Replay of an already-rotated token: assume theft, drop the family.
        async with tenant_session(tenant_id) as session:
            revoked_count = 0
            for sibling in (
                (
                    await session.execute(
                        select(RefreshToken).where(
                            RefreshToken.family_id == family_id,
                            RefreshToken.revoked_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            ):
                sibling.revoked_at = utcnow()
                sibling.revoked_reason = "family_reuse"
                revoked_count += 1
            AuditRecorder(session).record(
                action="auth.refresh_reuse",
                resource_type="auth_session",
                resource_id=family_id,
                tenant_id=tenant_id,
                actor_id=user_id,
                outcome="blocked",
                new_values={"sessions_revoked": revoked_count},
            )
        logger.warning("auth_refresh_reuse", family_id=str(family_id))
        raise Unauthenticated(expired)

    if not outcome.accepted or row is None:
        if row is not None:
            async with tenant_session(tenant_id) as session:
                AuditRecorder(session).record(
                    action="auth.refresh",
                    resource_type="auth_session",
                    resource_id=family_id,
                    tenant_id=tenant_id,
                    actor_id=user_id,
                    outcome="failure",
                    metadata={"reason": outcome.reason or "refresh_rejected"},
                )
        raise Unauthenticated(expired)

    async with platform_session("authentication: reload principal") as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None or user.status != "active":
            raise Unauthenticated(expired)
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one()
        roles = await _load_roles(session, user)
        profile_email, profile_name = user.email, user.full_name
        tenant_slug, tenant_name = tenant.slug, tenant.name

    plaintext, token_hash, new_jti = generate_refresh_token()
    async with tenant_session(tenant_id) as session:
        current = (
            await session.execute(select(RefreshToken).where(RefreshToken.jti == current_jti))
        ).scalar_one()
        current.revoked_at = utcnow()
        current.revoked_reason = "rotated"
        current.last_used_at = utcnow()
        session.add(
            RefreshToken(
                tenant_id=tenant_id,
                user_id=user_id,
                jti=new_jti,
                token_hash=token_hash,
                family_id=family_id,
                parent_jti=current_jti,
                expires_at=utcnow() + timedelta(seconds=REFRESH_TTL_SECONDS),
            )
        )
        AuditRecorder(session).record(
            action="auth.refresh",
            resource_type="auth_session",
            resource_id=family_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"rotated": True},
        )

    access_token, expires_at = tokens.issue_access_token(
        _claims_for_values(
            user_id, tenant_id, tenant_slug, profile_email, profile_name, roles, str(family_id)
        )
    )
    return AuthResult(
        access_token=access_token,
        refresh_token=plaintext,
        expires_in=int((expires_at - utcnow()).total_seconds()),
        user={
            "id": str(user_id),
            "email": profile_email,
            "name": profile_name,
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant_slug,
            "tenant_name": tenant_name,
            "roles": [r.value for r in roles],
        },
    )


async def logout(refresh_token: str) -> None:
    """Revoke the presented token's entire family."""
    from application.audit.recorder import AuditRecorder

    try:
        jti = parse_refresh_token(refresh_token)
    except Unauthenticated:
        return

    async with platform_session("authentication: resolve session family") as session:
        row = (
            await session.execute(select(RefreshToken).where(RefreshToken.jti == jti))
        ).scalar_one_or_none()
        if row is None:
            return
        tenant_id, family_id, user_id = row.tenant_id, row.family_id, row.user_id

    async with tenant_session(tenant_id) as session:
        revoked_count = 0
        for sibling in (
            (
                await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.family_id == family_id,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        ):
            sibling.revoked_at = utcnow()
            sibling.revoked_reason = "logout"
            revoked_count += 1
        AuditRecorder(session).record(
            action="auth.logout",
            resource_type="auth_session",
            resource_id=family_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"sessions_revoked": revoked_count},
        )
    logger.info("auth_logout", user_id=str(user_id))
