"""Capture form builder. The public submission surface lives in `public.py`."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Request, status

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from api.v1.schemas import FormCreateRequest, FormUpdateRequest
from application.leads import form_builder

router = APIRouter(tags=["forms"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", ""))


@router.get("/forms", summary="List capture forms")
async def list_forms(
    request: Request,
    principal: CurrentPrincipal,
    include_archived: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    principal.require("form", "read")
    rows = await form_builder.list_forms(
        tenant_id=principal.tenant_id, include_archived=include_archived
    )
    return success({"items": rows, "total": len(rows)}, request_id=_request_id(request))


@router.post("/forms", status_code=status.HTTP_201_CREATED, summary="Create a draft form")
async def create_form(
    payload: FormCreateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("form", "create")
    result = await form_builder.create_form(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        name=payload.name,
        form_type=payload.type,
        schema=payload.schema_,
        allowed_origins=payload.allowed_origins,
        source=payload.source,
        settings=payload.settings,
    )
    return success(result, request_id=_request_id(request))


@router.get("/forms/{form_id}", summary="Read a form")
async def read_form(
    form_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("form", "read")
    result = await form_builder.get_form(tenant_id=principal.tenant_id, form_id=form_id)
    return success(result, request_id=_request_id(request))


@router.patch("/forms/{form_id}", summary="Edit the draft")
async def update_form(
    form_id: UUID,
    payload: FormUpdateRequest,
    request: Request,
    principal: CurrentPrincipal,
    if_match: Annotated[int | None, Query(alias="version")] = None,
) -> dict[str, Any]:
    principal.require("form", "update")
    result = await form_builder.update_form(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        form_id=form_id,
        expected_version=if_match,
        name=payload.name,
        schema=payload.schema_,
        allowed_origins=payload.allowed_origins,
        settings=payload.settings,
        source=payload.source,
    )
    return success(result, request_id=_request_id(request))


@router.post("/forms/{form_id}/publish", summary="Publish the current draft")
async def publish_form(
    form_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    # Publishing puts a write surface on the open internet, so it is a separate
    # permission from editing a draft.
    principal.require("form", "publish")
    result = await form_builder.publish_form(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, form_id=form_id
    )
    return success(result, request_id=_request_id(request))


@router.post("/forms/{form_id}/unpublish", summary="Take the form offline")
async def unpublish_form(
    form_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("form", "publish")
    result = await form_builder.unpublish_form(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, form_id=form_id
    )
    return success(result, request_id=_request_id(request))


@router.delete("/forms/{form_id}", summary="Archive a form")
async def archive_form(
    form_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("form", "delete")
    result = await form_builder.archive_form(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, form_id=form_id
    )
    return success(result, request_id=_request_id(request))
