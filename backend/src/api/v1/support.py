"""Tenant-controlled support access approvals."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from api.app.envelope import success
from api.deps.idempotency import IdempotencyContext, idempotency
from api.deps.principal import CurrentPrincipal, require_step_up
from api.v1.schemas import SupportAccessRequest

router = APIRouter(prefix="/support-access", tags=["support-access"])


@router.get("", summary="List tenant support access grants")
async def list_grants(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    from application.support.service import list_support_access

    grants = await list_support_access(principal)
    return success(
        {"grants": grants, "write_access_available": False},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Approve time-bound support access")
async def grant_access(
    payload: SupportAccessRequest,
    request: Request,
    principal: Annotated[Any, Depends(require_step_up("support_access.approve"))],
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.support.service import grant_support_access

    grant = await grant_support_access(
        principal,
        support_user_ref=payload.support_user_ref,
        purpose=payload.purpose,
        duration_minutes=payload.duration_minutes,
        idempotency_key=idem.key,
    )
    return success(grant, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{grant_id}/revoke", summary="Revoke support access immediately")
async def revoke_access(
    grant_id: UUID,
    request: Request,
    principal: Annotated[Any, Depends(require_step_up("support_access.approve"))],
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.support.service import revoke_support_access

    grant = await revoke_support_access(principal, grant_id=grant_id, idempotency_key=idem.key)
    return success(grant, request_id=getattr(request.state, "correlation_id", None))
