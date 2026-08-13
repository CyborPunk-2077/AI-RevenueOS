"""Lead endpoints: capture, dedupe, qualification and human review."""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from api.app.envelope import success
from api.deps.idempotency import IdempotencyContext, idempotency, parse_if_match
from api.deps.principal import CurrentPrincipal, ListQuery, list_query, rate_limit
from api.v1.schemas import (
    ActivityLogRequest,
    LeadBulkUpdateRequest,
    LeadCreate,
    LeadDisqualifyRequest,
    LeadMergeRequest,
    LeadQualifyRequest,
    LeadReviewRequest,
    LeadUpdate,
    NoteCreateRequest,
    StartingBaselineRequest,
)
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


@router.post(
    "/bulk",
    summary="Atomically update up to 100 scoped leads",
    dependencies=[Depends(rate_limit("lead_bulk_tenant", per="tenant"))],
)
async def bulk_update_leads(
    payload: LeadBulkUpdateRequest,
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    principal.require("lead", "update")
    changes = payload.changes.model_dump(exclude_unset=True)
    if "assignee_id" in changes:
        principal.require("lead", "assign")
    from application.leads.service import LeadService

    result = await LeadService.for_principal(principal).bulk_update(
        payload.lead_ids, changes, idempotency_key=idem.key
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.get("/response-metrics", summary="Leakage figures for the caller's scope")
async def response_metrics(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    """Counts and response times behind the operational dashboard.

    Declared before `/{lead_id}` so the literal path is not swallowed by the UUID
    route.
    """
    principal.require("lead", "list")
    principal.require("task", "list")
    from application.leads.metrics import LeadMetricsService

    service = LeadMetricsService.for_principal(principal)
    metrics = await service.response_metrics()
    metrics["overdue_follow_ups"] = await service.overdue_task_count()
    return success(metrics, request_id=getattr(request.state, "correlation_id", None))


@router.get("/starting-baseline", summary="The pilot's captured 'before' picture")
async def read_starting_baseline(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    """The stored baseline plus what the same figures say right now.

    Declared before `/{lead_id}` so the literal path is not swallowed by the UUID
    route.
    """
    principal.require("lead", "list")
    principal.require("task", "list")
    from application.leads.baseline import BaselineService

    service = BaselineService.for_principal(principal)
    payload = await service.reconcile()
    if not payload.get("has_baseline"):
        # Nothing captured yet, so show what capturing would record. This is a
        # preview and says so; it is never presented as a baseline.
        payload["preview"] = await service.preview()
    return success(payload, request_id=getattr(request.state, "correlation_id", None))


@router.post(
    "/starting-baseline",
    status_code=status.HTTP_201_CREATED,
    summary="Capture the starting baseline",
)
async def capture_starting_baseline(
    payload: StartingBaselineRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """Photograph today's figures and keep them as the pilot's starting point.

    Requires `tenant:configure` rather than `lead:list`: this writes a number the
    whole pilot will later be discussed against, and a salesperson should not be
    able to reset it by clicking something.
    """
    principal.require("tenant", "configure")
    principal.require("lead", "list")
    principal.require("task", "list")
    from application.leads.baseline import BaselineService

    captured = await BaselineService.for_principal(principal).capture(
        replace=payload.replace, note=payload.note
    )
    return success(captured, request_id=getattr(request.state, "correlation_id", None))


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


@router.post("/{lead_id}/deduplicate", summary="Scan for duplicate candidates")
async def deduplicate_lead(
    lead_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "read")
    from application.leads import lifecycle_ops

    result = await lifecycle_ops.deduplicate(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, lead_id=lead_id
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/merge", summary="Merge another lead into this one")
async def merge_lead(
    lead_id: UUID,
    payload: LeadMergeRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    """`lead_id` survives; the lead named in the body is folded into it."""
    principal.require("lead", "merge")
    from application.leads import lifecycle_ops

    result = await lifecycle_ops.merge_leads(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        survivor_id=lead_id,
        loser_id=payload.merge_id,
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/disqualify", summary="Disqualify a lead with a reason")
async def disqualify_lead(
    lead_id: UUID,
    payload: LeadDisqualifyRequest,
    request: Request,
    principal: CurrentPrincipal,
) -> dict[str, Any]:
    principal.require("lead", "update")
    from application.leads import lifecycle_ops

    result = await lifecycle_ops.disqualify_lead(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        lead_id=lead_id,
        reason=payload.reason,
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/restore", summary="Reopen a disqualified or archived lead")
async def restore_lead(
    lead_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "update")
    from application.leads import lifecycle_ops

    result = await lifecycle_ops.restore_lead(
        tenant_id=principal.tenant_id, actor_id=principal.user_id, lead_id=lead_id
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/assign", summary="Run the assignment rules against this lead")
async def assign_lead(
    lead_id: UUID,
    request: Request,
    principal: CurrentPrincipal,
    dry_run: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    principal.require("lead", "assign")
    from application.leads import assignment_rules

    result = await assignment_rules.apply_rules(
        tenant_id=principal.tenant_id,
        actor_id=principal.user_id,
        lead_id=lead_id,
        dry_run=dry_run,
    )
    return success(result, request_id=getattr(request.state, "correlation_id", None))


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


# --- history and follow-ups --------------------------------------------------
#
# A prospect's history has to exist before conversion, not after it. Logging a
# call against a lead writes the same activity row a contact would get, so the
# record survives the conversion instead of restarting from empty.


def _timeline(principal: Any) -> Any:
    from application.crm.timeline import TimelineService

    return TimelineService.for_principal(principal)


@router.get("/{lead_id}/timeline", summary="Activities and notes for a lead")
async def lead_timeline(
    lead_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "read")
    principal.require("activity", "list")
    entries = await _timeline(principal).timeline("lead", lead_id)
    return success({"timeline": entries}, request_id=getattr(request.state, "correlation_id", None))


@router.post(
    "/{lead_id}/activities", status_code=status.HTTP_201_CREATED, summary="Log an activity"
)
async def log_lead_activity(
    lead_id: UUID, payload: ActivityLogRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("activity", "create")
    entry = await _timeline(principal).log_activity("lead", lead_id, payload.model_dump())
    return success(entry, request_id=getattr(request.state, "correlation_id", None))


@router.post("/{lead_id}/notes", status_code=status.HTTP_201_CREATED, summary="Add a note")
async def add_lead_note(
    lead_id: UUID, payload: NoteCreateRequest, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("note", "create")
    entry = await _timeline(principal).add_note("lead", lead_id, payload.model_dump())
    return success(entry, request_id=getattr(request.state, "correlation_id", None))


@router.get("/{lead_id}/tasks", summary="Follow-ups on a lead")
async def lead_tasks(
    lead_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("lead", "read")
    principal.require("task", "list")
    from application.crm.tasks import TaskService

    tasks = await TaskService.for_principal(principal).for_entity("lead", lead_id)
    return success({"tasks": tasks}, request_id=getattr(request.state, "correlation_id", None))
