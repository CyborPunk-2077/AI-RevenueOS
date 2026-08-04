"""Team membership: invitations issued, listed, revoked, and redeemed.

Two of these routes are unauthenticated by necessity - the recipient has no
account yet - so both are rate limited by IP and both refuse to distinguish
"wrong token" from "expired token" from "already used". A link that answers those
questions differently is an oracle for enumerating invitations.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status

from api.app.envelope import success
from api.app.settings import Settings
from api.deps.principal import CurrentPrincipal, get_app_settings
from api.v1.schemas import AcceptInvitationRequest, InviteUserRequest
from application.auth import invitations as service
from infrastructure.auth.passwords import hash_password, validate_password
from shared.exceptions import ValidationError

router = APIRouter(tags=["users"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", ""))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _reveal_tokens(settings: Settings) -> bool:
    """Local development surfaces the link because email delivery is gated off."""
    return settings.environment in ("local", "test")


async def _limit(bucket: str, key: str) -> None:
    from api.v1.auth import _limit as auth_limit

    await auth_limit(bucket, key)


@router.post(
    "/users/invitations",
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone to the organisation",
)
async def create_invitation(
    payload: InviteUserRequest,
    request: Request,
    principal: CurrentPrincipal,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, Any]:
    principal.require("user", "create")
    issued = await service.invite_user(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        actor_roles=principal.roles,
        email=payload.email,
        role=payload.role,
    )
    body: dict[str, Any] = {
        "id": str(issued.invitation_id),
        "email": issued.email,
        "role": issued.role.value,
        "expires_at": issued.expires_at.isoformat(),
        "status": "pending",
        # Delivery is an externally gated capability. Until a verified sender
        # domain exists (gate 1.4), nothing is sent and nothing pretends to be.
        "delivery": "not_sent",
    }
    if _reveal_tokens(settings):
        body["invitation_token"] = issued.token
    return success(body, request_id=_request_id(request))


@router.get("/users/invitations", summary="List invitations")
async def list_invitations(
    request: Request,
    principal: CurrentPrincipal,
    include_settled: Annotated[bool, Query(description="Include accepted and revoked")] = False,
) -> dict[str, Any]:
    principal.require("user", "read")
    rows = await service.list_invitations(
        tenant_id=principal.tenant_id, include_settled=include_settled
    )
    return success({"items": rows, "total": len(rows)}, request_id=_request_id(request))


@router.delete("/users/invitations/{invitation_id}", summary="Revoke an invitation")
async def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("user", "delete")
    result = await service.revoke_invitation(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        invitation_id=invitation_id,
    )
    return success(result, request_id=_request_id(request))


@router.get("/invitations/preview", summary="What an invitation link is for")
async def preview_invitation(
    request: Request, token: Annotated[str, Query(min_length=8)]
) -> dict[str, Any]:
    """Unauthenticated: the recipient has no account yet."""
    await _limit("login_ip", _client_ip(request))
    return success(await service.peek_invitation(token), request_id=_request_id(request))


@router.post(
    "/invitations/accept",
    status_code=status.HTTP_201_CREATED,
    summary="Redeem an invitation and create the account",
)
async def accept_invitation(
    payload: AcceptInvitationRequest,
    request: Request,
) -> dict[str, Any]:
    await _limit("login_ip", _client_ip(request))

    check = validate_password(payload.password, full_name=payload.full_name)
    if not check.ok:
        raise ValidationError(
            "That password is not acceptable.", details={"problems": check.problems}
        )

    result = await service.accept_invitation(
        token=payload.token,
        full_name=payload.full_name,
        password_hash=hash_password(payload.password),
    )
    # No session is issued here. The account is real and the address is proven, but
    # signing in goes through `/auth/login` so that MFA, session caps and the
    # step-up rules apply on the first session as they do on every other one.
    return success({**result, "sign_in_required": True}, request_id=_request_id(request))
