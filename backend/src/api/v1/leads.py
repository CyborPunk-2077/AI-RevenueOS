"""Lead endpoints: capture, dedupe, qualification and human review."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status

from api.app.envelope import success
from api.deps.idempotency import IdempotencyContext, idempotency, parse_if_match
from api.deps.principal import CurrentPrincipal, ListQuery, list_query, rate_limit
from api.v1.schemas import LeadCreate, LeadQualifyRequest, LeadReviewRequest, LeadUpdate
from domain.leads.lifecycle import (
    duplicate_resolution,
)

router = APIRouter(prefix="/leads", tags=["leads"])

# In the deployed system these calls go through the application service and repository.
# The route layer stays free of ORM access and provider calls by design.


@router.get("", summary="List leads")
async def list_leads(
    request: Request,
    principal: CurrentPrincipal,
    query: Annotated[ListQuery, Depends(list_query)],
) -> dict[str, Any]:
    principal.require("lead", "list")
    from application.leads.service import LeadService

    page = await LeadService.for_principal(principal).list_leads(query)
    return success(
        {"leads": page.items},
        pagination=page.meta(),
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("", status_code=status.HTTP_201_CREATED, summary="Create a lead")
async def create_lead(
    payload: LeadCreate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    principal.require("lead", "create")
    from application.leads.service import LeadService

    result = await LeadService.for_principal(principal).capture(
        payload.model_dump(), idempotency=idem
    )
    response.headers["ETag"] = f'W/"{result["version"]}"'
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.get("/{lead_id}", summary="Read a lead")
async def read_lead(
    lead_id: UUID, request: Request, response: Response, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "read")
    from application.leads.service import LeadService

    lead = await LeadService.for_principal(principal).get(lead_id)
    response.headers["ETag"] = f'W/"{lead["version"]}"'
    return success(lead, request_id=getattr(request.state, "correlation_id", None))


@router.patch("/{lead_id}", summary="Update a lead")
async def update_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    request: Request,
    response: Response,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Depends(parse_if_match)] = None,
) -> dict[str, Any]:
    principal.require("lead", "update")
    from application.leads.service import LeadService

    lead = await LeadService.for_principal(principal).update(
        lead_id, payload.model_dump(exclude_unset=True), expected_version=if_match
    )
    response.headers["ETag"] = f'W/"{lead["version"]}"'
    return success(lead, request_id=getattr(request.state, "correlation_id", None))


@router.get("/{lead_id}/duplicates", summary="List duplicate candidates")
async def lead_duplicates(
    lead_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "read")
    from application.leads.service import LeadService

    candidates = await LeadService.for_principal(principal).duplicates(lead_id)
    return success(
        {"candidates": candidates, "resolution": duplicate_resolution([])},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post(
    "/{lead_id}/qualify",
    summary="Qualify a lead",
    dependencies=[Depends(rate_limit("ai_qualify_tenant", per="tenant"))],
)
async def qualify_lead(
    lead_id: UUID,
    payload: LeadQualifyRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """AI proposes; a human accepts, edits, rejects or defers. Failure degrades safely."""
    principal.require("lead", "update")
    from application.leads.service import LeadService

    result = await LeadService.for_principal(principal).qualify(
        lead_id, mode=payload.mode, manual_score=payload.manual_score, notes=payload.notes
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/qualification/review", summary="Record a human qualification decision")
async def review_qualification(
    lead_id: UUID,
    payload: LeadReviewRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("lead", "update")
    from application.leads.service import LeadService

    result = await LeadService.for_principal(principal).review_qualification(
        lead_id, decision=payload.decision, edited_score=payload.edited_score, note=payload.note
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/convert", summary="Convert a lead to a contact and opportunity")
async def convert_lead(
    lead_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "update")
    principal.require("contact", "create")
    from application.leads.service import LeadService

    result = await LeadService.for_principal(principal).convert(lead_id)
    return success(result, request_id=getattr(request.state, "correlation_id", None))
