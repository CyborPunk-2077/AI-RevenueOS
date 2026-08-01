"""Google sign-in.

Gated like every other external capability: without a client id and secret,
`is_configured()` is False and the routes report the feature as unavailable rather
than pretending. No fallback, no stub success.

The state parameter is single use, and that is enforced by `GETDEL` — one atomic
round trip that returns the value and removes it. A read-then-delete pair would
leave a window in which two concurrent callbacks both validate, which is precisely
the CSRF/replay hole state is meant to close.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import select

from infrastructure.caching.redis import get_redis, global_key
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.models.users import GoogleIdentity, User
from infrastructure.database.session import platform_session, tenant_session
from infrastructure.logging.setup import get_logger
from shared.exceptions import FeatureNotAvailable, Unauthenticated
from shared.settings import Settings, get_settings
from shared.utils.text import normalize_email
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth.oauth")

AUTHORIZE_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
STATE_TTL_SECONDS = 600
SCOPES = ("openid", "email", "profile")


def is_configured(cfg: Settings | None = None) -> bool:
    settings = cfg or get_settings()
    return bool(settings.google_client_id and settings.google_client_secret)


def _require_configured(cfg: Settings | None = None) -> Settings:
    settings = cfg or get_settings()
    if not is_configured(settings):
        raise FeatureNotAvailable(
            "Google sign-in is not configured.",
            details={"capability": "google_oauth", "reason": "missing client credentials"},
        )
    return settings


@dataclass(frozen=True, slots=True)
class AuthorizeRedirect:
    url: str
    state: str


async def begin(*, redirect_to: str = "/", cfg: Settings | None = None) -> AuthorizeRedirect:
    """Mint state, park it in Redis with a TTL, and build the consent URL."""
    settings = _require_configured(cfg)
    state = secrets.token_urlsafe(32)
    payload = json.dumps({"redirect_to": redirect_to, "issued_at": utcnow().isoformat()})
    await get_redis().set(global_key("oauth_state", state), payload, ex=STATE_TTL_SECONDS)

    query = urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
        }
    )
    return AuthorizeRedirect(url=f"{AUTHORIZE_ENDPOINT}?{query}", state=state)


async def consume_state(state: str) -> dict[str, Any]:
    """Redeem the state exactly once, atomically.

    Returns the stored payload. A second call with the same value fails, which is
    what makes a replayed callback useless.
    """
    if not state:
        raise Unauthenticated("The sign-in request is invalid. Start again.")
    key = global_key("oauth_state", state)
    redis = get_redis()
    try:
        raw = await redis.getdel(key)
    except AttributeError:  # pragma: no cover - very old redis-py
        # Fall back to a Lua compare-and-delete rather than a racy GET then DEL.
        raw = await redis.eval(
            "local v = redis.call('GET', KEYS[1]); redis.call('DEL', KEYS[1]); return v", 1, key
        )
    if not raw:
        logger.warning("auth_oauth_state_rejected")
        raise Unauthenticated("The sign-in request has expired or was already used.")
    try:
        return dict(json.loads(raw))
    except (TypeError, ValueError):
        return {}


async def exchange_code(code: str, cfg: Settings | None = None) -> dict[str, Any]:
    """Trade the authorization code for tokens and the verified profile."""
    settings = _require_configured(cfg)
    import httpx

    async with httpx.AsyncClient(timeout=10.0) as client:
        token_response = await client.post(
            TOKEN_ENDPOINT,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": settings.google_redirect_uri,
                "grant_type": "authorization_code",
            },
        )
        if token_response.status_code != 200:
            logger.warning("auth_oauth_token_exchange_failed", status=token_response.status_code)
            raise Unauthenticated("Google sign-in failed.")
        tokens = token_response.json()

        profile_response = await client.get(
            USERINFO_ENDPOINT, headers={"Authorization": f"Bearer {tokens.get('access_token', '')}"}
        )
        if profile_response.status_code != 200:
            raise Unauthenticated("Google sign-in failed.")
        profile = profile_response.json()

    if not profile.get("email_verified"):
        # An unverified Google address would let anyone who can register that
        # address elsewhere claim a matching account.
        raise Unauthenticated("Your Google account does not have a verified email address.")
    return {"tokens": tokens, "profile": profile}


async def resolve_user(profile: dict[str, Any]) -> tuple[Any, Any]:
    """Map a Google profile onto an existing user. Never creates one.

    Self-serve tenant creation goes through `signup`. Auto-provisioning here would
    let anyone with a Google account materialise a tenant by visiting a callback
    URL, so an unrecognised address is refused.
    """
    email = normalize_email(str(profile.get("email", "")))
    google_sub = str(profile.get("sub", ""))

    async with platform_session("oauth: resolve google identity") as session:
        user = (
            await session.execute(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if user is None or user.status != "active":
            logger.info("auth_oauth_unknown_account")
            raise Unauthenticated("No active account matches that Google address.")
        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == user.tenant_id))
        ).scalar_one()
        user_id, tenant_id = user.id, user.tenant_id

    async with tenant_session(tenant_id) as session:
        identity = (
            await session.execute(select(GoogleIdentity).where(GoogleIdentity.user_id == user_id))
        ).scalar_one_or_none()
        if identity is None:
            session.add(
                GoogleIdentity(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    google_sub=google_sub,
                    email=email,
                    scopes=list(SCOPES),
                )
            )
        elif identity.google_sub != google_sub:
            # The address matches but the Google account behind it changed.
            raise Unauthenticated("This address is linked to a different Google account.")

    logger.info("auth_oauth_login", user_id=str(user_id), tenant_id=str(tenant_id))
    return user_id, tenant
