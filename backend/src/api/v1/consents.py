"""Tenant-scoped immutable consent ledger."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from api.v1.schemas import ConsentGrantRequest, ConsentWithdrawRequest

router = APIRouter(prefix="/consents", tags=["consent"])


@router.get("", summary="List consent evidence")
async def list_consents(
    request: Request,
    principal: CurrentPrincipal,
    subject_type: Annotated[str | None, Query(max_length=30)] = None,
    subject_id: UUID | None = None,
) -> dict[str, Any]:
    principal.require("consent", "read")
    from application.communications.consents import ConsentService

    rows = await ConsentService.for_principal(principal).list_records(
        subject_type=subject_type, subject_id=subject_id
    )
    return success(rows, request_id=getattr(request.state, "correlation_id", None))


@router.post("", status_code=status.HTTP_201_CREATED, summary="Record a consent grant")
async def grant_consent(
    payload: ConsentGrantRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("consent", "create")
    from application.communications.consents import ConsentService

    row = await ConsentService.for_principal(principal).grant(**payload.model_dump())
    return success(row, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{consent_id}/withdraw", summary="Withdraw a consent grant")
async def withdraw_consent(
    consent_id: UUID,
    payload: ConsentWithdrawRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("consent", "update")
    from application.communications.consents import ConsentService

    row = await ConsentService.for_principal(principal).withdraw(consent_id, reason=payload.reason)
    return success(row, request_id=getattr(request.state, "correlation_id", None))
