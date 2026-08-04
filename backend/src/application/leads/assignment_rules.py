"""Assignment rules: CRUD, reorder, and execution against a lead.

The cursor that makes `round_robin` fair lives on the rule row and is advanced
inside the same transaction that assigns the lead. Two concurrent captures can
therefore hand the same person two leads in a row - `SELECT ... FOR UPDATE` would
serialise every capture behind one rule row, which is a worse trade. Fairness
here is "even over time", not "strictly alternating".
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select

from application.audit.recorder import AuditRecorder
from domain.leads.assignment import select_assignee, validate_rule, validate_rule_name
from infrastructure.database.models.leads import AssignmentRule, Lead
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span
from shared.exceptions import NotFound, PreconditionFailed
from shared.utils.ids import uuid7

logger = get_logger("application.leads.assignment_rules")

MAX_RULES = 100


def _serialize(rule: AssignmentRule) -> dict[str, Any]:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "entity_type": rule.entity_type,
        "strategy": rule.strategy,
        "conditions": rule.conditions,
        "targets": list(rule.targets or []),
        "position": rule.position,
        "is_active": rule.is_active,
        "cursor": rule.cursor,
        "version": rule.version,
    }


def _as_rule(rule: AssignmentRule) -> dict[str, Any]:
    data = _serialize(rule)
    data["_row"] = rule
    return data


async def _load(session: Any, tenant_id: UUID, rule_id: UUID) -> AssignmentRule:
    rule: AssignmentRule | None = (
        await session.execute(
            select(AssignmentRule).where(
                AssignmentRule.id == rule_id, AssignmentRule.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if rule is None:
        raise NotFound("That assignment rule does not exist.")
    return rule


async def list_rules(*, tenant_id: UUID, entity_type: str = "lead") -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(AssignmentRule)
                    .where(
                        AssignmentRule.tenant_id == tenant_id,
                        AssignmentRule.entity_type == entity_type,
                    )
                    .order_by(AssignmentRule.position, AssignmentRule.created_at)
                )
            )
            .scalars()
            .all()
        )
        return [_serialize(rule) for rule in rows]


async def create_rule(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    name: str,
    strategy: str = "round_robin",
    conditions: dict[str, Any] | None = None,
    targets: list[Any] | None = None,
    position: int | None = None,
    entity_type: str = "lead",
) -> dict[str, Any]:
    clean_name = validate_rule_name(name)
    clean_conditions, clean_targets = validate_rule(
        strategy=strategy, conditions=conditions or {}, targets=targets or []
    )
    rule_id = uuid7()

    async with tenant_session(tenant_id) as session:
        existing = (
            (
                await session.execute(
                    select(AssignmentRule).where(
                        AssignmentRule.tenant_id == tenant_id,
                        AssignmentRule.entity_type == entity_type,
                    )
                )
            )
            .scalars()
            .all()
        )
        if len(existing) >= MAX_RULES:
            raise PreconditionFailed(
                f"This organisation already has {MAX_RULES} rules.",
                details={"limit": MAX_RULES},
            )

        session.add(
            AssignmentRule(
                id=rule_id,
                tenant_id=tenant_id,
                name=clean_name,
                entity_type=entity_type,
                strategy=strategy,
                conditions=clean_conditions,
                targets=clean_targets,
                position=position if position is not None else len(existing),
                is_active=True,
                cursor=0,
                version=1,
            )
        )
        AuditRecorder(session).record(
            action="assignment_rule.created",
            resource_type="assignment_rule",
            resource_id=rule_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"name": clean_name, "strategy": strategy, "targets": len(clean_targets)},
        )
        await session.flush()
        return _serialize(await _load(session, tenant_id, rule_id))


async def update_rule(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    rule_id: UUID,
    expected_version: int | None = None,
    name: str | None = None,
    strategy: str | None = None,
    conditions: dict[str, Any] | None = None,
    targets: list[Any] | None = None,
    position: int | None = None,
    is_active: bool | None = None,
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        rule = await _load(session, tenant_id, rule_id)
        if expected_version is not None and rule.version != expected_version:
            raise PreconditionFailed(
                "This rule changed since you loaded it.",
                details={"expected": expected_version, "current": rule.version},
            )

        before = _serialize(rule)
        if name is not None:
            rule.name = validate_rule_name(name)
        if strategy is not None or conditions is not None or targets is not None:
            clean_conditions, clean_targets = validate_rule(
                strategy=strategy or rule.strategy,
                conditions=conditions if conditions is not None else rule.conditions,
                targets=targets if targets is not None else list(rule.targets or []),
            )
            rule.strategy = strategy or rule.strategy
            rule.conditions = clean_conditions
            if targets is not None:
                rule.targets = clean_targets
                # The target list changed, so the old cursor points at a different
                # person than the user thinks. Restarting is the honest option.
                rule.cursor = 0
        if position is not None:
            rule.position = position
        if is_active is not None:
            rule.is_active = is_active
        rule.version += 1

        AuditRecorder(session).record(
            action="assignment_rule.updated",
            resource_type="assignment_rule",
            resource_id=rule_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            old_values={"name": before["name"], "is_active": before["is_active"]},
            new_values={"name": rule.name, "is_active": rule.is_active},
        )
        return _serialize(rule)


async def delete_rule(*, tenant_id: UUID, actor_id: UUID, rule_id: UUID) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        rule = await _load(session, tenant_id, rule_id)
        await session.delete(rule)
        AuditRecorder(session).record(
            action="assignment_rule.deleted",
            resource_type="assignment_rule",
            resource_id=rule_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            old_values={"name": rule.name},
        )
        return {"id": str(rule_id), "deleted": True}


async def reorder_rules(
    *, tenant_id: UUID, actor_id: UUID, ordered_ids: list[UUID]
) -> list[dict[str, Any]]:
    """Order is the whole semantics of the rule set, so reordering is one atomic act."""
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(AssignmentRule).where(AssignmentRule.tenant_id == tenant_id)
                )
            )
            .scalars()
            .all()
        )
        by_id = {rule.id: rule for rule in rows}
        missing = [str(rule_id) for rule_id in ordered_ids if rule_id not in by_id]
        if missing:
            raise NotFound("Some of those rules do not exist.", details={"missing": missing})

        for position, rule_id in enumerate(ordered_ids):
            by_id[rule_id].position = position
            by_id[rule_id].version += 1

        AuditRecorder(session).record(
            action="assignment_rule.reordered",
            resource_type="assignment_rule",
            tenant_id=tenant_id,
            actor_id=actor_id,
            new_values={"order": [str(rule_id) for rule_id in ordered_ids]},
        )
        return [
            _serialize(rule)
            for rule in sorted(by_id.values(), key=lambda r: (r.position, r.created_at))
        ]


async def apply_rules(
    *, tenant_id: UUID, actor_id: UUID, lead_id: UUID, dry_run: bool = False
) -> dict[str, Any]:
    """Run the rule set against one lead and assign it."""
    with start_span("assignment apply", attributes={"tenant.id": str(tenant_id)}):
        async with tenant_session(tenant_id) as session:
            lead: Lead | None = (
                await session.execute(
                    select(Lead).where(
                        Lead.id == lead_id,
                        Lead.tenant_id == tenant_id,
                        Lead.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if lead is None:
                raise NotFound("That lead does not exist.")

            rules = [
                _as_rule(rule)
                for rule in (
                    (
                        await session.execute(
                            select(AssignmentRule)
                            .where(
                                AssignmentRule.tenant_id == tenant_id,
                                AssignmentRule.entity_type == "lead",
                                AssignmentRule.is_active.is_(True),
                            )
                            .order_by(AssignmentRule.position)
                        )
                    )
                    .scalars()
                    .all()
                )
            ]

            decision = select_assignee(
                rules,
                {
                    "source": lead.source,
                    "source_channel": lead.source_channel,
                    "city": (lead.capture or {}).get("city"),
                    "company": (lead.capture or {}).get("company"),
                    "category": lead.category,
                    "qualification_score": lead.qualification_score,
                    "status": lead.status,
                },
            )

            if decision is None:
                return {"lead_id": str(lead_id), "assigned": False, "reason": "no_rule_matched"}
            if dry_run:
                return {
                    "lead_id": str(lead_id),
                    "assigned": False,
                    "would_assign": decision.as_dict(),
                }

            previous = str(lead.assignee_id) if lead.assignee_id else None
            lead.assignee_id = UUID(decision.assignee_id)
            lead.updated_by = actor_id
            lead.version += 1

            for rule in rules:
                if rule["id"] == decision.rule_id and decision.next_cursor is not None:
                    rule["_row"].cursor = decision.next_cursor

            AuditRecorder(session).record(
                action="lead.assigned",
                resource_type="lead",
                resource_id=lead_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                old_values={"assignee_id": previous},
                new_values={
                    "assignee_id": decision.assignee_id,
                    "rule_id": decision.rule_id,
                    "strategy": decision.strategy,
                },
            )
            return {"lead_id": str(lead_id), "assigned": True, **decision.as_dict()}
