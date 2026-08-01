"""Public, unauthenticated surface. Constrained tokens, strict origins, hard limits."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status

from api.app.envelope import success
from api.deps.principal import public_rate_limit
from api.v1.schemas import PublicFormSubmission
from shared.exceptions import NotFound

router = APIRouter(prefix="/public", tags=["public"])


@router.get("/forms/{form_id}/config", summary="Published form configuration")
async def form_config(form_id: UUID, request: Request) -> dict[str, Any]:
    from application.leads.forms import get_published_form

    form = await get_published_form(form_id)
    if form is None:
        raise NotFound("Form not found.")
    return success(form, request_id=getattr(request.state, "correlation_id", None))


@router.post(
    "/forms/{form_id}/submit",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a published form",
    dependencies=[Depends(public_rate_limit)],
)
async def submit_form(
    form_id: UUID, payload: PublicFormSubmission, request: Request
) -> dict[str, Any]:
    """The raw source event is always preserved, even when the lead is a duplicate."""
    from application.leads.forms import submit_public_form

    origin = request.headers.get("origin", "")
    result = await submit_public_form(
        form_id=form_id,
        payload=payload.model_dump(),
        origin=origin,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return success(
        {"accepted": True, "source_event_id": result["source_event_id"]},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/knowledge/articles", summary="List published knowledge articles")
async def knowledge_articles(request: Request, tenant_slug: str) -> dict[str, Any]:
    from application.documents.knowledge import list_public_articles

    return success(
        {"articles": await list_public_articles(tenant_slug)},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post(
    "/booking/appointments",
    status_code=status.HTTP_201_CREATED,
    summary="Public appointment booking",
    dependencies=[Depends(public_rate_limit)],
)
async def public_booking(request: Request) -> dict[str, Any]:
    """Slot claims are protected by a database unique constraint; a taken slot is 409."""
    from application.appointments.booking import claim_public_slot

    body = await request.json()
    result = await claim_public_slot(body, idempotency_key=request.headers.get("Idempotency-Key"))
    return success(result, request_id=getattr(request.state, "correlation_id", None))
