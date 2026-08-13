"""Recording the moment a prospect was first answered.

Called from inside whichever unit of work wrote the evidence, so the timestamp and
the activity that justifies it land together or not at all. A `first_response_at`
with no logged contact behind it is exactly the kind of number this session exists
to eliminate.

Three properties matter more than the code is long:

* **Idempotent.** The update is conditional on the column still being null, in
  SQL. Two people logging a call at the same instant cannot both win, because the
  database decides, not a read-then-write in Python.
* **Never overwritten.** The same `WHERE ... IS NULL` guarantees the *first*
  response is kept. The tenth call does not restate the clock.
* **No retrospective invention.** Nothing here backfills. A prospect that was
  never answered stays unanswered, and the dashboard keeps telling the truth about
  it.

The channel/direction rule itself lives in `domain.leads.first_response` so a real
provider event can ask the same question later without this function changing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from domain.base import DomainEvent
from domain.events.catalog import LEAD_FIRST_RESPONSE_RECORDED
from domain.leads.first_response import qualifies_as_first_response
from infrastructure.logging.setup import get_logger

logger = get_logger("application.leads.first_response")


async def record_first_response(
    uow: Any,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    channel: str,
    direction: str,
    occurred_at: datetime,
    actor_id: UUID | None,
    source: str,
    outcome: str | None = None,
) -> bool:
    """Stamp first response if this contact qualifies and none is recorded yet.

    `uow` is an open unit of work whose session is already scoped to the tenant.
    Returns True only when this call is what set the timestamp, so the caller can
    emit an event exactly once.

    `outcome` is passed straight through to the domain rule and never interpreted
    here. A missed call, a scheduled meeting and a send the provider rejected all
    arrive as ordinary calls to this function and are refused there, which is why
    there is no second opinion about them anywhere in the codebase.
    """
    if not qualifies_as_first_response(channel=channel, direction=direction, outcome=outcome):
        return False

    from sqlalchemy import update

    from infrastructure.database.models.leads import Lead

    # The tenant predicate is repeated here even though row-level security already
    # applies it. A conditional UPDATE that reaches the wrong tenant's row would
    # be silent, and defence in depth costs one line.
    result = await uow.session.execute(
        update(Lead)
        .where(
            Lead.id == lead_id,
            Lead.tenant_id == tenant_id,
            Lead.first_response_at.is_(None),
        )
        .values(first_response_at=occurred_at)
    )

    if not result.rowcount:
        # Either already answered, or not visible to this caller. Both mean "do
        # nothing", and neither is an error.
        return False

    uow.collect(
        DomainEvent(
            event_type=LEAD_FIRST_RESPONSE_RECORDED,
            tenant_id=tenant_id,
            resource_type="lead",
            resource_id=lead_id,
            actor_id=actor_id,
            payload={
                "channel": channel,
                "direction": direction,
                "outcome": outcome,
                "source": source,
                "occurred_at": occurred_at.isoformat(),
            },
        )
    )
    logger.info(
        "lead_first_response_recorded",
        tenant_id=str(tenant_id),
        lead_id=str(lead_id),
        channel=channel,
        source=source,
    )
    return True
