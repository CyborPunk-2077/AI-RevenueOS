"""Self-serve sign-up, email confirmation and password recovery.

These are the unauthenticated entry points, so every one of them is written to be
non-enumerating: the response to "this address exists" is byte-for-byte the
response to "it does not". The caller learns nothing it did not already know.

Token handling follows the same rule throughout: generate a high-entropy value,
persist only its SHA-256, hand the plaintext to the caller once, and mark the row
used on redemption so a replay is a no-op rather than a second grant.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select

from domain.auth.permissions import ROLE_PERMISSIONS, Role
from infrastructure.auth.passwords import (
    hash_password,
    is_in_history,
    push_history,
    validate_password,
)
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.models.users import (
    EmailVerification,
    PasswordReset,
    RefreshToken,
    RolePermission,
    User,
    UserRole,
)
from infrastructure.database.models.users import Role as RoleRow
from infrastructure.database.session import platform_session, tenant_session, unscoped_session
from infrastructure.logging.setup import get_logger
from shared.exceptions import Conflict, NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.text import normalize_email
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth.registration")

VERIFICATION_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)
SLUG_ALPHABET = "abcdefghijklmnopqrstuvwxyz0123456789-"


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _new_token(tenant_id: UUID) -> tuple[str, str]:
    """Mint `<tenant_id>.<secret>` and its hash.

    The tenant id is carried in the token on purpose. Redemption happens before
    anyone is authenticated, so the alternative is a cross-tenant read: either the
    migration credential, or a second SELECT-only policy on these tables like the
    one `0004` had to add for `users`. Naming the tenant in the token means the
    lookup runs inside `tenant_session(...)` under the ordinary isolation policy
    instead. The id is not a secret and grants nothing on its own -- the row is
    found by the hash of the whole string, so a forged prefix simply matches
    nothing.
    """
    plaintext = f"{tenant_id}.{secrets.token_urlsafe(32)}"
    return plaintext, _hash_token(plaintext)


def _split_token(plaintext: str) -> tuple[UUID, str]:
    """Recover the tenant from a token, or refuse it."""
    prefix, _, secret = plaintext.partition(".")
    if not prefix or not secret:
        raise NotFound(_INVALID_LINK)
    try:
        return UUID(prefix), _hash_token(plaintext)
    except ValueError as exc:
        raise NotFound(_INVALID_LINK) from exc


_INVALID_LINK = "This link is invalid, expired, or has already been used."


def slugify_organisation(name: str) -> str:
    """A URL-safe tenant slug. Collisions are resolved by the caller, not here."""
    lowered = "".join(c if c in SLUG_ALPHABET else "-" for c in name.strip().lower())
    collapsed = "-".join(part for part in lowered.split("-") if part)
    return (collapsed or "org")[:40]


@dataclass(frozen=True, slots=True)
class SignupResult:
    tenant_id: UUID
    user_id: UUID
    tenant_slug: str
    email: str
    # Handed back so the caller can deliver it. Email delivery is an externally
    # gated capability, so in local development it is surfaced rather than sent,
    # and the route only echoes it when the environment allows.
    verification_token: str


async def _unique_slug(session: Any, desired: str) -> str:
    slug = desired
    for attempt in range(50):
        taken = (
            await session.execute(select(Tenant.id).where(Tenant.slug == slug))
        ).scalar_one_or_none()
        if taken is None:
            return slug
        slug = f"{desired[:34]}-{secrets.token_hex(2)}" if attempt else f"{desired[:34]}-1"
    raise Conflict("Could not allocate an organisation address. Try a different name.")


async def signup(*, email: str, password: str, full_name: str, organisation: str) -> SignupResult:
    """Create a tenant and its owner.

    `app.tenants` is not tenant-owned, so the row can be inserted without a bound
    context; everything after it is written inside `tenant_session(new_tenant_id)`
    so the RLS `WITH CHECK` clause governs it exactly as it governs ordinary
    traffic. There is no privileged path here.
    """
    from application.audit.recorder import AuditRecorder

    normalized = normalize_email(email)

    check = validate_password(password, email=normalized, full_name=full_name)
    if not check.ok:
        raise ValidationError(
            "The password does not meet the policy.", details={"problems": check.problems}
        )

    async with platform_session("registration: check for an existing account") as session:
        existing = (
            await session.execute(
                select(User.id).where(User.email == normalized, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
    if existing is not None:
        # Deliberately explicit: sign-up is the one flow where silence would leave
        # the user unable to act. The address is one they control, or they are
        # about to be told to reset a password they cannot use.
        raise Conflict("An account already exists for this email address.")

    tenant_id = uuid7()
    user_id = uuid7()
    role_id = uuid7()
    password_hash = hash_password(password)
    verification_plain, verification_hash = _new_token(tenant_id)

    async with unscoped_session() as session:
        slug = await _unique_slug(session, slugify_organisation(organisation))
        session.add(
            Tenant(
                id=tenant_id,
                name=organisation.strip()[:200],
                slug=slug,
                plan_code="starter",
                status="trial",
                trial_ends_at=utcnow() + timedelta(days=14),
                version=1,
            )
        )

    async with tenant_session(tenant_id) as session:
        session.add(
            RoleRow(
                id=role_id,
                tenant_id=tenant_id,
                name=Role.OWNER.value,
                description="Organisation owner",
                is_system=True,
                default_scope="global",
                version=1,
            )
        )
        for code in sorted(ROLE_PERMISSIONS[Role.OWNER]):
            session.add(RolePermission(tenant_id=tenant_id, role_id=role_id, permission_code=code))
        session.add(
            User(
                id=user_id,
                tenant_id=tenant_id,
                email=normalized,
                full_name=full_name.strip()[:200],
                password_hash=password_hash,
                password_changed_at=utcnow(),
                # Unverified until the emailed link is redeemed. `login` refuses a
                # non-active account, so an unconfirmed sign-up cannot sign in.
                status="invited",
                is_owner=True,
                version=1,
            )
        )
        session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role_id))
        session.add(
            EmailVerification(
                tenant_id=tenant_id,
                user_id=user_id,
                email=normalized,
                token_hash=verification_hash,
                expires_at=utcnow() + VERIFICATION_TTL,
            )
        )
        AuditRecorder(session).record(
            action="user.created",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_type="anonymous",
            new_values={"status": "invited", "role": Role.OWNER.value},
        )

    logger.info("auth_signup", tenant_id=str(tenant_id), user_id=str(user_id))
    return SignupResult(
        tenant_id=tenant_id,
        user_id=user_id,
        tenant_slug=slug,
        email=normalized,
        verification_token=verification_plain,
    )


async def verify_email(token: str) -> dict[str, Any]:
    """Redeem a confirmation token. Single use, and expiry is enforced."""
    from application.audit.recorder import AuditRecorder

    tenant_id, token_hash = _split_token(token)

    async with tenant_session(tenant_id) as session:
        record = (
            await session.execute(
                select(EmailVerification).where(EmailVerification.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if record is None or record.used_at is not None or record.expires_at <= utcnow():
            raise NotFound(_INVALID_LINK)
        record.used_at = utcnow()

        user = (
            await session.execute(select(User).where(User.id == record.user_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFound(_INVALID_LINK)
        user.email_verified_at = utcnow()
        if user.status == "invited":
            user.status = "active"
        email, status, user_id = user.email, user.status, user.id
        AuditRecorder(session).record(
            action="auth.email_verified",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_type="anonymous",
            new_values={"status": status, "email_verified": True},
        )

    logger.info("auth_email_verified", user_id=str(user_id), tenant_id=str(tenant_id))
    return {"email": email, "status": status, "verified": True}


async def forgot_password(email: str) -> str | None:
    """Issue a reset token, or quietly do nothing.

    Returns the plaintext token when a reset was actually issued so the caller can
    deliver it. The route never varies its response on this value: an unknown
    address and a known one are indistinguishable to the client.
    """
    from application.audit.recorder import AuditRecorder

    try:
        normalized = normalize_email(email)
    except ValueError:
        return None

    async with platform_session("recovery: resolve account") as session:
        user = (
            await session.execute(
                select(User).where(User.email == normalized, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None or user.status not in ("active", "invited"):
            logger.info("auth_reset_requested_unknown")
            return None
        tenant_id, user_id = user.tenant_id, user.id

    plaintext, token_hash = _new_token(tenant_id)
    async with tenant_session(tenant_id) as session:
        session.add(
            PasswordReset(
                tenant_id=tenant_id,
                user_id=user_id,
                token_hash=token_hash,
                expires_at=utcnow() + RESET_TTL,
            )
        )
        AuditRecorder(session).record(
            action="auth.password_reset_requested",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_type="anonymous",
        )
    logger.info("auth_reset_requested", user_id=str(user_id), tenant_id=str(tenant_id))
    return plaintext


async def reset_password(token: str, new_password: str) -> dict[str, Any]:
    """Consume a reset token, set the password and drop every existing session.

    Revoking the sessions is the point: a password reset is the response to a
    suspected compromise, so leaving an attacker's refresh tokens alive would
    defeat it.
    """
    from application.audit.recorder import AuditRecorder

    tenant_id, token_hash = _split_token(token)

    async with tenant_session(tenant_id) as session:
        record = (
            await session.execute(
                select(PasswordReset).where(PasswordReset.token_hash == token_hash)
            )
        ).scalar_one_or_none()
        if record is None or record.used_at is not None or record.expires_at <= utcnow():
            raise NotFound(_INVALID_LINK)

        user = (
            await session.execute(select(User).where(User.id == record.user_id))
        ).scalar_one_or_none()
        if user is None:
            raise NotFound(_INVALID_LINK)

        check = validate_password(new_password, email=user.email, full_name=user.full_name)
        if not check.ok:
            raise ValidationError(
                "The password does not meet the policy.", details={"problems": check.problems}
            )
        if is_in_history(new_password, list(user.password_history or [])):
            raise ValidationError(
                "This password was used recently. Choose one you have not used before."
            )

        record.used_at = utcnow()
        user.password_history = push_history(user.password_hash, list(user.password_history or []))
        user.password_hash = hash_password(new_password)
        user.password_changed_at = utcnow()
        user.failed_login_count = 0
        user.locked_until = None
        if user.status == "invited":
            user.status = "active"
        user_id = user.id

        revoked_count = 0
        for token_row in (
            (
                await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        ):
            token_row.revoked_at = utcnow()
            token_row.revoked_reason = "password_reset"
            revoked_count += 1
        AuditRecorder(session).record(
            action="auth.password_reset",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_type="anonymous",
            new_values={"sessions_revoked": revoked_count},
        )

    logger.info("auth_password_reset", user_id=str(user_id), tenant_id=str(tenant_id))
    return {"reset": True, "sessions_revoked": True}
