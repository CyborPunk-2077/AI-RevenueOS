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
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select

from application.audit.recorder import AuditRecorder
from domain.leads.importing import (
    MAX_ROWS,
    ImportPlan,
    normalise_phone_digits,
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
from shared.utils.spreadsheet import neutralise_formula

logger = get_logger("application.leads.importer")

MAX_BYTES = 5 * 1024 * 1024


#: The starter sheet handed to a founder. Column names are the words they would
#: use, not our field names - `suggest_mapping` already knows these spellings, so
#: a file built from this template maps itself with nothing to confirm.
TEMPLATE_COLUMNS: Final[tuple[str, ...]] = (
    "Business name",
    "Contact person",
    "Phone",
    "Email",
    "City",
    "Industry",
    "Website",
    "Why we are approaching them",
    "Source",
    "Notes",
)

TEMPLATE_ROWS: Final[tuple[tuple[str, ...], ...]] = (
    (
        "Sri Lakshmi Sweets",
        "Ramesh Gowda",
        "+91 98450 11223",
        "ramesh@srilakshmisweets.in",
        "Basavanagudi, Bengaluru",
        "Sweets and bakery",
        "https://srilakshmisweets.in",
        "Festival orders taken on paper; loses repeat customers",
        "Walk past",
        "Owner is in most mornings",
    ),
    (
        "Nandi Physiotherapy",
        "",
        "080 4123 8890",
        "care@nandiphysio.in",
        "Malleshwaram, Bengaluru",
        "Clinics",
        "",
        "Appointment reminders done by hand, misses follow-up sessions",
        "Referral from Anitha",
        "",
    ),
    (
        "GreenLeaf Interiors",
        "Farida Khan",
        "9845066112",
        "",
        "HSR Layout, Bengaluru",
        "Interior design",
        "https://greenleafinteriors.in",
        "Site-visit enquiries split across two designers",
        "Instagram",
        "Busy until the end of the month",
    ),
)


def build_template_csv() -> str:
    """The example sheet, written through the same safety rule as an export."""
    buffer = io.StringIO()
    # QUOTE_MINIMAL with explicit \r\n: Excel on Windows is the target reader.
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(TEMPLATE_COLUMNS)
    for row in TEMPLATE_ROWS:
        writer.writerow([neutralise_formula(cell) for cell in row])
    return buffer.getvalue()


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

    matches = await _existing_matches(tenant_id, plan)

    # Reported per row, with the evidence, so the founder can see *which* business
    # this collides with and decide. Never merged automatically: two businesses
    # sharing a landline is common, and an unpickable merge is far harder to undo
    # than a duplicate.
    duplicates = [
        {
            "row": row.row_number,
            "incoming": row.values.get("first_name") or row.dedupe_value,
            **matches[row.dedupe_value],
        }
        for row in plan.accepted
        if row.dedupe_value in matches
    ]

    return {
        "headers": headers,
        "suggested_mapping": suggest_mapping(headers),
        "mapping": resolved,
        **plan.summary(),
        "duplicates": duplicates,
        "will_create": len(plan.accepted) - len(duplicates),
        "sample": [
            {
                "row": row.row_number,
                "values": row.values,
                # What will actually be stored, after normalisation, rather than
                # what the sheet said. Seeing `+919845012201` for a cell that read
                # `98450 12201` is how the founder learns to trust the import.
                "normalized": {
                    "name": row.values.get("first_name"),
                    "email": row.values.get("email"),
                    "phone": row.values.get("phone"),
                    "company": row.capture.get("company"),
                    "city": row.capture.get("city"),
                },
            }
            for row in plan.accepted[:8]
        ],
    }


async def _existing_matches(tenant_id: UUID, plan: ImportPlan) -> dict[str, dict[str, Any]]:
    """Map each incoming dedupe value to the prospect it already matches.

    Email *and* phone, because a founder importing the same business from two
    lists usually has the number both times and the address only once. Matching on
    email alone was the difference between "we caught the duplicate" and "we
    created a second copy of a customer we are already talking to".

    Phone comparison uses the last ten digits, which is what makes
    `+91 98450 12201`, `09845012201` and `98450-12201` the same number.
    """
    wanted = {row.dedupe_value for row in plan.accepted if row.dedupe_value}
    if not wanted:
        return {}

    matches: dict[str, dict[str, Any]] = {}
    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(Lead).where(
                        Lead.tenant_id == tenant_id,
                        Lead.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )

    for lead in rows:
        label = str(lead.capture.get("company") or "") if isinstance(lead.capture, dict) else ""
        display = label or f"{lead.first_name} {lead.last_name or ''}".strip()
        if lead.email and lead.email.lower() in wanted:
            matches.setdefault(
                lead.email.lower(),
                {
                    "lead_id": str(lead.id),
                    "name": display,
                    "matched_on": "email",
                    "evidence": lead.email.lower(),
                    "status": lead.status,
                },
            )
        if lead.phone:
            digits = normalise_phone_digits(lead.phone)
            if digits and digits in wanted:
                matches.setdefault(
                    digits,
                    {
                        "lead_id": str(lead.id),
                        "name": display,
                        "matched_on": "phone",
                        "evidence": lead.phone,
                        "status": lead.status,
                    },
                )
    return matches


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
            matches = await _existing_matches(tenant_id, plan)
            duplicates: list[dict[str, Any]] = []

            for row in plan.accepted:
                match = matches.get(row.dedupe_value)
                if match is not None:
                    # The existing prospect is left completely untouched - its
                    # owner, its status and its whole conversation history. The
                    # incoming row is not thrown away either: it is kept as a
                    # source event pointing at what it matched, so the attribution
                    # survives and a human can look at it later.
                    session.add(
                        LeadSourceEvent(
                            id=uuid7(),
                            tenant_id=tenant_id,
                            lead_id=None,
                            source=row.values.get("source", default_source),
                            source_channel="csv_import",
                            source_idempotency_key=f"{import_key}:{row.row_number}",
                            raw_payload=row.values,
                            normalized={"dedupe_value": row.dedupe_value},
                            outcome="duplicate",
                            duplicate_of_lead_id=UUID(str(match["lead_id"])),
                        )
                    )
                    duplicates.append({"row": row.row_number, **match})
                    continue

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
                    normalized={
                        "accepted": len(plan.accepted),
                        "rejected": len(plan.rejected),
                        "created": len(created),
                        "duplicates": len(duplicates),
                    },
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
                    "created": len(created),
                    "duplicates": len(duplicates),
                    "rejected": len(plan.rejected),
                    "assigned": assign,
                },
            )

    # Counts only. Names, numbers and addresses of real prospects have no business
    # in a log line.
    logger.info(
        "lead_import_committed",
        tenant_id=str(tenant_id),
        created=len(created),
        duplicates=len(duplicates),
        rejected=len(plan.rejected),
    )
    return {
        "batch_id": str(batch_id),
        "created_ids": created,
        "created": len(created),
        "duplicates": duplicates,
        **plan.summary(),
    }


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
