"""The leakage numbers, computed once, server-side, over the caller's own scope.

Every figure here is a count or a statistic over rows the caller can actually
open. That is the constraint the whole file is written to satisfy: if a number
cannot be reconciled by clicking through to the records behind it, it should not
be on the screen.

Two consequences worth stating:

* **Scope is applied in the query.** A salesperson with `self` scope sees the
  leakage in their own book, not the company's. Filtering after fetching would
  leak the size of the tenant even when the rows stay hidden.
* **The clock is the server's.** "Overdue" and "waiting since" are decided here,
  the same way `is_overdue` is decided for a task, so two screens cannot disagree
  because one machine's time drifted.

Median rather than mean, on purpose. One prospect answered after three weeks
drags a mean far enough to make a good week look bad, and an SME owner correctly
stops believing a number that behaves like that.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from application.crm.service import _PrincipalScoped
from shared.utils.timeutil import utcnow

# Statuses that are still live work. A converted or disqualified prospect is not
# "waiting for a reply" - it is finished, and counting it would make the backlog
# look permanently worse than it is.
OPEN_STATUSES = ("new", "contacted", "qualified", "nurturing")


def _minutes_between(start: datetime, end: datetime) -> int:
    return max(0, int((end - start).total_seconds() // 60))


def _median(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) // 2


@dataclass(slots=True)
class LeadMetricsService(_PrincipalScoped):
    """Operational counts for the follow-up workflow."""

    async def response_metrics(self) -> dict[str, Any]:
        """Awaiting-reply, ownership, next-action and response-time figures."""
        from sqlalchemy import select

        from infrastructure.database.models.crm import Task
        from infrastructure.database.models.leads import Lead
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class LeadRepository(TenantRepository[Lead]):
            model = Lead

        now = utcnow()

        async with tenant_session(self.tenant_id) as session:
            repo = LeadRepository(session, self.tenant_id)
            scoped = repo.scoped_query(self.permissions_scope())

            open_leads = list(
                (await session.execute(scoped.where(Lead.status.in_(OPEN_STATUSES))))
                .scalars()
                .all()
            )

            # Which open prospects have an open follow-up. One query, not one per
            # prospect: this runs on every dashboard load.
            lead_ids = [lead.id for lead in open_leads]
            with_next_action: set[UUID] = set()
            if lead_ids:
                rows = await session.execute(
                    select(Task.entity_id)
                    .where(
                        Task.entity_type == "lead",
                        Task.entity_id.in_(lead_ids),
                        Task.status.in_(("open", "in_progress")),
                        Task.deleted_at.is_(None),
                    )
                    .group_by(Task.entity_id)
                )
                with_next_action = {row[0] for row in rows}

            # Response times are measured across every answered lead in scope,
            # including converted ones: excluding them would quietly drop the
            # best-handled prospects out of the statistic and flatter the median.
            # Built from the same scoped query, so a self-scoped salesperson gets
            # their own median rather than the company's.
            answered = list(
                (
                    await session.execute(
                        repo.scoped_query(self.permissions_scope()).where(
                            Lead.first_response_at.is_not(None)
                        )
                    )
                )
                .scalars()
                .all()
            )
            response_minutes = [
                _minutes_between(lead.created_at, lead.first_response_at)
                for lead in answered
                if lead.created_at and lead.first_response_at
            ]

        awaiting = [lead for lead in open_leads if lead.first_response_at is None]
        unassigned = [lead for lead in open_leads if lead.assignee_id is None]
        no_next_action = [lead for lead in open_leads if lead.id not in with_next_action]

        waits = [_minutes_between(lead.created_at, now) for lead in awaiting if lead.created_at]

        return {
            "open_total": len(open_leads),
            "awaiting_first_response": len(awaiting),
            "unassigned": len(unassigned),
            "no_next_action": len(no_next_action),
            "answered_total": len(response_minutes),
            "median_first_response_minutes": _median(response_minutes),
            "longest_wait_minutes": max(waits) if waits else None,
            "measured_at": now.isoformat(),
        }

    async def overdue_task_count(self) -> int:
        """Open follow-ups whose due date has passed, in the caller's scope."""
        from sqlalchemy import func, select

        from infrastructure.database.models.crm import Task
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class TaskRepository(TenantRepository[Task]):
            model = Task

        async with tenant_session(self.tenant_id) as session:
            repo = TaskRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope()).where(
                Task.due_at.is_not(None),
                Task.due_at < utcnow(),
                Task.status.in_(("open", "in_progress")),
            )
            total = await session.execute(
                select(func.count()).select_from(stmt.subquery().alias("overdue_tasks"))
            )
            return int(total.scalar_one())
