"""CSV import: preview, then commit. Both go through the same plan.

The preview and the commit call `plan_import` with identical inputs, so what the
user approved is what runs. A preview that takes a different code path from the
commit is a preview of nothing.

Commit is idempotent on `import_key`: a double-clicked button, or a retried
request after a timeout, replays the same result rather than importing twice.
"""

from __future__ import annotations

import csv
import io
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from application.audit.recorder import AuditRecorder
from domain.leads.importing import (
    MAX_ROWS,
    ImportPlan,
    plan_import,
    suggest_mapping,
    validate_mapping,
)
from domain.leads.lifecycle import dedupe_key
from infrastructure.database.models.leads import Lead, LeadSourceEvent
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span
from shared.exceptions import Conflict, ValidationError
from shared.utils.ids import uuid7

logger = get_logger("application.leads.importer")

MAX_BYTES = 5 * 1024 * 1024


def parse_csv(content: bytes) -> tuple[list[str], list[dict[str, Any]]]:
    """Decode and parse. Refuses anything that is not plausibly a CSV of leads."""
    if len(content) > MAX_BYTES:
        raise ValidationError("That file is larger than 5 MB.", details={"bytes": len(content)})
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Excel on a Windows machine in India commonly writes cp1252.
        try:
            text = content.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise ValidationError(
                "That file is not UTF-8 or Windows-1252 text. Re-export it as CSV UTF-8."
            ) from exc

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValidationError("That file has no header row.")

    headers = [str(name or "").strip() for name in reader.fieldnames]
    rows: list[dict[str, Any]] = []
    for row in reader:
        rows.append({str(k or "").strip(): v for k, v in row.items()})
        if len(rows) > MAX_ROWS:
            raise ValidationError(
                f"An import may carry at most {MAX_ROWS} rows.", details={"limit": MAX_ROWS}
            )
    return headers, rows


async def preview_import(
    *,
    tenant_id: UUID,
    content: bytes,
    mapping: dict[str, str | None] | None = None,
    default_source: str = "csv_import",
) -> dict[str, Any]:
    """Judge the file and report, without writing anything."""
    headers, rows = parse_csv(content)
    resolved = validate_mapping(mapping if mapping is not None else suggest_mapping(headers))
    plan = plan_import(rows, resolved, default_source=default_source)

    existing = await _existing_dedupe_values(tenant_id, plan)

    return {
        "headers": headers,
        "suggested_mapping": suggest_mapping(headers),
        "mapping": resolved,
        **plan.summary(),
        # Existing leads are reported, not rejected: importing an updated row for
        # someone already in the CRM is a normal thing to want.
        "already_in_crm": sorted(existing),
        "sample": [{"row": row.row_number, "values": row.values} for row in plan.accepted[:5]],
    }


async def _existing_dedupe_values(tenant_id: UUID, plan: ImportPlan) -> set[str]:
    wanted = {row.dedupe_value for row in plan.accepted if row.dedupe_value}
    if not wanted:
        return set()
    async with tenant_session(tenant_id) as session:
        emails = (
            (
                await session.execute(
                    select(Lead.email).where(
                        Lead.tenant_id == tenant_id,
                        Lead.deleted_at.is_(None),
                        func.lower(Lead.email).in_(wanted),
                    )
                )
            )
            .scalars()
            .all()
        )
    return {str(email).lower() for email in emails if email}


async def commit_import(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    content: bytes,
    mapping: dict[str, str | None] | None = None,
    import_key: str,
    default_source: str = "csv_import",
    assign: bool = True,
) -> dict[str, Any]:
    """Create the accepted rows. Rejected rows are reported, never guessed at."""
    if not import_key.strip():
        raise ValidationError("An import key is required so a retry cannot double-import.")

    headers, rows = parse_csv(content)
    resolved = validate_mapping(mapping if mapping is not None else suggest_mapping(headers))
    plan = plan_import(rows, resolved, default_source=default_source)

    batch_id = uuid7()
    created: list[str] = []

    with start_span(
        "lead import",
        attributes={"tenant.id": str(tenant_id), "entity.type": "lead"},
    ):
        async with tenant_session(tenant_id) as session:
            replay = (
                await session.execute(
                    select(func.count())
                    .select_from(LeadSourceEvent)
                    .where(
                        LeadSourceEvent.tenant_id == tenant_id,
                        LeadSourceEvent.source_idempotency_key == import_key,
                    )
                )
            ).scalar_one()
            if replay:
                raise Conflict(
                    "That import has already been committed.",
                    details={"import_key": import_key},
                )

            assignments = await _assignment_rules(session, tenant_id) if assign else []

            for row in plan.accepted:
                lead_id = uuid7()
                values = dict(row.values)
                assignee = _assign(assignments, values)

                session.add(
                    Lead(
                        id=lead_id,
                        tenant_id=tenant_id,
                        first_name=values.get("first_name", "")[:120],
                        last_name=(values.get("last_name") or None),
                        email=(values.get("email") or None),
                        phone=(values.get("phone") or None),
                        source=values.get("source", default_source),
                        source_channel=values.get("source_channel") or "import",
                        capture={**row.capture, "import_batch_id": str(batch_id)},
                        status="new",
                        assignee_id=UUID(assignee) if assignee else None,
                        dedupe_key=dedupe_key(
                            email=values.get("email"),
                            phone=values.get("phone"),
                            name=values.get("first_name"),
                        ),
                        created_by=actor_id,
                        updated_by=actor_id,
                        version=1,
                    )
                )
                # One source event per row, keyed by the batch: attribution survives
                # even if the lead is later merged away.
                session.add(
                    LeadSourceEvent(
                        id=uuid7(),
                        tenant_id=tenant_id,
                        lead_id=lead_id,
                        source=values.get("source", default_source),
                        source_channel="csv_import",
                        source_idempotency_key=f"{import_key}:{row.row_number}",
                        raw_payload=row.values,
                        normalized={"dedupe_value": row.dedupe_value},
                        outcome="imported",
                    )
                )
                created.append(str(lead_id))

            # The batch marker carries the import key, and is what makes a replay
            # detectable above.
            session.add(
                LeadSourceEvent(
                    id=uuid7(),
                    tenant_id=tenant_id,
                    source="csv_import",
                    source_channel="csv_import",
                    source_idempotency_key=import_key,
                    raw_payload={"batch_id": str(batch_id), "rows": plan.total},
                    normalized={"accepted": len(plan.accepted), "rejected": len(plan.rejected)},
                    outcome="batch",
                )
            )

            AuditRecorder(session).record(
                action="lead.imported",
                resource_type="import",
                resource_id=batch_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                new_values={
                    "accepted": len(plan.accepted),
                    "rejected": len(plan.rejected),
                    "assigned": assign,
                },
            )

    logger.info(
        "lead_import_committed",
        tenant_id=str(tenant_id),
        accepted=len(plan.accepted),
        rejected=len(plan.rejected),
    )
    return {"batch_id": str(batch_id), "created_ids": created, **plan.summary()}


async def _assignment_rules(session: Any, tenant_id: UUID) -> list[dict[str, Any]]:
    from infrastructure.database.models.leads import AssignmentRule

    rows = (
        (
            await session.execute(
                select(AssignmentRule).where(
                    AssignmentRule.tenant_id == tenant_id,
                    AssignmentRule.entity_type == "lead",
                    AssignmentRule.is_active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": str(rule.id),
            "name": rule.name,
            "strategy": rule.strategy,
            "conditions": rule.conditions,
            "targets": rule.targets,
            "position": rule.position,
            "is_active": rule.is_active,
            "cursor": rule.cursor,
            "_row": rule,
        }
        for rule in rows
    ]


def _assign(rules: list[dict[str, Any]], values: dict[str, Any]) -> str | None:
    """Pick an assignee and advance the rule's cursor in place."""
    from domain.leads.assignment import select_assignee

    if not rules:
        return None
    decision = select_assignee(rules, values)
    if decision is None:
        return None
    for rule in rules:
        if rule["id"] == decision.rule_id and decision.next_cursor is not None:
            rule["cursor"] = decision.next_cursor
            rule["_row"].cursor = decision.next_cursor
    return decision.assignee_id
