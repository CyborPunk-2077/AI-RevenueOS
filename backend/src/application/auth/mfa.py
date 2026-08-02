"""TOTP enrolment, verification, disablement and recovery codes.

The cryptography already existed and is unit-tested; this module is the state
machine around it. Two properties matter and are enforced here rather than at the
route:

* A secret is only committed to the user record once a code generated from it has
  been proved. Enrolment that is started and abandoned leaves nothing behind.
* `mfa_verified` is a property of a *session*, not of an account. It is set on the
  access token only by a successful challenge, which is what makes the step-up
  dependency meaningful for billing, exports and API-key creation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from infrastructure.auth.encryption import EnvelopeEncryptor
from infrastructure.auth.mfa import (
    generate_recovery_codes,
    generate_totp_secret,
    provisioning_uri,
    verify_recovery_code,
    verify_totp,
)
from infrastructure.auth.passwords import verify_password
from infrastructure.database.models.users import RefreshToken, User
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from shared.exceptions import Conflict, Unauthenticated, ValidationError
from shared.settings import get_settings
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth.mfa")

_BAD_CODE = "That code is not valid."


def _encryptor() -> EnvelopeEncryptor:
    """Fail closed: an unset master key must not silently store a plaintext secret."""
    master_key = get_settings().encryption_master_key
    if not master_key:
        raise ValidationError(
            "Multi-factor authentication is unavailable: no encryption key is configured."
        )
    return EnvelopeEncryptor(master_key)


@dataclass(frozen=True, slots=True)
class EnrolmentChallenge:
    """Returned by setup. The secret is shown once, for the authenticator app."""

    secret: str
    provisioning_uri: str
    # Encrypted form, handed back to the client so `verify` can commit it without
    # a server-side staging table. It is opaque and bound to the tenant, so it is
    # useless anywhere else, and it is worthless until a matching code proves it.
    pending: str


async def start_enrolment(*, tenant_id: UUID, user_id: UUID, email: str) -> EnrolmentChallenge:
    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        if user.mfa_enabled:
            raise Conflict("Multi-factor authentication is already enabled for this account.")

    secret = generate_totp_secret()
    encrypted = _encryptor().encrypt(secret, tenant_id=str(tenant_id))
    return EnrolmentChallenge(
        secret=secret,
        provisioning_uri=provisioning_uri(secret, account=email),
        pending=encrypted,
    )


async def complete_enrolment(
    *, tenant_id: UUID, user_id: UUID, pending: str, code: str
) -> dict[str, Any]:
    """Commit the secret only if the user can already generate codes from it."""
    from application.audit.recorder import AuditRecorder

    try:
        secret = _encryptor().decrypt(pending, tenant_id=str(tenant_id)).decode()
    except Exception as exc:
        raise ValidationError("This enrolment has expired. Start again.") from exc

    if not verify_totp(secret, code):
        raise ValidationError(_BAD_CODE)

    codes = generate_recovery_codes()
    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        if user.mfa_enabled:
            raise Conflict("Multi-factor authentication is already enabled for this account.")
        user.mfa_enabled = True
        user.mfa_secret_encrypted = pending
        user.mfa_recovery_codes = codes.hashes
        AuditRecorder(session).record(
            action="auth.mfa_enabled",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"mfa_enabled": True, "recovery_code_count": len(codes.hashes)},
        )

    logger.info("auth_mfa_enabled", user_id=str(user_id), tenant_id=str(tenant_id))
    # The only time the recovery codes are ever readable.
    return {"enabled": True, "recovery_codes": codes.plaintext}


async def check_code(*, tenant_id: UUID, user_id: UUID, code: str) -> bool:
    """Verify a TOTP code against the enrolled secret."""
    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        if not user.mfa_enabled or not user.mfa_secret_encrypted:
            return False
        encrypted = user.mfa_secret_encrypted

    try:
        secret = _encryptor().decrypt(encrypted, tenant_id=str(tenant_id)).decode()
    except Exception:
        logger.error("auth_mfa_secret_undecryptable", user_id=str(user_id))
        return False
    return verify_totp(secret, code)


async def consume_recovery_code(*, tenant_id: UUID, user_id: UUID, code: str) -> bool:
    """Spend a single-use recovery code. Consumed codes are removed, not marked."""
    from application.audit.recorder import AuditRecorder

    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        hashes = list(user.mfa_recovery_codes or [])
        if not user.mfa_enabled or not hashes:
            return False
        index = verify_recovery_code(code, hashes)
        if index is None:
            return False
        remaining = [h for position, h in enumerate(hashes) if position != index]
        user.mfa_recovery_codes = remaining
        left = len(remaining)
        AuditRecorder(session).record(
            action="auth.mfa_recovery_used",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"recovery_codes_remaining": left},
        )

    logger.warning(
        "auth_mfa_recovery_used", user_id=str(user_id), tenant_id=str(tenant_id), remaining=left
    )
    return True


async def regenerate_recovery_codes(*, tenant_id: UUID, user_id: UUID, code: str) -> dict[str, Any]:
    """Replace the recovery set. Requires a live TOTP code, not just a session."""
    from application.audit.recorder import AuditRecorder

    if not await check_code(tenant_id=tenant_id, user_id=user_id, code=code):
        raise ValidationError(_BAD_CODE)

    codes = generate_recovery_codes()
    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        user.mfa_recovery_codes = codes.hashes
        AuditRecorder(session).record(
            action="auth.mfa_recovery_regenerated",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"recovery_code_count": len(codes.hashes)},
        )

    logger.info("auth_mfa_recovery_regenerated", user_id=str(user_id))
    return {"recovery_codes": codes.plaintext}


async def disable(
    *, tenant_id: UUID, user_id: UUID, password: str, code: str | None
) -> dict[str, Any]:
    """Turn MFA off. Requires the password *and* a current code or recovery code.

    Both are demanded because disabling MFA is exactly what an attacker holding a
    hijacked session would try first. Every other session is dropped afterwards.
    """
    from application.audit.recorder import AuditRecorder

    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        if not user.mfa_enabled:
            raise Conflict("Multi-factor authentication is not enabled for this account.")
        if not user.password_hash or not verify_password(password, user.password_hash):
            raise Unauthenticated("Your password is incorrect.")

    proved = bool(code) and (
        await check_code(tenant_id=tenant_id, user_id=user_id, code=code or "")
        or await consume_recovery_code(tenant_id=tenant_id, user_id=user_id, code=code or "")
    )
    if not proved:
        raise ValidationError("A current authenticator code or recovery code is required.")

    async with tenant_session(tenant_id) as session:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one()
        user.mfa_enabled = False
        user.mfa_secret_encrypted = None
        user.mfa_recovery_codes = []

        revoked_count = 0
        for token in (
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
            token.revoked_at = utcnow()
            token.revoked_reason = "mfa_disabled"
            revoked_count += 1
        AuditRecorder(session).record(
            action="auth.mfa_disabled",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"mfa_enabled": False, "sessions_revoked": revoked_count},
        )

    logger.warning("auth_mfa_disabled", user_id=str(user_id), tenant_id=str(tenant_id))
    return {"enabled": False, "sessions_revoked": True}
