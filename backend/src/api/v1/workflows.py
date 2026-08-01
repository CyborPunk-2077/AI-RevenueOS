"""Workflow validation, publication and execution control."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from api.v1.schemas import WorkflowPublishRequest, WorkflowValidateRequest
from domain.workflows.dsl import DslValidationError, compile_workflow, validate_workflow
from shared.exceptions import ValidationError

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.post("/validate", summary="Validate a workflow document against the restricted DSL")
async def validate(
    payload: WorkflowValidateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("workflow", "read")
    report = validate_workflow(payload.document)
    return success(report.to_dict(), request_id=getattr(request.state, "correlation_id", None))


@router.post("/publish", summary="Publish an immutable workflow version")
async def publish(
    payload: WorkflowPublishRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("workflow", "update")
    try:
        plan = compile_workflow(payload.document)
    except DslValidationError as exc:
        raise ValidationError(
            "The workflow document failed validation.",
            details={"problems": exc.problems},
        ) from exc
    return success(
        {
            "content_hash": plan["content_hash"],
            "entry_nodes": plan["entry_nodes"],
            "external_effect_nodes": plan["external_effect_nodes"],
            "global_policy": plan["global_policy"],
            "status": "published",
            "changelog": payload.changelog,
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/{workflow_id}/kill", summary="Engage the workflow kill switch")
async def kill(workflow_id: UUID, request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("workflow", "execute")
    from application.workflows.control import engage_kill_switch

    result = await engage_kill_switch(
        tenant_id=principal.tenant_id, workflow_id=workflow_id, actor_id=principal.user_id
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))
