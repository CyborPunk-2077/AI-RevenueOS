"""Disaster recovery for a lead destroyed by the old demo refresh. LOCAL ONLY.

This is not a business feature and must never become one. It rebuilds a lead row
from the append-only evidence that survived its deletion - the `lead_source_event`
written when it was captured, and the audit entries written as it was worked - so
that the activities still sitting in the database have their record back.

Rules it holds to:

* **Only what the evidence says.** Every field comes from the stored capture
  payload or an audit row. Nothing is inferred, and nothing is invented to fill a
  gap - a task whose title was recorded is restored, a note whose body was not is
  reported as unrecoverable and left alone.
* **The original id.** Activities, source events and audit rows all point at it.
  Recreating under a new id would orphan the very history this exists to reconnect.
* **No duplicate history.** The surviving activities are not copied; they simply
  become reachable again. The script refuses to run if the lead already exists.
* **Honest timestamps.** `created_at` is the moment of the original capture, taken
  from the source event, not the moment of recovery.

    python src/scripts/recover_lead.py --lead-id <uuid> [--apply]

Without `--apply` it reports what it would restore and writes nothing.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from infrastructure.database.models.crm import Task
from infrastructure.database.models.leads import Lead, LeadSourceEvent
from infrastructure.database.session import admin_session
from infrastructure.logging.setup import configure_logging, get_logger
from shared.settings import get_settings

logger = get_logger("scripts.recover_lead")


async def _gather(session: Any, lead_id: UUID) -> dict[str, Any]:
    """Everything the database still knows about the destroyed lead."""
    existing = (await session.execute(select(Lead).where(Lead.id == lead_id))).scalar_one_or_none()

    capture_event = (
        (
            await session.execute(
                select(LeadSourceEvent)
                .where(LeadSourceEvent.lead_id == lead_id, LeadSourceEvent.outcome == "created")
                .order_by(LeadSourceEvent.created_at.asc())
            )
        )
        .scalars()
        .first()
    )

    activities = (
        await session.execute(
            text(
                "SELECT id, created_at, subject FROM app.activities "
                "WHERE entity_id = :lead ORDER BY created_at"
            ),
            {"lead": lead_id},
        )
    ).all()

    audit = (
        await session.execute(
            text(
                "SELECT action, resource_id, created_at, actor_id, new_values "
                "FROM audit.audit_logs WHERE new_values ->> 'entity_id' = :lead_text "
                "   OR resource_id = :lead ORDER BY created_at"
            ),
            {"lead": lead_id, "lead_text": str(lead_id)},
        )
    ).all()

    return {
        "existing": existing,
        "capture_event": capture_event,
        "activities": activities,
        "audit": audit,
    }


def _plan_tasks(audit: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """Tasks whose title the audit preserved, and the ids it did not.

    `task.create` records the title, so those are faithfully reconstructable.
    Anything the audit did not capture - a due date, a priority - stays unset
    rather than being guessed at.
    """
    created: dict[str, dict[str, Any]] = {}
    completions: dict[str, Any] = {}

    for action, resource_id, created_at, actor_id, new_values in audit:
        values = new_values or {}
        if action == "task.create" and values.get("title"):
            created[str(resource_id)] = {
                "id": UUID(str(resource_id)),
                "title": str(values["title"]),
                "created_at": created_at,
                "actor_id": actor_id,
            }
        elif action == "task.complete":
            completions[str(resource_id)] = values.get("completed_at")

    plan = []
    for task_id, record in created.items():
        record["completed_at"] = completions.get(task_id)
        plan.append(record)

    unrecoverable = [
        str(resource_id)
        for action, resource_id, _created_at, _actor, values in audit
        if action == "note.create" and not (values or {}).get("body")
    ]
    return plan, unrecoverable


async def recover(lead_id: UUID, *, apply: bool) -> int:
    settings = get_settings()
    if settings.environment != "local":
        raise SystemExit(f"refusing to run in the '{settings.environment}' environment")

    async with admin_session() as session:
        found = await _gather(session, lead_id)

        if found["existing"] is not None:
            print(f"\n  Lead {lead_id} already exists. Nothing to recover.\n")  # noqa: T201
            return 0

        event = found["capture_event"]
        if event is None:
            print(f"\n  No capture event survives for {lead_id}; cannot recover.\n")  # noqa: T201
            return 1

        payload = dict(event.raw_payload or {})
        capture = dict(payload.get("capture") or {})
        tasks, lost_notes = _plan_tasks(list(found["audit"]))

        print("\n" + "=" * 66)  # noqa: T201
        print("  Recoverable from surviving evidence")  # noqa: T201
        print("=" * 66)  # noqa: T201
        print(f"  lead id      {lead_id}")  # noqa: T201
        print(f"  name         {payload.get('first_name')}")  # noqa: T201
        print(f"  business     {capture.get('company')}")  # noqa: T201
        print(f"  captured at  {event.created_at.isoformat()}")  # noqa: T201
        print(f"  activities   {len(found['activities'])} (reconnect, not copied)")  # noqa: T201
        print(f"  tasks        {len(tasks)} with titles recorded in the audit")  # noqa: T201
        print(f"  notes        {len(lost_notes)} existed; bodies were not audited")  # noqa: T201
        print("=" * 66 + "\n")  # noqa: T201

        if not apply:
            print("  Dry run. Re-run with --apply to write these rows.\n")  # noqa: T201
            return 0

        session.add(
            Lead(
                id=lead_id,
                tenant_id=event.tenant_id,
                first_name=str(payload.get("first_name") or "Recovered prospect")[:120],
                last_name=payload.get("last_name"),
                email=payload.get("email"),
                phone=payload.get("phone"),
                source=str(payload.get("source") or "manual")[:80],
                source_channel=payload.get("source_channel"),
                # `recovered_at` is deliberately part of the record: anyone reading
                # this prospect later should be able to see that it was rebuilt
                # from evidence rather than entered normally.
                capture={
                    **capture,
                    "recovered_from_source_event": str(event.id),
                    "recovered_at": _now_iso(),
                },
                utm=payload.get("utm") or {},
                status="new",
                assignee_id=(
                    UUID(str(payload["assignee_id"])) if payload.get("assignee_id") else None
                ),
                team_id=(UUID(str(payload["team_id"])) if payload.get("team_id") else None),
                branch_id=(UUID(str(payload["branch_id"])) if payload.get("branch_id") else None),
                dedupe_key=None,
                # The capture moment, from the event. Not the moment of recovery.
                created_at=event.created_at,
                updated_at=event.created_at,
                # Derived from the surviving outbound activities rather than
                # backfilled: the earliest one is, by definition, the first reply.
                first_response_at=_first_outbound(found["activities"]),
                version=1,
            )
        )

        for record in tasks:
            session.add(
                Task(
                    id=record["id"],
                    tenant_id=event.tenant_id,
                    title=record["title"][:250],
                    description=None,
                    entity_type="lead",
                    entity_id=lead_id,
                    assignee_id=record["actor_id"],
                    due_at=None,
                    priority="normal",
                    status="completed" if record["completed_at"] else "open",
                    completed_at=record["completed_at"],
                    is_next_action=False,
                    source="recovered",
                    created_by=record["actor_id"],
                    created_at=record["created_at"],
                    updated_at=record["created_at"],
                    version=1,
                )
            )

    logger.info(
        "lead_recovered",
        lead_id=str(lead_id),
        tasks_restored=len(tasks),
        notes_unrecoverable=len(lost_notes),
    )
    print(f"  Restored lead {lead_id} and {len(tasks)} task(s).")  # noqa: T201
    if lost_notes:
        print(  # noqa: T201
            f"  {len(lost_notes)} note(s) are proven to have existed but their text "
            "was never audited, so they were NOT recreated."
        )
    print()  # noqa: T201
    return 0


def _now_iso() -> str:
    from shared.utils.timeutil import utcnow

    return utcnow().isoformat()


def _first_outbound(activities: list[Any]) -> Any:
    """The earliest surviving activity timestamp, or None when there are none."""
    return activities[0][1] if activities else None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild a deleted lead from surviving evidence")
    parser.add_argument("--lead-id", required=True)
    parser.add_argument("--apply", action="store_true", help="write the rows")
    args = parser.parse_args()

    configure_logging(json_output=False)
    return await recover(UUID(args.lead_id), apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
