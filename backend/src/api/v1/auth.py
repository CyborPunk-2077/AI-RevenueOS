"""Authentication endpoints for the demo vertical slice.

Deliberately narrow: login, refresh, me, logout. Signup, MFA, Google OAuth,
password reset, API keys and session management are P0-2.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal, get_token_service
from api.v1.schemas import LoginRequest, RefreshRequest
from application.auth import service as auth_service
from infrastructure.auth.tokens import TokenService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", summary="Exchange credentials for a session")
async def login(
    payload: LoginRequest,
    request: Request,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> dict[str, Any]:
    """The browser never sees these tokens: the Next.js BFF stores the refresh
    token in a host-only, Secure, HttpOnly cookie and keeps the access token
    server side."""
    result = await auth_service.login(payload.email, payload.password, tokens)
    return success(
        {
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
            "user": result.user,
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/refresh", summary="Rotate a refresh token")
async def refresh(
    payload: RefreshRequest,
    request: Request,
    tokens: Annotated[TokenService, Depends(get_token_service)],
) -> dict[str, Any]:
    result = await auth_service.refresh(payload.refresh_token, tokens)
    return success(
        {
            "access_token": result.access_token,
            "refresh_token": result.refresh_token,
            "expires_in": result.expires_in,
            "user": result.user,
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/logout", summary="Revoke the current session family")
async def logout(payload: RefreshRequest, request: Request) -> dict[str, Any]:
    await auth_service.logout(payload.refresh_token)
    return success({"signed_out": True}, request_id=getattr(request.state, "correlation_id", None))


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
        },
        request_id=getattr(request.state, "correlation_id", None),
    )
