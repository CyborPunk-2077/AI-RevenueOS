"""CSV import and assignment rules."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile, status

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from api.v1.schemas import (
    AssignmentRuleCreateRequest,
    AssignmentRuleUpdateRequest,
    ReorderRulesRequest,
)
from application.leads import assignment_rules, importer
from shared.exceptions import ValidationError

router = APIRouter(tags=["imports"])


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "correlation_id", ""))


def _mapping(raw: str | None) -> dict[str, str | None] | None:
    if not raw:
        return None
    import json

    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise ValidationError("`mapping` must be JSON.") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("`mapping` must be a JSON object of column to field.")
    return {str(k): (str(v) if v is not None else None) for k, v in parsed.items()}


@router.get("/imports/leads/template", summary="Download the prospect import template")
async def lead_import_template(principal: CurrentPrincipal) -> Response:
    """A three-row example sheet using the founders' own column names."""
    principal.require("import", "create")
    return Response(
        content=importer.build_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="sangam-prospect-template.csv"'},
    )


@router.post("/imports/leads/preview", summary="Judge a CSV without importing it")
async def preview_lead_import(
    request: Request,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    mapping: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    principal.require("import", "create")
    result = await importer.preview_import(
        tenant_id=principal.tenant_id, content=await file.read(), mapping=_mapping(mapping)
    )
    return success(result, request_id=_request_id(request))


@router.post(
    "/imports/leads",
    status_code=status.HTTP_201_CREATED,
    summary="Commit a CSV import",
)
async def commit_lead_import(
    request: Request,
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
    import_key: Annotated[str, Form(min_length=8, max_length=120)],
    mapping: Annotated[str | None, Form()] = None,
    assign: Annotated[bool, Form()] = True,
) -> dict[str, Any]:
    principal.require("import", "create")
    result = await importer.commit_import(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        content=await file.read(),
        mapping=_mapping(mapping),
        import_key=import_key,
        assign=assign,
    )
    return success(result, request_id=_request_id(request))


@router.get("/assignment-rules", summary="List assignment rules in priority order")
async def list_rules(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("lead", "read")
    rows = await assignment_rules.list_rules(tenant_id=principal.tenant_id)
    return success({"items": rows, "total": len(rows)}, request_id=_request_id(request))


@router.post("/assignment-rules", status_code=status.HTTP_201_CREATED, summary="Create a rule")
async def create_rule(
    payload: AssignmentRuleCreateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "assign")
    result = await assignment_rules.create_rule(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        name=payload.name,
        strategy=payload.strategy,
        conditions=payload.conditions,
        targets=payload.targets,
        position=payload.position,
    )
    return success(result, request_id=_request_id(request))


@router.patch("/assignment-rules/{rule_id}", summary="Edit a rule")
async def update_rule(
    rule_id: UUID,
    payload: AssignmentRuleUpdateRequest,
    request: Request,
    principal: CurrentPrincipal,
    version: Annotated[int | None, Query()] = None,
) -> dict[str, Any]:
    principal.require("lead", "assign")
    result = await assignment_rules.update_rule(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        rule_id=rule_id,
        expected_version=version,
        name=payload.name,
        strategy=payload.strategy,
        conditions=payload.conditions,
        targets=payload.targets,
        position=payload.position,
        is_active=payload.is_active,
    )
    return success(result, request_id=_request_id(request))


@router.delete("/assignment-rules/{rule_id}", summary="Delete a rule")
async def delete_rule(
    rule_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "assign")
    result = await assignment_rules.delete_rule(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, rule_id=rule_id
    )
    return success(result, request_id=_request_id(request))


@router.post("/assignment-rules/reorder", summary="Reorder the rule set")
async def reorder_rules(
    payload: ReorderRulesRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "assign")
    rows = await assignment_rules.reorder_rules(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, ordered_ids=payload.rule_ids
    )
    return success({"items": rows, "total": len(rows)}, request_id=_request_id(request))
