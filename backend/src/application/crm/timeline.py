"""Activities and notes: the timeline hanging off a contact or an account.

Two record types with deliberately different rules, which is why they share a
service rather than a table:

* **Activities are append-only.** The model says so, and the API offers no update
  or delete. A logged call that can be rewritten later is not a record of what
  happened.
* **Notes are editable, by their author only.** Anyone with `note:update` could
  otherwise rewrite a colleague's note and the timeline would attribute the new
  text to the original author.

The parent record is always resolved through the scoped repository *first*. That
is what makes a timeline on another tenant's contact a 404 rather than an empty
list -- an empty list would confirm the id exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.base import DomainEvent
from domain.events.catalog import ACTIVITY_LOGGED, NOTE_ADDED, NOTE_UPDATED
from domain.leads.first_response import (
    DIRECTIONS,
    OUTCOMES_BY_CHANNEL,
    default_direction,
    describe_outcome,
    is_valid_outcome,
)
from infrastructure.logging.setup import get_logger
from shared.exceptions import Forbidden, NotFound, ValidationError
from shared.utils.ids import uuid7

logger = get_logger("application.crm.timeline")

# The subset of the model's ACTIVITY_TYPES a human may log by hand. `system` and
# `status_change` are written by the platform, so accepting them from a client
# would let anyone forge a system record.
LOGGABLE_TYPES = frozenset({"call", "email", "meeting", "note", "task", "whatsapp"})
ENTITY_TYPES = frozenset({"contact", "account", "lead"})


def serialize_activity(row: Any, *, actor_name: str | None = None) -> dict[str, Any]:
    return {
        "kind": "activity",
        "id": str(row.id),
        "activity_type": row.activity_type,
        "subject": row.subject,
        "body": row.body,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "actor_id": str(row.actor_id) if row.actor_id else None,
        "actor_name": actor_name,
        "actor_type": row.actor_type,
        # Shown in the timeline so a reader can tell "we called them" from "they
        # called us" - the distinction the first-response rule turns on.
        "direction": (row.metadata_json or {}).get("direction"),
        # And what actually happened, which is the other half of that rule. A
        # reader who sees "no answer" beside a prospect still marked as waiting
        # can tell at a glance that the dashboard is right rather than stuck.
        "outcome": (row.metadata_json or {}).get("outcome"),
        "outcome_label": describe_outcome((row.metadata_json or {}).get("outcome")),
        "editable": False,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def serialize_note(
    row: Any, *, actor_name: str | None = None, editable: bool = False
) -> dict[str, Any]:
    return {
        "kind": "note",
        "id": str(row.id),
        "body": row.body,
        "is_pinned": row.is_pinned,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id),
        "actor_id": str(row.created_by) if row.created_by else None,
        "actor_name": actor_name,
        "editable": editable,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@dataclass(slots=True)
class TimelineService(_PrincipalScoped):
    """Activities and notes for one contact or account."""

    async def _assert_parent_visible(self, entity_type: str, entity_id: UUID) -> None:
        """404 before anything else if the caller may not see the parent record."""
        if entity_type not in ENTITY_TYPES:
            raise ValidationError(f"Unsupported entity type: {entity_type!r}.")

        from application.crm.service import AccountService, ContactService
        from application.leads.service import LeadService

        # A lead's history is the same table as a contact's, because the point of
        # the model is that converting a prospect does not start a new memory.
        factory: Any = {
            "contact": ContactService,
            "account": AccountService,
            "lead": LeadService,
        }[entity_type]
        service: Any = factory(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        )
        await service.get(entity_id)

    async def _actor_names(self, session: Any, actor_ids: set[UUID]) -> dict[UUID, str]:
        """Resolve display names in one query rather than N+1."""
        if not actor_ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.users import User

        rows = await session.execute(
            select(User.id, User.full_name).where(
                User.id.in_(actor_ids), User.tenant_id == self.tenant_id
            )
        )
        return {row[0]: row[1] for row in rows}

    async def timeline(self, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
        """Activities and notes merged, newest first, pinned notes on top."""
        await self._assert_parent_visible(entity_type, entity_id)

        from sqlalchemy import select

        from infrastructure.database.models.crm import Activity, Note
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            activities = (
                (
                    await session.execute(
                        select(Activity)
                        .where(
                            Activity.entity_type == entity_type,
                            Activity.entity_id == entity_id,
                        )
                        .order_by(Activity.created_at.desc())
                        .limit(200)
                    )
                )
                .scalars()
                .all()
            )
            notes = (
                (
                    await session.execute(
                        select(Note)
                        .where(
                            Note.entity_type == entity_type,
                            Note.entity_id == entity_id,
                            Note.deleted_at.is_(None),
                        )
                        .order_by(Note.created_at.desc())
                        .limit(200)
                    )
                )
                .scalars()
                .all()
            )

            actor_ids = {a.actor_id for a in activities if a.actor_id}
            actor_ids |= {n.created_by for n in notes if n.created_by}
            names = await self._actor_names(session, actor_ids)

            entries = [
                serialize_activity(a, actor_name=names.get(a.actor_id) if a.actor_id else None)
                for a in activities
            ] + [
                serialize_note(
                    n,
                    actor_name=names.get(n.created_by) if n.created_by else None,
                    # Only the author may edit, so the UI must not offer it to
                    # anyone else. The service enforces the same rule again.
                    editable=n.created_by == self.user_id,
                )
                for n in notes
            ]

        entries.sort(
            key=lambda e: (e.get("is_pinned") is True, e["created_at"] or ""), reverse=True
        )
        return entries

    async def log_activity(
        self, entity_type: str, entity_id: UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        await self._assert_parent_visible(entity_type, entity_id)

        activity_type = str(payload.get("activity_type", "note"))
        if activity_type not in LOGGABLE_TYPES:
            raise ValidationError(
                "That activity type cannot be logged by hand.",
                details={"allowed": sorted(LOGGABLE_TYPES)},
            )
        subject = str(payload.get("subject", "")).strip()
        if not subject:
            raise ValidationError("A subject is required.")

        direction = str(payload.get("direction") or default_direction())
        if direction not in DIRECTIONS:
            raise ValidationError(
                "Direction must say whether this went out or came in.",
                details={"allowed": sorted(DIRECTIONS)},
            )

        # Optional, because a note or a task has nothing to report and because
        # every activity written before this existed has none. When it *is* given
        # it must belong to the channel: "a call that was a no-show" is not a
        # record anybody can act on, and silently keeping it would put an outcome
        # in front of the founders that their own dashboard ignores.
        raw_outcome = payload.get("outcome")
        outcome: str | None = str(raw_outcome).strip() or None if raw_outcome else None
        if outcome is not None and not is_valid_outcome(channel=activity_type, outcome=outcome):
            raise ValidationError(
                f"That is not something a {activity_type} can end in.",
                details={"allowed": sorted(OUTCOMES_BY_CHANNEL.get(activity_type, frozenset()))},
            )

        from application.audit.recorder import AuditRecorder
        from application.leads.first_response import record_first_response
        from infrastructure.database.models.crm import Activity
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
        from shared.utils.timeutil import utcnow

        activity_id = uuid7()
        occurred_at = utcnow()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                Activity(
                    id=activity_id,
                    tenant_id=self.tenant_id,
                    activity_type=activity_type,
                    subject=subject[:300],
                    body=payload.get("body"),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    actor_id=self.user_id,
                    actor_type="user",
                    # Direction lives on the record, not only in the decision it
                    # triggered, so "why is this prospect marked answered?" is
                    # answerable from the timeline months later.
                    metadata_json={"direction": direction, "outcome": outcome},
                    created_at=occurred_at,
                )
            )

            # Same transaction as the evidence. A first-response timestamp that
            # could outlive a rolled-back activity is the bug this design exists
            # to prevent.
            if entity_type == "lead":
                await record_first_response(
                    uow,
                    tenant_id=self.tenant_id,
                    lead_id=entity_id,
                    channel=activity_type,
                    direction=direction,
                    outcome=outcome,
                    occurred_at=occurred_at,
                    actor_id=self.user_id,
                    source="activity.log",
                )
            AuditRecorder(uow.session).record(
                action="activity.log",
                resource_type="activity",
                resource_id=activity_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"activity_type": activity_type, "entity_id": str(entity_id)},
            )
            uow.collect(
                DomainEvent(
                    event_type=ACTIVITY_LOGGED,
                    tenant_id=self.tenant_id,
                    resource_type="activity",
                    resource_id=activity_id,
                    actor_id=self.user_id,
                    payload={
                        "activity_type": activity_type,
                        "direction": direction,
                        "outcome": outcome,
                        "entity_type": entity_type,
                        "entity_id": str(entity_id),
                    },
                )
            )

        logger.info("activity_logged", tenant_id=str(self.tenant_id), activity_id=str(activity_id))
        return await self._read_activity(activity_id)

    async def _read_activity(self, activity_id: UUID) -> dict[str, Any]:
        from sqlalchemy import select

        from infrastructure.database.models.crm import Activity
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            row = (
                await session.execute(select(Activity).where(Activity.id == activity_id))
            ).scalar_one_or_none()
            if row is None:
                raise NotFound("Activity not found.")
            names = await self._actor_names(session, {row.actor_id} if row.actor_id else set())
            return serialize_activity(
                row, actor_name=names.get(row.actor_id) if row.actor_id else None
            )

    async def add_note(
        self, entity_type: str, entity_id: UUID, payload: dict[str, Any]
    ) -> dict[str, Any]:
        await self._assert_parent_visible(entity_type, entity_id)

        body = str(payload.get("body", "")).strip()
        if not body:
            raise ValidationError("A note cannot be empty.")

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Note
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        note_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                Note(
                    id=note_id,
                    tenant_id=self.tenant_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    body=body,
                    is_pinned=bool(payload.get("is_pinned", False)),
                    created_by=self.user_id,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="note.create",
                resource_type="note",
                resource_id=note_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"entity_id": str(entity_id)},
            )
            uow.collect(
                DomainEvent(
                    event_type=NOTE_ADDED,
                    tenant_id=self.tenant_id,
                    resource_type="note",
                    resource_id=note_id,
                    actor_id=self.user_id,
                    payload={"entity_type": entity_type, "entity_id": str(entity_id)},
                )
            )

        logger.info("note_added", tenant_id=str(self.tenant_id), note_id=str(note_id))
        return await self._read_note(note_id)

    async def _read_note(self, note_id: UUID) -> dict[str, Any]:
        from sqlalchemy import select

        from infrastructure.database.models.crm import Note
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            row = (
                await session.execute(
                    select(Note).where(Note.id == note_id, Note.deleted_at.is_(None))
                )
            ).scalar_one_or_none()
            if row is None:
                raise NotFound("Note not found.")
            names = await self._actor_names(session, {row.created_by} if row.created_by else set())
            return serialize_note(
                row,
                actor_name=names.get(row.created_by) if row.created_by else None,
                editable=row.created_by == self.user_id,
            )

    async def update_note(
        self, note_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        """Author-only. A colleague's note is not editable at any permission level."""
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Note
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class NoteRepository(TenantRepository[Note]):
            model = Note

        body = changes.get("body")
        if body is not None and not str(body).strip():
            raise ValidationError("A note cannot be empty.")

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = NoteRepository(uow.session, self.tenant_id)
            note = await repo.get(note_id, self.permissions_scope())
            if note is None:
                raise NotFound("Note not found.")
            if note.created_by != self.user_id:
                # Deliberately Forbidden rather than NotFound: the caller can
                # already see this note in the timeline, so pretending it does not
                # exist would be confusing rather than protective.
                raise Forbidden("You can only edit your own notes.")

            before = note.body
            if body is not None:
                note.body = str(body).strip()
            if "is_pinned" in changes and changes["is_pinned"] is not None:
                note.is_pinned = bool(changes["is_pinned"])
            await repo.bump_version(note, expected_version)
            note.updated_by = self.user_id

            AuditRecorder(uow.session).record(
                action="note.update",
                resource_type="note",
                resource_id=note_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values={"body": before},
                new_values={"body": note.body},
            )
            uow.collect(
                DomainEvent(
                    event_type=NOTE_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="note",
                    resource_id=note_id,
                    actor_id=self.user_id,
                    payload={"changed": sorted(changes)},
                )
            )
        return await self._read_note(note_id)
