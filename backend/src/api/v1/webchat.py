"""Webchat: the tenant's widget settings, and the public surface the widget uses.

The public routes are unauthenticated because the caller is a stranger on
someone else's website. Three things stand in for a session: the public key
names the tenant, the `Origin` header decides whether that page may speak for
them, and the rate limiter caps how fast anyone may try. None of them produces a
`Principal`, and none of them can read across a tenant boundary.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request, status

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal, public_rate_limit
from api.v1.schemas import (
    WebchatMessageRequest,
    WebchatSessionRequest,
    WebchatWidgetRequest,
)
from application.communications import webchat

router = APIRouter(tags=["webchat"])


async def public_chat_limit(request: Request) -> None:
    """IP-keyed, on the `webchat_session_ip` policy rather than the form one."""
    await public_rate_limit(request, policy="webchat_session_ip")


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", ""))


def _origin(request: Request, origin_header: str | None) -> str:
    """`Origin` is set by the browser and cannot be forged by page script.

    Falling back to `Referer` would accept a header the page controls, which is
    the whole thing this check exists to prevent.
    """
    return origin_header or request.headers.get("origin") or ""


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


# ------------------------------------------------------------ tenant settings


@router.get("/webchat/widget", summary="Read the webchat widget configuration")
async def read_widget(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("channel", "read")
    widget = await webchat.get_widget(tenant_id=principal.tenant_id)
    return success({"widget": widget}, request_id=_request_id(request))


@router.put("/webchat/widget", summary="Create or update the widget")
async def configure_widget(
    payload: WebchatWidgetRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    # Configuring a channel is a settings change, not day-to-day CRM work.
    principal.require("channel", "configure")
    result = await webchat.configure_widget(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        allowed_origins=payload.allowed_origins,
        greeting=payload.greeting,
        consent_copy=payload.consent_copy,
        branding=payload.branding,
        handoff_enabled=payload.handoff_enabled,
        ai_suggestions_enabled=payload.ai_suggestions_enabled,
        is_active=payload.is_active,
    )
    return success(result, request_id=_request_id(request))


@router.post("/webchat/widget/rotate-key", summary="Issue a new public key")
async def rotate_key(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("channel", "configure")
    result = await webchat.rotate_public_key(
        tenant_id=principal.tenant_id, actor_id=principal.user_id
    )
    return success(result, request_id=_request_id(request))


# -------------------------------------------------------------- public surface

public_router = APIRouter(prefix="/public/webchat", tags=["webchat-public"])


@public_router.get(
    "/config", summary="Widget configuration", dependencies=[Depends(public_chat_limit)]
)
async def public_config(
    request: Request,
    public_key: str,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict[str, Any]:
    result = await webchat.widget_config(public_key=public_key, origin=_origin(request, origin))
    return success(result, request_id=_request_id(request))


@public_router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    summary="Start a visitor session",
    dependencies=[Depends(public_chat_limit)],
)
async def start_session(
    payload: WebchatSessionRequest,
    request: Request,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict[str, Any]:
    opened = await webchat.start_session(
        public_key=payload.public_key,
        origin=_origin(request, origin),
        visitor_ref=payload.visitor_ref,
        consent_granted=payload.consent_granted,
        ip=_client_ip(request),
    )
    return success(
        {
            "session_token": opened.token,
            "conversation_id": str(opened.conversation_id),
            "greeting": opened.greeting,
            "consent_copy": opened.consent_copy,
            "handoff_enabled": opened.handoff_enabled,
        },
        request_id=_request_id(request),
    )


@public_router.post(
    "/messages",
    status_code=status.HTTP_201_CREATED,
    summary="Send a visitor message",
    dependencies=[Depends(public_chat_limit)],
)
async def post_message(
    payload: WebchatMessageRequest,
    request: Request,
    origin: Annotated[str | None, Header(alias="Origin")] = None,
) -> dict[str, Any]:
    result = await webchat.post_visitor_message(
        token=payload.session_token, body=payload.body, origin=_origin(request, origin)
    )
    return success(result, request_id=_request_id(request))


@public_router.get(
    "/transcript",
    summary="The visitor's own transcript",
    dependencies=[Depends(public_chat_limit)],
)
async def transcript(request: Request, session_token: str) -> dict[str, Any]:
    result = await webchat.visitor_transcript(token=session_token)
    return success(result, request_id=_request_id(request))


@public_router.post(
    "/sessions/end", summary="End a visitor session", dependencies=[Depends(public_chat_limit)]
)
async def end_session(payload: WebchatMessageRequest, request: Request) -> dict[str, Any]:
    result = await webchat.end_session(token=payload.session_token)
    return success(result, request_id=_request_id(request))
