"""Session inventory, revocation and the per-user session cap.

A "session" is a refresh-token *family*: login opens one, every rotation extends
it, and reuse of a rotated token kills it. Listing and revoking therefore operate
on families rather than on individual token rows.

Revoking a family also blacklists the access-token jti in Redis. Without that, a
revoked session would keep working for up to the access-token TTL, which would
make `DELETE /auth/sessions/{id}` a promise the system does not keep.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from infrastructure.auth.tokens import ACCESS_TTL_SECONDS, sessions_to_evict
from infrastructure.caching.redis import get_redis, global_key
from infrastructure.database.models.users import RefreshToken
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth.sessions")


async def revoke_access_jtis(jtis: list[str]) -> None:
    """Blacklist access tokens until they would have expired anyway.

    `get_principal` consults this on every request. A Redis outage means the check
    fails open for at most one access-token lifetime, which is why revocation also
    always removes the refresh tokens: the durable store is the database, and
    Redis only shortens the window.
    """
    live = [j for j in jtis if j]
    if not live:
        return
    try:
        redis = get_redis()
        for jti in live:
            await redis.set(global_key("revoked", jti), "1", ex=ACCESS_TTL_SECONDS)
    except Exception:
        logger.error("auth_revocation_cache_unavailable", count=len(live))


async def list_sessions(
    *, tenant_id: UUID, user_id: UUID, current_family: str = ""
) -> list[dict[str, Any]]:
    """One entry per live family, newest first."""
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > utcnow(),
                    )
                    .order_by(RefreshToken.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        families: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = str(row.family_id)
            if key in families:
                continue
            families[key] = {
                "id": key,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "expires_at": row.expires_at.isoformat(),
                "current": key == current_family,
                # Never the token, the hash, or anything that could reconstruct one.
                "user_agent": (row.metadata_json or {}).get("user_agent"),
                "ip": (row.metadata_json or {}).get("ip"),
            }
    return list(families.values())


async def revoke_session(*, tenant_id: UUID, user_id: UUID, family_id: str) -> dict[str, Any]:
    """Revoke one family. Scoped to the caller's own user id, so this is not an IDOR."""
    from application.audit.recorder import AuditRecorder

    try:
        family = UUID(family_id)
    except ValueError as exc:
        raise NotFound("That session does not exist.") from exc

    revoked_jtis: list[str] = []
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.family_id == family,
                        # The user id is part of the predicate, not just the tenant:
                        # a colleague's session must be as invisible as another
                        # tenant's.
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            raise NotFound("That session does not exist.")
        for row in rows:
            row.revoked_at = utcnow()
            row.revoked_reason = "user_revoked"
            revoked_jtis.append(row.jti)
        AuditRecorder(session).record(
            action="auth.session_revoked",
            resource_type="auth_session",
            resource_id=family,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"tokens_revoked": len(revoked_jtis)},
            metadata={"reason": "user_revoked"},
        )

    await revoke_access_jtis(revoked_jtis)
    logger.info("auth_session_revoked", user_id=str(user_id), family_id=family_id)
    return {"revoked": True, "session_id": family_id}


async def revoke_all(
    *, tenant_id: UUID, user_id: UUID, reason: str = "logout_all", keep_family: str = ""
) -> dict[str, Any]:
    """Drop every session for the user, optionally sparing the current one."""
    from application.audit.recorder import AuditRecorder

    revoked_jtis: list[str] = []
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(RefreshToken).where(
                        RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            if keep_family and str(row.family_id) == keep_family:
                continue
            row.revoked_at = utcnow()
            row.revoked_reason = reason
            revoked_jtis.append(row.jti)
        AuditRecorder(session).record(
            action="auth.logout",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_id=user_id,
            new_values={"sessions_revoked": len(revoked_jtis)},
            metadata={"reason": reason, "kept_current_family": bool(keep_family)},
        )

    await revoke_access_jtis(revoked_jtis)
    logger.info("auth_logout_all", user_id=str(user_id), revoked=len(revoked_jtis))
    return {"signed_out": True, "sessions_revoked": len(revoked_jtis)}


async def enforce_session_cap(*, tenant_id: UUID, user_id: UUID) -> int:
    """Evict the oldest families once the per-user cap is exceeded.

    `sessions_to_evict` has been unit-tested since M04 but was never called, so the
    cap was documented and not enforced. Login calls this before opening a new
    family; the helper's contract is "return what to drop to make room for one
    more", which is why it is invoked before the insert.
    """
    from application.audit.recorder import AuditRecorder

    evicted_jtis: list[str] = []
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(RefreshToken)
                    .where(
                        RefreshToken.user_id == user_id,
                        RefreshToken.revoked_at.is_(None),
                        RefreshToken.expires_at > utcnow(),
                    )
                    .order_by(RefreshToken.created_at.asc())
                )
            )
            .scalars()
            .all()
        )

        # Oldest family first, each appearing once.
        ordered: list[str] = []
        for row in rows:
            key = str(row.family_id)
            if key not in ordered:
                ordered.append(key)

        doomed = set(sessions_to_evict(ordered))
        if not doomed:
            return 0
        for row in rows:
            if str(row.family_id) in doomed:
                row.revoked_at = utcnow()
                row.revoked_reason = "session_cap"
                evicted_jtis.append(row.jti)
        AuditRecorder(session).record(
            action="auth.session_revoked",
            resource_type="user",
            resource_id=user_id,
            tenant_id=tenant_id,
            actor_type="system",
            new_values={"families_evicted": len(doomed)},
            metadata={"reason": "session_cap"},
        )

    await revoke_access_jtis(evicted_jtis)
    logger.info("auth_session_cap_evicted", user_id=str(user_id), families=len(doomed))
    return len(doomed)
