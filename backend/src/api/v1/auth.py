"""The `/v1/auth` surface.

Thin by design: parse, authorise, delegate, envelope. Every decision that matters
-- password policy, lockout, rotation, revocation, single-use tokens -- lives in
`application.auth.*` and its primitives, which were already built and tested.

Two conventions run through the whole module:

* Unauthenticated routes are rate limited by IP *and* by account where an account
  can be named, and they do not vary their response on whether an address exists.
* Nothing that could be replayed is ever returned twice. Recovery codes, API keys
  and the MFA secret appear in exactly one response and are unreadable afterwards.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status

from api.app.envelope import success
from api.deps.principal import (
    CurrentPrincipal,
    get_app_settings,
    get_token_service,
    require_step_up,
)
from api.v1.schemas import (
    ApiKeyCreateRequest,
    ForgotPasswordRequest,
    LoginRequest,
    MfaDisableRequest,
    MfaRecoveryRequest,
    MfaSetupConfirmRequest,
    MfaVerifyRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    VerifyEmailRequest,
)
from application.auth import api_keys as api_key_service
from application.auth import mfa as mfa_service
from application.auth import oauth as oauth_service
from application.auth import registration
from application.auth import service as auth_service
from application.auth import sessions as session_service
from infrastructure.auth.tokens import TokenService
from infrastructure.caching.rate_limit import RateLimiter
from infrastructure.logging.setup import get_logger
from shared.exceptions import RateLimited, Unauthenticated, ValidationError
from shared.settings import Settings

router = APIRouter(prefix="/auth", tags=["auth"])
logger = get_logger("api.auth")


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


async def _limit(policy: str, subject: str) -> None:
    """Rate limit a route that has no authenticated principal to key on."""
    decision = await RateLimiter().check(policy, subject)
    if not decision.allowed:
        raise RateLimited(
            "Too many attempts. Please wait before trying again.",
            details={"policy": decision.policy, "retry_after": decision.retry_after_seconds},
        )


def _session_payload(result: auth_service.AuthResult) -> dict[str, Any]:
    return {
        "access_token": result.access_token,
        "refresh_token": result.refresh_token,
        "expires_in": result.expires_in,
        "user": result.user,
    }


def _reveal_tokens(settings: Settings) -> bool:
    """Whether a token that would normally be emailed may be returned in JSON.

    Email delivery is an externally gated capability that is off by default, so
    without this a local operator could never complete sign-up or reset a
    password. It is restricted to `local` AND to email being unconfigured, so
    there is no deployed environment in which it can weaken anything.
    """
    return settings.environment == "local" and not settings.features.email_enabled


# --- password sign-in -------------------------------------------------------


@router.post("/signup", status_code=status.HTTP_201_CREATED, summary="Create an organisation")
async def signup(
    payload: SignupRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, Any]:
    await _limit("login_ip", _client_ip(request))
    result = await registration.signup(
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        organisation=payload.organisation,
    )
    body: dict[str, Any] = {
        "user_id": str(result.user_id),
        "tenant_id": str(result.tenant_id),
        "tenant_slug": result.tenant_slug,
        "email": result.email,
        # No session is issued: the address is unconfirmed, so there is nothing to
        # sign in to yet. That is what stops sign-up being a takeover primitive.
        "verification_required": True,
    }
    if _reveal_tokens(settings):
        body["verification_token"] = result.verification_token
    return success(body, request_id=_request_id(request))


@router.post("/login", summary="Exchange credentials for a session")
async def login(
    payload: LoginRequest,
    request: Request,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> dict[str, Any]:
    """The browser never sees these tokens: the Next.js BFF stores the refresh
    token in a host-only, Secure, HttpOnly cookie and keeps the access token
    server side."""
    await _limit("login_ip", _client_ip(request))
    await _limit("login_account", payload.email)
    try:
        result = await auth_service.login(payload.email, payload.password, tokens)
    except auth_service.MfaRequired as challenge:
        # 200, not 401: the credential was accepted. A second step is outstanding
        # and no session exists until it completes.
        return success(
            {"mfa_required": True, "mfa_token": challenge.challenge_token},
            request_id=_request_id(request),
        )
    return success(_session_payload(result), request_id=_request_id(request))


@router.post("/refresh", summary="Rotate a refresh token")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> dict[str, Any]:
    await _limit("refresh_user", _client_ip(request))
    result = await auth_service.refresh(payload.refresh_token, tokens)
    return success(_session_payload(result), request_id=_request_id(request))


@router.post("/logout", summary="Revoke the current session family")
async def logout(payload: RefreshRequest, request: Request) -> dict[str, Any]:
    await auth_service.logout(payload.refresh_token)
    return success({"signed_out": True}, request_id=_request_id(request))


@router.post("/logout-all", summary="Revoke every session for the current user")
async def logout_all(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    result = await session_service.revoke_all(
        tenant_id=principal.tenant_id, user_id=principal.user_id
    )
    return success(result, request_id=_request_id(request))


# --- account recovery -------------------------------------------------------


@router.post("/forgot-password", summary="Request a password reset link")
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, Any]:
    await _limit("password_reset_email", payload.email.lower())
    await _limit("login_ip", _client_ip(request))
    token = await registration.forgot_password(payload.email)

    # The body is identical whether or not the address exists: this endpoint must
    # not be usable to enumerate accounts.
    body: dict[str, Any] = {"requested": True}
    if token and _reveal_tokens(settings):
        body["reset_token"] = token
    return success(body, request_id=_request_id(request))


@router.post("/reset-password", summary="Set a new password using a reset link")
async def reset_password(payload: ResetPasswordRequest, request: Request) -> dict[str, Any]:
    await _limit("login_ip", _client_ip(request))
    result = await registration.reset_password(payload.token, payload.password)
    return success(result, request_id=_request_id(request))


@router.post("/verify-email", summary="Confirm an email address")
async def verify_email(payload: VerifyEmailRequest, request: Request) -> dict[str, Any]:
    await _limit("login_ip", _client_ip(request))
    result = await registration.verify_email(payload.token)
    return success(result, request_id=_request_id(request))


# --- multi-factor authentication -------------------------------------------


@router.post("/mfa/setup", summary="Begin authenticator enrolment")
async def mfa_setup(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    await _limit("mfa_user", str(principal.user_id))
    challenge = await mfa_service.start_enrolment(
        tenant_id=principal.tenant_id, user_id=principal.user_id, email=principal.email
    )
    return success(
        {
            "secret": challenge.secret,
            "otpauth_url": challenge.provisioning_uri,
            "pending": challenge.pending,
        },
        request_id=_request_id(request),
    )


@router.post("/mfa/setup/confirm", summary="Commit authenticator enrolment")
async def mfa_setup_confirm(
    payload: MfaSetupConfirmRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _limit("mfa_user", str(principal.user_id))
    result = await mfa_service.complete_enrolment(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        pending=payload.pending,
        code=payload.code,
    )
    return success(result, request_id=_request_id(request))


@router.post("/mfa/verify", summary="Complete a sign-in challenge, or step up in place")
async def mfa_verify(
    payload: MfaVerifyRequest,
    request: Request,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> dict[str, Any]:
    if payload.mfa_token:
        tenant_id, user_id = await auth_service.consume_mfa_challenge(payload.mfa_token)
        await _limit("mfa_user", str(user_id))
        accepted = await mfa_service.check_code(
            tenant_id=tenant_id, user_id=user_id, code=payload.code
        ) or await mfa_service.consume_recovery_code(
            tenant_id=tenant_id, user_id=user_id, code=payload.code
        )
        if not accepted:
            logger.warning("auth_mfa_failed", user_id=str(user_id))
            raise Unauthenticated("That code is not valid.")

        tenant, roles, email, name = await auth_service.load_principal(tenant_id, user_id)
        result = await auth_service.issue_session(
            user_id=user_id,
            tenant=tenant,
            roles=roles,
            email=email,
            name=name,
            tokens=tokens,
            mfa_verified=True,
        )
        return success(_session_payload(result), request_id=_request_id(request))

    # No challenge token: this is an in-place step-up, so a live session is
    # required. The principal is resolved here rather than as a route dependency
    # so that one path can serve both modes.
    from api.deps.principal import get_principal

    principal = await get_principal(
        request, tokens, authorization=request.headers.get("authorization")
    )
    await _limit("mfa_user", str(principal.user_id))
    if not await mfa_service.check_code(
        tenant_id=principal.tenant_id, user_id=principal.user_id, code=payload.code
    ):
        raise Unauthenticated("That code is not valid.")

    tenant, roles, email, name = await auth_service.load_principal(
        principal.tenant_id, principal.user_id
    )
    result = await auth_service.issue_session(
        user_id=principal.user_id,
        tenant=tenant,
        roles=roles,
        email=email,
        name=name,
        tokens=tokens,
        mfa_verified=True,
    )
    return success(_session_payload(result), request_id=_request_id(request))


@router.post("/mfa/recovery", summary="Regenerate recovery codes")
async def mfa_recovery(
    payload: MfaRecoveryRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _limit("mfa_user", str(principal.user_id))
    result = await mfa_service.regenerate_recovery_codes(
        tenant_id=principal.tenant_id, user_id=principal.user_id, code=payload.code
    )
    return success(result, request_id=_request_id(request))


@router.post("/mfa/disable", summary="Turn off multi-factor authentication")
async def mfa_disable(
    payload: MfaDisableRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    await _limit("mfa_user", str(principal.user_id))
    result = await mfa_service.disable(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        password=payload.password,
        code=payload.code,
    )
    return success(result, request_id=_request_id(request))


# --- identity and sessions --------------------------------------------------


@router.get("/me", summary="The authenticated principal")
async def me(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    return success(
        {
            "id": str(principal.user_id),
            "email": principal.email,
            "name": principal.name,
            "tenant_id": str(principal.tenant_id),
            "tenant_slug": principal.tenant_slug,
            "roles": list(principal.roles),
            "scope": principal.scope.value,
            "permissions": sorted(principal.permissions),
            "mfa_verified": principal.mfa_verified,
        },
        request_id=_request_id(request),
    )


@router.get("/sessions", summary="List the current user's active sessions")
async def list_sessions(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    items = await session_service.list_sessions(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        current_family=principal.session_id,
    )
    return success({"sessions": items}, request_id=_request_id(request))


@router.delete("/sessions/{session_id}", summary="Revoke one session")
async def revoke_session(
    session_id: str, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    result = await session_service.revoke_session(
        tenant_id=principal.tenant_id, user_id=principal.user_id, family_id=session_id
    )
    return success(result, request_id=_request_id(request))


# --- Google sign-in ---------------------------------------------------------


@router.get("/google/authorize", summary="Begin Google sign-in")
async def google_authorize(
    request: Request,
    settings: Annotated[Settings, Depends(get_app_settings)],
    redirect_to: Annotated[str, Query(max_length=500)] = "/",
) -> dict[str, Any]:
    await _limit("google_ip", _client_ip(request))
    # Relative paths only. An absolute URL here would make this an open redirect.
    target = (
        redirect_to if redirect_to.startswith("/") and not redirect_to.startswith("//") else "/"
    )
    began = await oauth_service.begin(redirect_to=target, cfg=settings)
    return success(
        {"authorize_url": began.url, "state": began.state}, request_id=_request_id(request)
    )


@router.get("/google/callback", summary="Complete Google sign-in")
async def google_callback(
    request: Request,
    response: Response,
    tokens: Annotated[TokenService, Depends(get_token_service)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=512)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> dict[str, Any]:
    await _limit("google_ip", _client_ip(request))
    if error:
        raise Unauthenticated("Google sign-in was cancelled.")
    if not code:
        raise ValidationError("The sign-in response is missing its authorization code.")

    # Consumed first and unconditionally: a replayed callback must fail before any
    # token exchange is attempted.
    stored = await oauth_service.consume_state(state or "")
    exchanged = await oauth_service.exchange_code(code, cfg=settings)
    user_id, tenant = await oauth_service.resolve_user(exchanged["profile"])
    _, roles, email, name = await auth_service.load_principal(tenant.id, user_id)

    result = await auth_service.issue_session(
        user_id=user_id, tenant=tenant, roles=roles, email=email, name=name, tokens=tokens
    )
    response.headers["Cache-Control"] = "no-store"
    return success(
        {**_session_payload(result), "redirect_to": stored.get("redirect_to", "/")},
        request_id=_request_id(request),
    )


# --- developer API keys -----------------------------------------------------


@router.post(
    "/api-keys",
    status_code=status.HTTP_201_CREATED,
    summary="Mint an API key (shown once)",
    dependencies=[Depends(require_step_up("api_key.create"))],
)
async def create_api_key(
    payload: ApiKeyCreateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("api_key", "create")
    result = await api_key_service.create(
        tenant_id=principal.tenant_id,
        user_id=principal.user_id,
        name=payload.name,
        scopes=payload.scopes,
        granted_permissions=principal.permissions,
    )
    return success(result, request_id=_request_id(request))


@router.get("/api-keys", summary="List API keys (values are masked)")
async def list_api_keys(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("api_key", "read")
    items = await api_key_service.list_keys(tenant_id=principal.tenant_id)
    return success({"api_keys": items}, request_id=_request_id(request))


@router.delete("/api-keys/{key_id}", summary="Revoke an API key")
async def delete_api_key(
    key_id: str, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("api_key", "delete")
    result = await api_key_service.revoke(tenant_id=principal.tenant_id, key_id=key_id)
    return success(result, request_id=_request_id(request))
