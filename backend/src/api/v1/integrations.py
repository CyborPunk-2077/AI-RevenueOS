"""Provider configuration requests; no route claims external activation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from api.v1.schemas import ProviderConfigurationRequest

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("", summary="List truthful provider configuration readiness")
async def list_integrations(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    from application.integrations.service import list_configurations

    return success(
        await list_configurations(principal),
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.put("/channels/{channel_type}", summary="Store an encrypted channel configuration")
async def put_channel(
    channel_type: str,
    payload: ProviderConfigurationRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    from application.integrations.service import configure_channel

    return success(
        await configure_channel(principal, channel_type, payload.model_dump()),
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.put("/{provider}", summary="Store an encrypted integration configuration")
async def put_integration(
    provider: str,
    payload: ProviderConfigurationRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    from application.integrations.service import configure_integration

    return success(
        await configure_integration(principal, provider, payload.model_dump()),
        request_id=getattr(request.state, "correlation_id", None),
    )
