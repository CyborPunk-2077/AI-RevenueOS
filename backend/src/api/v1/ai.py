"""AI endpoints. Every response carries provider/model/cost-safe metadata."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from api.app.envelope import success
from api.deps.idempotency import IdempotencyContext, idempotency
from api.deps.principal import CurrentPrincipal, rate_limit
from api.v1.schemas import (
    AiChatRequest,
    AiTaskRequest,
    PromptEvaluationRequest,
    PromptPromotionRequest,
    PromptRollbackRequest,
)

router = APIRouter(prefix="/ai", tags=["ai"])


def _gateway() -> Any:
    from application.ai.registry import get_gateway

    return get_gateway()


@router.get("/health", summary="AI provider and circuit health")
async def ai_health(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("ai", "read")
    return success(_gateway().health(), request_id=getattr(request.state, "correlation_id", None))


@router.post(
    "/chat",
    summary="Copilot chat",
    dependencies=[Depends(rate_limit("ai_copilot_user"))],
)
async def ai_chat(
    payload: AiChatRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Chat never takes an autonomous external action; tool calls are confirmation gated."""
    principal.require("ai", "execute")
    from application.ai.service import AiService

    result = await AiService.for_principal(principal).chat(
        payload.message, entity_type=payload.entity_type, entity_id=payload.entity_id
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post(
    "/generate",
    summary="Generate content for human review",
    dependencies=[Depends(rate_limit("ai_generate_user"))],
)
async def ai_generate(
    payload: AiTaskRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("ai", "execute")
    from application.ai.service import AiService

    result = await AiService.for_principal(principal).run_task(
        payload.task, payload.input, options=payload.options
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.get("/usage", summary="AI usage and cost for the tenant")
async def ai_usage(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("ai", "read")
    from application.ai.service import AiService

    return success(
        await AiService.for_principal(principal).usage(),
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/prompts", summary="List governed prompt metadata")
async def prompts(
    request: Request, principal: CurrentPrincipal, task: str | None = None
) -> dict[str, Any]:
    from application.ai.prompt_registry import list_prompts

    rows = await list_prompts(principal, task=task)
    return success(
        {"prompts": rows, "templates_returned": False},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/prompts/sync", summary="Mirror immutable Git prompt versions")
async def sync_prompts(
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.ai.prompt_registry import sync_git_prompts

    result = await sync_git_prompts(principal, idempotency_key=idem.key)
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/prompts/{task}/v{version}/evaluations", summary="Record gold-set evidence")
async def evaluate_prompt(
    task: str,
    version: int,
    payload: PromptEvaluationRequest,
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.ai.prompt_registry import record_evaluation

    result = await record_evaluation(
        principal,
        task=task,
        version=version,
        evaluation_set=payload.evaluation_set,
        evaluation_version=payload.evaluation_version,
        content_hash=payload.content_hash,
        results=[item.model_dump() for item in payload.results],
        idempotency_key=idem.key,
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/prompts/{task}/v{version}/promote", summary="Promote an evaluated prompt")
async def promote_prompt_version(
    task: str,
    version: int,
    payload: PromptPromotionRequest,
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.ai.prompt_registry import promote_prompt

    result = await promote_prompt(
        principal,
        task=task,
        version=version,
        evaluation_run_id=payload.evaluation_run_id,
        idempotency_key=idem.key,
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/prompts/{task}/rollback", summary="Rollback to evaluated prompt evidence")
async def rollback_prompt_version(
    task: str,
    payload: PromptRollbackRequest,
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.ai.prompt_registry import rollback_prompt

    result = await rollback_prompt(
        principal,
        task=task,
        target_version=payload.target_version,
        idempotency_key=idem.key,
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))
