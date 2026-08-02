"""Workflow validation, publication and execution control."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Request

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from api.v1.schemas import (
    WorkflowApprovalDecisionRequest,
    WorkflowPublishRequest,
    WorkflowValidateRequest,
)
from domain.workflows.dsl import validate_workflow

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get("/approvals", summary="List workflow approvals assigned to the caller")
async def approvals(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("approval", "read")
    from application.workflows.approvals import list_pending_approvals

    rows = await list_pending_approvals(principal)
    return success(rows, request_id=getattr(request.state, "correlation_id", None))


@router.post("/approvals/{approval_id}/decide", summary="Approve or reject a workflow node")
async def decide(
    approval_id: UUID,
    payload: WorkflowApprovalDecisionRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("approval", "approve")
    from application.workflows.approvals import decide_approval

    result = await decide_approval(
        approval_id=approval_id,
        decision=payload.decision,
        comment=payload.comment,
        principal=principal,
    )
    if result["resume"]:
        from infrastructure.celery.context import build_headers
        from infrastructure.celery.tasks.workflow import resume_execution

        resume_execution.apply_async(
            args=[result["execution_id"]],
            headers=build_headers(
                tenant_id=principal.tenant_id,
                correlation_id=getattr(request.state, "correlation_id", None),
                actor_id=principal.user_id,
                actor_type="user",
            ),
        )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


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
    from application.workflows.service import publish_workflow

    published = await publish_workflow(
        document=payload.document,
        changelog=payload.changelog,
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
    )
    return success(
        published,
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
