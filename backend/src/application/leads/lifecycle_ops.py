"""Deduplicate, merge, disqualify and restore.

Merge is the dangerous one, so it is worth stating what it does and does not do.

**The loser is never deleted.** It is soft-deleted and stamped with
`merged_into_id`, so an inbound webhook or a bookmarked URL that still names the
old id can be followed to the survivor instead of 404ing. Undoing a bad merge is
a support action, not a restore-from-backup.

**Only empty fields are filled.** The survivor's data wins; the loser contributes
what the survivor is missing. Overwriting a human-corrected field with older data
is the failure mode people never forgive.

**Source events are preserved on both sides**, exactly where they were written.
Attribution is the reason the duplicate existed; losing it to tidy a list defeats
the purpose, and `app.lead_source_events` is append-only anyway - a merge that
tried to re-point them could not commit.

Disqualify and restore are a pair: disqualification is reversible by design,
because "not now" is the most common reason and it is usually wrong within a
quarter.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update

from application.audit.recorder import AuditRecorder
from domain.leads.lifecycle import LeadStatus, assert_transition, find_duplicates
from infrastructure.database.models.leads import Lead, LeadDuplicateCandidate
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span
from shared.exceptions import Conflict, NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.leads.lifecycle_ops")

#: Fields the survivor may inherit when it has nothing of its own.
FILLABLE = (
    "last_name",
    "email",
    "phone",
    "source_channel",
    "qualification_score",
    "category",
    "assignee_id",
    "branch_id",
    "team_id",
)

MAX_SCAN = 5000


async def _load(
    session: Any, tenant_id: UUID, lead_id: UUID, *, include_deleted: bool = False
) -> Lead:
    statement = select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant_id)
    if not include_deleted:
        statement = statement.where(Lead.deleted_at.is_(None))
    lead: Lead | None = (await session.execute(statement)).scalar_one_or_none()
    if lead is None:
        raise NotFound("That lead does not exist.")
    return lead


def _row(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "email": lead.email,
        "phone": lead.phone,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "source": lead.source,
    }


async def deduplicate(
    *,
    tenant_id: UUID,
    actor_id: UUID,  # noqa: ARG001
    lead_id: UUID,
    persist: bool = True,
) -> dict[str, Any]:
    """Score candidates and record them, so a human can decide later.

    Recording rather than auto-merging is the point: an automatic merge on a
    fuzzy name match destroys data that nobody asked it to touch.
    """
    with start_span("lead deduplicate", attributes={"tenant.id": str(tenant_id)}):
        async with tenant_session(tenant_id) as session:
            lead = await _load(session, tenant_id, lead_id)
            others = (
                (
                    await session.execute(
                        select(Lead)
                        .where(
                            Lead.tenant_id == tenant_id,
                            Lead.id != lead_id,
                            Lead.deleted_at.is_(None),
                            Lead.merged_into_id.is_(None),
                        )
                        .limit(MAX_SCAN)
                    )
                )
                .scalars()
                .all()
            )

            candidates = find_duplicates(_row(lead), [_row(other) for other in others])

            if persist:
                # Compared as strings, because `DuplicateCandidate.lead_id` is one
                # and the column is a UUID. A set of UUIDs never contains a str, so
                # this guard silently matched nothing and the second run of a
                # deduplication violated the `lead_candidate` unique constraint
                # instead of being the no-op it is supposed to be.
                existing = {
                    str(row.candidate_lead_id)
                    for row in (
                        await session.execute(
                            select(LeadDuplicateCandidate).where(
                                LeadDuplicateCandidate.tenant_id == tenant_id,
                                LeadDuplicateCandidate.lead_id == lead_id,
                            )
                        )
                    )
                    .scalars()
                    .all()
                }
                for candidate in candidates:
                    if candidate.lead_id in existing:
                        continue
                    session.add(
                        LeadDuplicateCandidate(
                            id=uuid7(),
                            tenant_id=tenant_id,
                            lead_id=lead_id,
                            candidate_lead_id=candidate.lead_id,
                            match_reason=candidate.match_reason,
                            confidence=candidate.confidence,
                            resolution="pending",
                        )
                    )

            return {
                "lead_id": str(lead_id),
                "scanned": len(others),
                "candidates": [
                    {
                        "lead_id": str(c.lead_id),
                        "match_reason": c.match_reason,
                        "confidence": c.confidence,
                    }
                    for c in candidates
                ],
            }


async def merge_leads(
    *, tenant_id: UUID, actor_id: UUID, survivor_id: UUID, loser_id: UUID
) -> dict[str, Any]:
    """Fold `loser` into `survivor`. One transaction, fully audited."""
    if survivor_id == loser_id:
        raise ValidationError("A lead cannot be merged into itself.")

    with start_span("lead merge", attributes={"tenant.id": str(tenant_id)}):
        async with tenant_session(tenant_id) as session:
            survivor = await _load(session, tenant_id, survivor_id)
            loser = await _load(session, tenant_id, loser_id)

            if loser.status == LeadStatus.CONVERTED.value:
                raise Conflict(
                    "That lead was already converted; merging would orphan the contact.",
                    details={"lead_id": str(loser_id)},
                )
            if survivor.merged_into_id is not None:
                raise Conflict("The surviving lead was itself already merged away.")

            filled: dict[str, Any] = {}
            for field_name in FILLABLE:
                if getattr(survivor, field_name, None) in (None, ""):
                    value = getattr(loser, field_name, None)
                    if value not in (None, ""):
                        setattr(survivor, field_name, value)
                        filled[field_name] = str(value)

            # Capture is merged the same way round: the survivor's keys win.
            merged_capture = {**(loser.capture or {}), **(survivor.capture or {})}
            survivor.capture = merged_capture
            survivor.utm = {**(loser.utm or {}), **(survivor.utm or {})}
            survivor.updated_by = actor_id
            survivor.version += 1

            # Source events are deliberately NOT re-pointed at the survivor.
            # `app.lead_source_events` is append-only at the database level, so the
            # UPDATE that used to be here could only ever raise and took the whole
            # merge down with it. It is also the wrong thing to want: the event
            # records what arrived and which record it created, and the loser is
            # kept and stamped with `merged_into_id`, so the attribution is still
            # reachable from the survivor without rewriting history.

            loser.merged_into_id = survivor_id
            loser.status = LeadStatus.ARCHIVED.value
            loser.deleted_at = utcnow()
            loser.updated_by = actor_id
            loser.version += 1

            await session.execute(
                update(LeadDuplicateCandidate)
                .where(
                    LeadDuplicateCandidate.tenant_id == tenant_id,
                    LeadDuplicateCandidate.lead_id.in_([survivor_id, loser_id]),
                )
                .values(resolution="merged", resolved_by=actor_id)
            )

            recorder = AuditRecorder(session)
            recorder.record(
                action="lead.merged",
                resource_type="lead",
                resource_id=survivor_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                old_values={"merged_from": str(loser_id)},
                new_values={"filled_fields": sorted(filled), "version": survivor.version},
            )
            recorder.record(
                action="lead.merged_away",
                resource_type="lead",
                resource_id=loser_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                new_values={"merged_into_id": str(survivor_id), "status": "archived"},
            )

            result = {
                "survivor_id": str(survivor_id),
                "merged_id": str(loser_id),
                "filled_fields": sorted(filled),
                "version": survivor.version,
            }

    logger.info("lead_merged", tenant_id=str(tenant_id), survivor=str(survivor_id))
    return result


async def disqualify_lead(
    *, tenant_id: UUID, actor_id: UUID, lead_id: UUID, reason: str
) -> dict[str, Any]:
    """Close a lead with a stated reason. Reversible by `restore_lead`."""
    cleaned = reason.strip()
    if len(cleaned) < 3:
        # An unexplained disqualification is indistinguishable from a mis-click
        # three months later, when someone asks why the pipeline dropped.
        raise ValidationError("Give a reason for disqualifying this lead.")

    async with tenant_session(tenant_id) as session:
        lead = await _load(session, tenant_id, lead_id)
        # The reason has to reach the state machine, not just be validated here:
        # `DISQUALIFIED` is in `REQUIRES_REASON`, so without it every well-formed
        # disqualification was refused as though no reason had been given.
        assert_transition(lead.status, LeadStatus.DISQUALIFIED, reason=cleaned)

        before = {"status": lead.status}
        lead.status = LeadStatus.DISQUALIFIED.value
        lead.disqualify_reason = cleaned[:200]
        lead.updated_by = actor_id
        lead.version += 1

        AuditRecorder(session).record(
            action="lead.disqualified",
            resource_type="lead",
            resource_id=lead_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            old_values=before,
            new_values={"status": "disqualified", "reason": cleaned[:200]},
        )
        return {
            "id": str(lead_id),
            "status": lead.status,
            "disqualify_reason": lead.disqualify_reason,
            "version": lead.version,
        }


async def restore_lead(*, tenant_id: UUID, actor_id: UUID, lead_id: UUID) -> dict[str, Any]:
    """Reopen a disqualified or archived lead.

    A converted lead is not restorable: a contact and possibly a deal already
    exist downstream, and reopening the lead would create a second source of
    truth for the same relationship.
    """
    async with tenant_session(tenant_id) as session:
        lead = await _load(session, tenant_id, lead_id, include_deleted=True)

        if lead.status == LeadStatus.CONVERTED.value:
            raise Conflict(
                "That lead was converted. Work with the contact it became.",
                details={"contact_id": str(lead.converted_contact_id or "")},
            )
        if lead.merged_into_id is not None:
            raise Conflict(
                "That lead was merged into another one.",
                details={"survivor_id": str(lead.merged_into_id)},
            )
        if lead.status not in (LeadStatus.DISQUALIFIED.value, LeadStatus.ARCHIVED.value):
            raise Conflict("That lead is already open.", details={"status": lead.status})

        before = {"status": lead.status, "archived": lead.deleted_at is not None}
        lead.status = LeadStatus.NEW.value
        lead.disqualify_reason = None
        lead.deleted_at = None
        lead.updated_by = actor_id
        lead.version += 1

        AuditRecorder(session).record(
            action="lead.restored",
            resource_type="lead",
            resource_id=lead_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            old_values=before,
            new_values={"status": lead.status},
        )
        return {"id": str(lead_id), "status": lead.status, "version": lead.version}


async def duplicate_candidates(*, tenant_id: UUID, lead_id: UUID) -> list[dict[str, Any]]:
    """Recorded candidates, newest first, with the counterpart's headline fields."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                select(LeadDuplicateCandidate, Lead)
                .join(Lead, Lead.id == LeadDuplicateCandidate.candidate_lead_id, isouter=True)
                .where(
                    LeadDuplicateCandidate.tenant_id == tenant_id,
                    LeadDuplicateCandidate.lead_id == lead_id,
                )
                .order_by(LeadDuplicateCandidate.confidence.desc())
            )
        ).all()

    return [
        {
            "id": str(candidate.id),
            "candidate_lead_id": str(candidate.candidate_lead_id),
            "match_reason": candidate.match_reason,
            "confidence": candidate.confidence,
            "resolution": candidate.resolution,
            "candidate": (
                {
                    "first_name": other.first_name,
                    "last_name": other.last_name,
                    "email": other.email,
                    "phone": other.phone,
                    "status": other.status,
                    # A prospecting record often has a business and a phone and
                    # nothing else. Without this the panel had to fall back to
                    # "Unknown record", which tells the reviewer nothing about the
                    # thing they are being asked to merge.
                    "company": (
                        str(other.capture.get("company"))
                        if isinstance(other.capture, dict) and other.capture.get("company")
                        else None
                    ),
                }
                if other is not None
                else None
            ),
        }
        for candidate, other in rows
    ]


async def pending_duplicate_count(*, tenant_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(LeadDuplicateCandidate)
                    .where(
                        LeadDuplicateCandidate.tenant_id == tenant_id,
                        LeadDuplicateCandidate.resolution == "pending",
                    )
                )
            ).scalar_one()
        )
