"""Minimal authentication service for the demo vertical slice.

Scope is deliberately narrow: password login, refresh rotation, current user and
logout. It reuses the already-tested primitives (Argon2id, RS256, opaque rotating
refresh tokens with family-reuse revocation) rather than reimplementing them.

The full surface -- signup, MFA, Google OAuth, password reset, API keys, session
listing -- is P0-2 and is intentionally NOT here.
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
        # The demo slice does not enrol MFA. Step-up protected operations
        # (billing, export, tenant deletion) therefore remain refused, which is
        # the correct behaviour rather than a bypass.
        mfa_verified=False,
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
        raise Unauthenticated("This account is temporarily locked after repeated failed attempts.")

    password_ok = verify_password(password, password_hash)
    account_ok = status == "active" and tenant is not None and tenant.status in ("trial", "active")

    # --- phase 2: write, bound to the resolved tenant ----------------------
    if not password_ok:
        async with tenant_session(tenant_id) as session:
            row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
            row.failed_login_count = failed_count + 1
            row.locked_until = next_lockout(failed_count)
        logger.info("auth_login_failed", user_id=str(user_id))
        raise Unauthenticated(generic)

    if not account_ok:
        raise Unauthenticated(generic)

    plaintext, token_hash, jti = generate_refresh_token()
    family_id = uuid7()
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        row.failed_login_count = 0
        row.locked_until = None
        row.last_login_at = utcnow()
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

    assert tenant is not None  # narrowed by account_ok
    access_token, expires_at = tokens.issue_access_token(
        _claims_for_values(
            user_id, tenant_id, tenant.slug, profile_email, profile_name, roles, str(family_id)
        )
    )
    logger.info("auth_login", user_id=str(user_id), tenant_id=str(tenant_id))
    return AuthResult(
        access_token=access_token,
        refresh_token=plaintext,
        expires_in=int((expires_at - utcnow()).total_seconds()),
        user={
            "id": str(user_id),
            "email": profile_email,
            "name": profile_name,
            "tenant_id": str(tenant_id),
            "tenant_slug": tenant.slug,
            "tenant_name": tenant.name,
            "roles": [r.value for r in roles],
        },
    )


async def refresh(refresh_token: str, tokens: TokenService) -> AuthResult:
    """Rotate a refresh token. Reuse of a rotated token revokes the whole family."""
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
        logger.warning("auth_refresh_reuse", family_id=str(family_id))
        raise Unauthenticated(expired)

    if not outcome.accepted or row is None:
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
    logger.info("auth_logout", user_id=str(user_id))
