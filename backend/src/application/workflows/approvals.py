"""Durable, assignee-bound workflow approval decisions and resumption."""

from __future__ import annotations

from typing import Any
from uuid import UUID


def _matching_assignees(assignees: list[Any], principal: Any) -> set[str]:
    user_token = f"user:{principal.user_id}"
    role_tokens = {f"role:{role}" for role in principal.roles}
    allowed = {str(value) for value in assignees}
    return ({user_token} | role_tokens) & allowed


async def list_pending_approvals(principal: Any) -> list[dict[str, Any]]:
    from sqlalchemy import select

    from infrastructure.database.models.workflows import WorkflowApproval
    from infrastructure.database.session import tenant_session

    async with tenant_session(principal.tenant_id) as session:
        rows = list(
            (
                await session.execute(
                    select(WorkflowApproval)
                    .where(WorkflowApproval.state == "requested")
                    .order_by(WorkflowApproval.created_at.asc())
                    .limit(200)
                )
            )
            .scalars()
            .all()
        )
    return [_serialize(row) for row in rows if _matching_assignees(row.assignees, principal)]


async def decide_approval(
    *,
    approval_id: UUID,
    decision: str,
    comment: str,
    principal: Any,
) -> dict[str, Any]:
    from sqlalchemy import select

    from application.audit.recorder import AuditRecorder
    from domain.base import DomainEvent
    from domain.events.catalog import APPROVAL_APPROVED, APPROVAL_REJECTED
    from infrastructure.database.models.audit import EventOutbox
    from infrastructure.database.models.workflows import WorkflowApproval, WorkflowExecution
    from infrastructure.database.session import tenant_session
    from shared.exceptions import Conflict, Forbidden, NotFound, ValidationError
    from shared.utils.timeutil import utcnow

    if decision not in {"approved", "rejected"}:
        raise ValidationError("Decision must be approved or rejected.")

    async with tenant_session(principal.tenant_id) as session:
        approval = (
            await session.execute(
                select(WorkflowApproval).where(WorkflowApproval.id == approval_id).with_for_update()
            )
        ).scalar_one_or_none()
        if approval is None:
            raise NotFound("Workflow approval not found.")
        matches = _matching_assignees(approval.assignees, principal)
        if not matches:
            raise Forbidden("This approval is not assigned to you or your roles.")
        if approval.state != "requested":
            prior = next(
                (
                    item
                    for item in approval.decisions or []
                    if str(item.get("actor_id")) == str(principal.user_id)
                ),
                None,
            )
            if prior and prior.get("decision") == decision:
                return {**_serialize(approval), "duplicate": True, "resume": False}
            raise Conflict("This approval has already been resolved.")
        if any(
            str(item.get("actor_id")) == str(principal.user_id) for item in approval.decisions or []
        ):
            raise Conflict("You have already decided this approval.")

        moment = utcnow()
        decisions = [
            *(approval.decisions or []),
            {
                "actor_id": str(principal.user_id),
                "decision": decision,
                "comment": comment[:1000],
                "assignees": sorted(matches),
                "decided_at": moment.isoformat(),
            },
        ]
        approval.decisions = decisions
        resolved = _resolved_state(
            approval.strategy,
            approval.quorum,
            approval.assignees,
            decisions,
        )
        if resolved:
            approval.state = resolved
            approval.resolved_at = moment

        execution = (
            await session.execute(
                select(WorkflowExecution)
                .where(WorkflowExecution.id == approval.execution_id)
                .with_for_update()
            )
        ).scalar_one()
        resume = resolved == "approved"
        if resume:
            execution.resume_at = moment
        elif resolved == "rejected":
            execution.state = "failed"
            execution.finished_at = moment
            execution.resume_at = None
            execution.error = {"reason": "approval rejected", "approval_id": str(approval.id)}

        AuditRecorder(session).record(
            action="workflow.approval_decided",
            resource_type="workflow_approval",
            resource_id=approval.id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            new_values={"decision": decision, "state": approval.state},
        )
        if resolved:
            event = DomainEvent(
                event_type=APPROVAL_APPROVED if resolved == "approved" else APPROVAL_REJECTED,
                tenant_id=principal.tenant_id,
                resource_type="workflow_approval",
                resource_id=approval.id,
                actor_id=principal.user_id,
                payload={
                    "execution_id": str(approval.execution_id),
                    "node_id": approval.node_id,
                },
            )
            session.add(
                EventOutbox(
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    tenant_id=event.tenant_id,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    payload=event.to_outbox_payload(),
                    correlation_id=event.correlation_id,
                    attempts=0,
                )
            )

    return {**_serialize(approval), "duplicate": False, "resume": resume}


def _resolved_state(
    strategy: str, quorum: int, assignees: list[Any], decisions: list[Any]
) -> str | None:
    approved = [item for item in decisions if item.get("decision") == "approved"]
    rejected = [item for item in decisions if item.get("decision") == "rejected"]
    if strategy == "any":
        return "approved" if approved else ("rejected" if rejected else None)
    if strategy == "all":
        if rejected:
            return "rejected"
        covered = {token for item in approved for token in item.get("assignees", [])}
        return "approved" if set(map(str, assignees)) <= covered else None
    if len(approved) >= quorum:
        return "approved"
    if len(rejected) > max(0, len(assignees) - quorum):
        return "rejected"
    return None


def _serialize(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "execution_id": str(row.execution_id),
        "node_id": row.node_id,
        "state": row.state,
        "strategy": row.strategy,
        "quorum": row.quorum,
        "assignees": list(row.assignees or []),
        "decisions": list(row.decisions or []),
        "summary": row.summary,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
    }
