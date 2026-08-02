"""Request-scoped authentication, tenant resolution and permission dependencies.

Tenant identity comes from validated host/slug PLUS authenticated membership. A
client-supplied tenant id is never trusted on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request

from api.app.settings import Settings, get_settings
from domain.auth.permissions import EffectivePermissions, Scope, permissions_for
from infrastructure.auth.tokens import TokenService
from infrastructure.caching.rate_limit import RateLimiter
from infrastructure.logging.context import bind_context
from infrastructure.monitoring.metrics import tenant_isolation_violations
from shared.exceptions import Forbidden, RateLimited, Unauthenticated
from shared.utils.timeutil import UTC


@dataclass(frozen=True, slots=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    tenant_slug: str
    email: str
    name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    scope: Scope
    branch_ids: frozenset[str] = frozenset()
    team_ids: frozenset[str] = frozenset()
    session_id: str = ""
    mfa_verified: bool = False
    authenticated_at: int = 0
    actor_type: str = "user"
    jti: str = ""

    def effective(self) -> EffectivePermissions:
        return EffectivePermissions(
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
            user_id=str(self.user_id),
        )

    def require(self, resource: str, action: str) -> None:
        if f"{resource}:{action}" not in self.permissions:
            raise Forbidden(
                "You do not have permission to perform this action.",
                details={"required_permission": f"{resource}:{action}"},
            )


_DEV_KEY_PATH = Path(__file__).resolve().parents[3] / ".dev-keys" / "jwt.pem"


def _local_dev_keypair() -> tuple[str, str]:
    """A stable RS256 keypair for local development, persisted outside Git."""
    from cryptography.hazmat.primitives import serialization

    from infrastructure.auth.tokens import generate_keypair

    if _DEV_KEY_PATH.exists():
        private_key = _DEV_KEY_PATH.read_text()
        public_key = (
            serialization.load_pem_private_key(private_key.encode(), password=None)
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM,
                serialization.PublicFormat.SubjectPublicKeyInfo,
            )
            .decode()
        )
        return private_key, public_key

    private_key, public_key = generate_keypair()
    _DEV_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    _DEV_KEY_PATH.write_text(private_key)
    _DEV_KEY_PATH.chmod(0o600)
    return private_key, public_key


def get_app_settings(request: Request) -> Settings:
    """Always resolve the settings the application was built with, not a cached global."""
    return getattr(request.app.state, "settings", None) or get_settings()


def get_token_service(settings: Annotated[Settings, Depends(get_app_settings)]) -> TokenService:
    private_key, public_key = settings.jwt_private_key, settings.jwt_public_key
    if not private_key or not public_key:
        # Local development only. Production boot fails earlier in
        # `assert_production_safe`, which refuses to start without signing
        # material. The key is persisted (gitignored) so restarting the API does
        # not silently invalidate every open session.
        if settings.environment != "local":
            raise RuntimeError(
                "JWT signing material is not configured; refusing to generate an "
                f"ephemeral key in the '{settings.environment}' environment"
            )
        private_key, public_key = _local_dev_keypair()
        object.__setattr__(settings, "jwt_private_key", private_key)
        object.__setattr__(settings, "jwt_public_key", public_key)
    return TokenService(
        private_key=private_key,
        public_key=public_key,
        issuer=settings.jwt_issuer,
        kid=settings.jwt_kid,
        access_ttl=settings.access_token_ttl_seconds,
    )


async def get_principal(
    request: Request,
    tokens: Annotated[TokenService, Depends(get_token_service)],
    authorization: Annotated[str | None, Header()] = None,
) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise Unauthenticated("A bearer access token is required.")
    claims = tokens.decode_access_token(authorization.split(" ", 1)[1].strip())

    if await _is_revoked(request, claims.get("jti", "")):
        raise Unauthenticated("This session has been revoked.")

    # A token may carry an explicit permission list (custom roles, service
    # principals). When it does not, the built-in role matrix is authoritative.
    claimed = claims.get("permissions") or []
    roles = tuple(claims.get("roles", []))
    permissions = frozenset(claimed) if claimed else permissions_for(list(roles))

    principal = Principal(
        user_id=UUID(claims["sub"]),
        tenant_id=UUID(claims["tenant_id"]),
        tenant_slug=str(claims.get("tenant_slug", "")),
        email=str(claims.get("email", "")),
        name=str(claims.get("name", "")),
        roles=roles,
        permissions=permissions,
        scope=Scope(claims.get("scope", "self")),
        branch_ids=frozenset(claims.get("branch_ids", [])),
        team_ids=frozenset(claims.get("team_ids", [])),
        session_id=str(claims.get("sid", "")),
        mfa_verified=bool(claims.get("mfa", False)),
        authenticated_at=int(claims.get("auth_time", 0)),
        actor_type=str(claims.get("actor_type", "user")),
        jti=str(claims.get("jti", "")),
    )
    bind_context(
        correlation_id=getattr(request.state, "correlation_id", None),
        tenant_id=str(principal.tenant_id),
        user_id=str(principal.user_id),
        actor_type=principal.actor_type,
    )
    request.state.principal = principal
    _assert_host_matches_tenant(request, principal)
    if "support" in principal.roles or principal.actor_type == "support":
        from application.support.service import assert_active_support_grant

        await assert_active_support_grant(principal)
    return principal


def _assert_host_matches_tenant(request: Request, principal: Principal) -> None:
    """`api.{slug}.airevenueos.io` must agree with the authenticated membership."""
    host = (request.headers.get("host") or "").split(":")[0]
    if not host.endswith("airevenueos.io"):
        return  # local and preview hosts are resolved by membership alone
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] == "api":
        slug = parts[1]
        if slug and principal.tenant_slug and slug != principal.tenant_slug:
            tenant_isolation_violations.labels(surface="host").inc()
            raise Forbidden("The requested host does not match your organisation.")


async def _is_revoked(request: Request, jti: str) -> bool:
    if not jti:
        return False
    try:
        from infrastructure.caching.redis import get_redis, global_key

        return bool(await get_redis().exists(global_key("revoked", jti)))
    except Exception:
        return False


CurrentPrincipal = Annotated[Principal, Depends(get_principal)]


def require_permission(resource: str, action: str):  # type: ignore[no-untyped-def]
    """Route dependency. Authorisation is checked before the use case runs."""

    async def _dependency(principal: CurrentPrincipal) -> Principal:
        principal.require(resource, action)
        return principal

    return _dependency


def require_step_up(operation: str):  # type: ignore[no-untyped-def]
    from datetime import datetime

    from infrastructure.auth.tokens import requires_step_up

    async def _dependency(principal: CurrentPrincipal) -> Principal:
        authenticated_at = datetime.fromtimestamp(principal.authenticated_at or 0, tz=UTC)
        if requires_step_up(
            operation, mfa_verified=principal.mfa_verified, authenticated_at=authenticated_at
        ):
            raise Forbidden(
                "This action requires re-authentication with multi-factor authentication.",
                details={"step_up_required": True, "operation": operation},
            )
        return principal

    return _dependency


def rate_limit(policy: str, *, per: str = "user"):  # type: ignore[no-untyped-def]
    async def _dependency(request: Request, principal: CurrentPrincipal) -> None:
        subject = {
            "user": str(principal.user_id),
            "tenant": str(principal.tenant_id),
            "ip": (request.client.host if request.client else "unknown"),
        }[per]
        decision = await RateLimiter().check(policy, subject)
        if not decision.allowed:
            raise RateLimited(
                "Too many requests.",
                details={
                    "policy": decision.policy,
                    "retry_after": decision.retry_after_seconds,
                },
            )

    return _dependency


async def public_rate_limit(request: Request, policy: str = "public_form_ip") -> None:
    subject = request.client.host if request.client else "unknown"
    decision = await RateLimiter().check(policy, subject)
    if not decision.allowed:
        raise RateLimited(
            "Too many requests.",
            details={"retry_after": decision.retry_after_seconds},
        )


@dataclass(slots=True)
class ListQuery:
    cursor: str | None = None
    page_size: int = 50
    sort: str | None = None
    fields: list[str] = field(default_factory=list)
    include: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)


async def list_query(
    cursor: str | None = None,
    page_size: int = 50,
    sort: str | None = None,
    fields: str | None = None,
    include: str | None = None,
) -> ListQuery:
    from shared.pagination import clamp_page_size

    return ListQuery(
        cursor=cursor,
        page_size=clamp_page_size(page_size),
        sort=sort,
        fields=[f.strip() for f in (fields or "").split(",") if f.strip()],
        include=[i.strip() for i in (include or "").split(",") if i.strip()],
    )
