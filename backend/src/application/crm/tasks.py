"""Tasks: the follow-ups hanging off a contact, account or deal.

Small on purpose. A task is a title, an owner, a due date and a status; the
interesting behaviour is that it can be attached to any CRM record and that
"what is overdue" has to be a server-side question, because a client that decides
overdueness from its own clock will disagree with the audit trail.

Statuses follow the table's check constraint exactly. A completed task records
*when*, so "closed on time" is answerable later rather than inferred from the row
still existing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from domain.base import DomainEvent
from domain.events.catalog import TASK_COMPLETED, TASK_CREATED, TASK_UPDATED
from infrastructure.logging.setup import get_logger
from shared.exceptions import NotFound, ValidationError
from shared.pagination import Page
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.crm.tasks")

STATUSES = ("open", "in_progress", "completed", "cancelled")
OPEN_STATUSES = frozenset({"open", "in_progress"})
PRIORITIES = ("low", "normal", "high", "urgent")
# A task may hang off any of these, or off nothing at all. Leads are included
# because the follow-up that stops a prospect going cold is created before the
# prospect is ever converted to a contact.
ENTITY_TYPES = frozenset({"contact", "account", "deal", "lead"})


def serialize_task(
    row: Any, *, assignee_name: str | None = None, now: datetime | None = None
) -> dict[str, Any]:
    moment = now or utcnow()
    is_open = row.status in OPEN_STATUSES
    return {
        "id": str(row.id),
        "title": row.title,
        "description": row.description,
        "status": row.status,
        "priority": row.priority,
        "entity_type": row.entity_type,
        "entity_id": str(row.entity_id) if row.entity_id else None,
        "assignee_id": str(row.assignee_id) if row.assignee_id else None,
        "assignee_name": assignee_name,
        "due_at": row.due_at.isoformat() if row.due_at else None,
        # Decided here, against the server clock. A client deciding this from its
        # own clock would disagree with the audit trail.
        "is_overdue": bool(is_open and row.due_at is not None and row.due_at < moment),
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "is_next_action": row.is_next_action,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@dataclass(slots=True)
class TaskService(_PrincipalScoped):
    """Follow-ups, optionally attached to a CRM record."""

    async def _assert_parent_visible(self, entity_type: str | None, entity_id: UUID | None) -> None:
        """A task on a record the caller cannot see must not be creatable."""
        if entity_type is None and entity_id is None:
            return
        if entity_type is None or entity_id is None:
            raise ValidationError("An entity type and id must be supplied together.")
        if entity_type not in ENTITY_TYPES:
            raise ValidationError(f"Unsupported entity type: {entity_type!r}.")

        from application.crm.deals import DealService
        from application.crm.service import AccountService, ContactService
        from application.leads.service import LeadService

        factory: Any = {
            "contact": ContactService,
            "account": AccountService,
            "deal": DealService,
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

    async def _assignee_names(self, session: Any, ids: set[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        from sqlalchemy import select

        from infrastructure.database.models.users import User

        rows = await session.execute(
            select(User.id, User.full_name).where(
                User.id.in_(ids), User.tenant_id == self.tenant_id
            )
        )
        return {row[0]: row[1] for row in rows}

    async def list_tasks(
        self,
        query: Any,
        *,
        status: str | None = None,
        mine: bool = False,
        overdue: bool = False,
    ) -> Page:
        from infrastructure.database.models.crm import Task
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class TaskRepository(TenantRepository[Task]):
            model = Task

        if status and status not in STATUSES:
            raise ValidationError(f"Unknown status: {status!r}.")

        async with tenant_session(self.tenant_id) as session:
            repo = TaskRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if status:
                stmt = stmt.where(Task.status == status)
            if mine:
                stmt = stmt.where(Task.assignee_id == self.user_id)
            if overdue:
                # Filtered in SQL against the database clock, for the same reason
                # `is_overdue` is computed server-side.
                stmt = stmt.where(
                    Task.due_at.is_not(None),
                    Task.due_at < utcnow(),
                    Task.status.in_(tuple(OPEN_STATUSES)),
                )
            stmt = stmt.order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())

            page = await repo.paginate_cursor(
                self.permissions_scope(), stmt, cursor=query.cursor, page_size=query.page_size
            )
            names = await self._assignee_names(
                session, {t.assignee_id for t in page.items if t.assignee_id}
            )
            page.items = [
                serialize_task(t, assignee_name=names.get(t.assignee_id) if t.assignee_id else None)
                for t in page.items
            ]
            return page

    async def for_entity(self, entity_type: str, entity_id: UUID) -> list[dict[str, Any]]:
        """Tasks attached to one record, open ones first."""
        await self._assert_parent_visible(entity_type, entity_id)

        from infrastructure.database.models.crm import Task
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class TaskRepository(TenantRepository[Task]):
            model = Task

        async with tenant_session(self.tenant_id) as session:
            repo = TaskRepository(session, self.tenant_id)
            stmt = (
                repo.scoped_query(self.permissions_scope())
                .where(Task.entity_type == entity_type, Task.entity_id == entity_id)
                .order_by(Task.due_at.asc().nulls_last(), Task.created_at.desc())
                .limit(100)
            )
            rows = list((await session.execute(stmt)).scalars().all())
            names = await self._assignee_names(
                session, {t.assignee_id for t in rows if t.assignee_id}
            )
            entries = [
                serialize_task(t, assignee_name=names.get(t.assignee_id) if t.assignee_id else None)
                for t in rows
            ]
        entries.sort(key=lambda e: (e["status"] not in OPEN_STATUSES, e["due_at"] or "9999"))
        return entries

    async def get(self, task_id: UUID) -> dict[str, Any]:
        from infrastructure.database.models.crm import Task
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class TaskRepository(TenantRepository[Task]):
            model = Task

        async with tenant_session(self.tenant_id) as session:
            task = await TaskRepository(session, self.tenant_id).get_scoped(
                task_id, self.permissions_scope()
            )
            if task is None:
                raise NotFound("Task not found.")
            names = await self._assignee_names(
                session, {task.assignee_id} if task.assignee_id else set()
            )
            return serialize_task(
                task, assignee_name=names.get(task.assignee_id) if task.assignee_id else None
            )

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Task
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        title = str(payload.get("title", "")).strip()
        if not title:
            raise ValidationError("A title is required.")
        priority = str(payload.get("priority") or "normal")
        if priority not in PRIORITIES:
            raise ValidationError(f"Unknown priority. Expected one of: {', '.join(PRIORITIES)}.")

        entity_type = payload.get("entity_type")
        entity_id = payload.get("entity_id")
        await self._assert_parent_visible(entity_type, entity_id)

        task_id = uuid7()
        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            uow.session.add(
                Task(
                    id=task_id,
                    tenant_id=self.tenant_id,
                    title=title[:250],
                    description=payload.get("description"),
                    entity_type=entity_type,
                    entity_id=entity_id,
                    assignee_id=payload.get("assignee_id") or self.user_id,
                    due_at=payload.get("due_at"),
                    priority=priority,
                    status="open",
                    is_next_action=bool(payload.get("is_next_action", False)),
                    source="manual",
                    created_by=self.user_id,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="task.create",
                resource_type="task",
                resource_id=task_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"title": title, "entity_id": str(entity_id) if entity_id else None},
            )
            uow.collect(
                DomainEvent(
                    event_type=TASK_CREATED,
                    tenant_id=self.tenant_id,
                    resource_type="task",
                    resource_id=task_id,
                    actor_id=self.user_id,
                    payload={"entity_type": entity_type, "priority": priority},
                )
            )

        logger.info("task_created", tenant_id=str(self.tenant_id), task_id=str(task_id))
        return await self.get(task_id)

    async def update(
        self, task_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder, diff_for_audit
        from infrastructure.database.models.crm import Task
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class TaskRepository(TenantRepository[Task]):
            model = Task

        if changes.get("status") and changes["status"] not in STATUSES:
            raise ValidationError(f"Unknown status. Expected one of: {', '.join(STATUSES)}.")
        if changes.get("priority") and changes["priority"] not in PRIORITIES:
            raise ValidationError(f"Unknown priority. Expected one of: {', '.join(PRIORITIES)}.")

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = TaskRepository(uow.session, self.tenant_id)
            task = await repo.get_scoped_or_404(task_id, self.permissions_scope())
            before = serialize_task(task)

            for field_name, value in changes.items():
                # due_at and assignee_id are explicitly clearable.
                if field_name in {"due_at", "assignee_id"} or value is not None:
                    setattr(task, field_name, value)

            # Completion time is set by the server, never accepted from a client:
            # "closed on time" has to be answerable from the record itself.
            if task.status == "completed" and task.completed_at is None:
                task.completed_at = utcnow()
            elif task.status in OPEN_STATUSES:
                task.completed_at = None

            await repo.bump_version(task, expected_version)
            task.updated_by = self.user_id
            after = serialize_task(task)
            completed_now = before["status"] != "completed" and task.status == "completed"

            old_values, new_values = diff_for_audit(before, after)
            AuditRecorder(uow.session).record(
                action="task.complete" if completed_now else "task.update",
                resource_type="task",
                resource_id=task_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values=old_values,
                new_values=new_values,
            )
            uow.collect(
                DomainEvent(
                    event_type=TASK_COMPLETED if completed_now else TASK_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="task",
                    resource_id=task_id,
                    actor_id=self.user_id,
                    payload={
                        "changed": sorted(changes),
                        "entity_type": task.entity_type,
                        "entity_id": str(task.entity_id) if task.entity_id else None,
                    },
                )
            )
        return await self.get(task_id)
