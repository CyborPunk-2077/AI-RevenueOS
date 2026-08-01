"""Developer API keys: minted once, stored hashed, listed masked.

The value is returned by exactly one call — the one that creates it. Nothing else
in the system can reproduce it, because only a SHA-256 is persisted. That is the
whole point of the design, so `list` deliberately has no code path that could
return a usable credential even by accident.

Creation is a step-up operation (`api_key.create` is in `STEP_UP_OPERATIONS`), so
the route requires a session that has recently proved MFA.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any
from uuid import UUID

from sqlalchemy import select

from infrastructure.database.models.users import ApiKey
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound, ValidationError
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth.api_keys")

KEY_PREFIX = "ak_live_"
PREFIX_VISIBLE = 12


def _hash_key(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _mask(prefix: str) -> str:
    """What a listing shows: enough to recognise the key, not enough to use it."""
    return f"{prefix}{'.' * 8}"


def _serialize(row: ApiKey) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "name": row.name,
        "masked_key": _mask(row.key_prefix),
        "scopes": list(row.scopes or []),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }


async def create(
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    scopes: list[str],
    granted_permissions: frozenset[str],
) -> dict[str, Any]:
    """Mint a key. Its scopes cannot exceed what the creating principal holds."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValidationError("A name is required.")

    requested = [s.strip() for s in scopes if s.strip()]
    # Privilege escalation guard: an Agent must not be able to mint an owner-scoped
    # key and then use it to do what their own session cannot.
    excessive = sorted(set(requested) - granted_permissions)
    if excessive:
        raise ValidationError(
            "You cannot grant a key permissions you do not hold.",
            details={"not_granted": excessive},
        )

    plaintext = f"{KEY_PREFIX}{secrets.token_urlsafe(32)}"
    async with tenant_session(tenant_id) as session:
        row = ApiKey(
            tenant_id=tenant_id,
            name=clean_name[:120],
            key_prefix=plaintext[:PREFIX_VISIBLE],
            key_hash=_hash_key(plaintext),
            scopes=requested,
            created_by=user_id,
        )
        session.add(row)
        await session.flush()
        created = _serialize(row)

    logger.info("auth_api_key_created", tenant_id=str(tenant_id), user_id=str(user_id))
    # `key` appears here and nowhere else, ever.
    return {**created, "key": plaintext}


async def list_keys(*, tenant_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(ApiKey)
                    .where(ApiKey.revoked_at.is_(None))
                    .order_by(ApiKey.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        return [_serialize(row) for row in rows]


async def revoke(*, tenant_id: UUID, key_id: str) -> dict[str, Any]:
    """Soft-revoke. The row is kept so audit history still resolves the key."""
    try:
        identifier = UUID(key_id)
    except ValueError as exc:
        raise NotFound("That API key does not exist.") from exc

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(ApiKey).where(ApiKey.id == identifier, ApiKey.revoked_at.is_(None))
            )
        ).scalar_one_or_none()
        if row is None:
            # A key belonging to another tenant is invisible under RLS and reports
            # as absent, which is the same answer as a key that never existed.
            raise NotFound("That API key does not exist.")
        row.revoked_at = utcnow()

    logger.info("auth_api_key_revoked", tenant_id=str(tenant_id), key_id=key_id)
    return {"revoked": True, "id": key_id}
