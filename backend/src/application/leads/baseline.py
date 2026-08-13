"""The honest "before" picture, captured once, at the start of a pilot.

A shadow pilot is worth nothing without a starting point. If the first numbers a
business ever sees are taken three weeks in, every later comparison is against a
half-remembered anecdote, and the temptation to describe any movement as an
improvement becomes overwhelming.

So this captures a **starting baseline** and calls it exactly that. What it is
not, and must never be presented as:

* it is **not** an improvement, a gain, or a performance figure. It is one
  photograph, taken on day one, of a backlog that already existed;
* it is **not** a trend. Nothing here stores a series, because two points taken a
  week apart during a pilot's first fortnight would say more about who was on
  leave than about the product;
* it is **not** a revenue number and cannot become one. Nothing in this file
  touches money.

Every value comes from `application.leads.metrics`, the same code the Today page
reads, computed in the caller's scope. That is deliberate: a baseline that used
its own queries could disagree with the dashboard, and then neither would be
believed. A baseline figure must always be reconcilable by clicking through to the
records behind it.

Where there is not enough history to say something truthful - no answered
prospects yet, so no median response time - the value is `None` and the reason is
recorded beside it. Inventing a plausible number here would corrupt the one thing
the pilot exists to establish.

Stored in `tenants.settings`, which is already JSONB, following the same precedent
as the demo manifest: no migration, and no second table to keep in step.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from application.crm.service import _PrincipalScoped
from infrastructure.logging.setup import get_logger
from shared.exceptions import ValidationError
from shared.utils.timeutil import utcnow

logger = get_logger("application.leads.baseline")

BASELINE_KEY: Final = "starting_baseline"
SUPERSEDED_KEY: Final = "starting_baseline_superseded"

#: Bumped when a metric's *meaning* changes, so an old baseline is never compared
#: against a differently-defined new number without somebody noticing. Session 5
#: is v1: the first version in which a missed call and a scheduled meeting do not
#: count as answering a prospect.
DEFINITION_VERSION: Final = "v1"

#: What each figure means, stored with the values. A baseline read six months
#: later by somebody who was not in the room has to explain itself.
DEFINITIONS: Final[dict[str, str]] = {
    "open_total": "Prospects still being worked: new, contacted, qualified or nurturing.",
    "awaiting_first_response": (
        "Open prospects nobody has genuinely replied to yet. A missed call or a "
        "meeting still in the diary does not count as a reply."
    ),
    "unassigned": "Open prospects with no named owner.",
    "no_next_action": "Open prospects with no follow-up scheduled.",
    "overdue_follow_ups": "Follow-ups whose due date has passed and are still open.",
    "answered_total": "Prospects that have been genuinely replied to at least once.",
    "median_first_response_minutes": (
        "Middle time from enquiry to genuine first reply. Median, not average, so "
        "one forgotten prospect cannot distort it."
    ),
    "longest_wait_minutes": "The longest any open prospect has been waiting for a first reply.",
}

#: The figures a baseline records. Kept explicit rather than "whatever the metrics
#: service returned", so adding a metric later cannot silently change what an
#: already-captured baseline claims to have measured.
CAPTURED_METRICS: Final[tuple[str, ...]] = tuple(DEFINITIONS)


@dataclass(slots=True)
class BaselineService(_PrincipalScoped):
    """Capture and read one tenant's starting baseline."""

    async def _current_metrics(self) -> dict[str, Any]:
        from application.leads.metrics import LeadMetricsService

        metrics_service = LeadMetricsService(
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
        )
        metrics = await metrics_service.response_metrics()
        metrics["overdue_follow_ups"] = await metrics_service.overdue_task_count()
        return metrics

    @staticmethod
    def _gaps(metrics: dict[str, Any]) -> list[str]:
        """Where the workspace cannot yet support a truthful figure.

        Named in plain words and shown to the owner. "Not enough history" is a
        real, useful answer; a zero pretending to be one is not.
        """
        gaps: list[str] = []
        if not metrics.get("open_total"):
            gaps.append("No open prospects yet, so there is nothing to measure.")
        if metrics.get("median_first_response_minutes") is None:
            gaps.append(
                "No prospect has been replied to yet, so there is no typical "
                "response time to record."
            )
        if metrics.get("longest_wait_minutes") is None and metrics.get("open_total"):
            gaps.append("Every open prospect has already been replied to.")
        return gaps

    async def preview(self) -> dict[str, Any]:
        """What a baseline captured right now would say. Stores nothing."""
        metrics = await self._current_metrics()
        return {
            "definition_version": DEFINITION_VERSION,
            "definitions": DEFINITIONS,
            "metrics": {key: metrics.get(key) for key in CAPTURED_METRICS},
            "insufficient_data": self._gaps(metrics),
        }

    async def read(self) -> dict[str, Any] | None:
        """The stored starting baseline, or None when none was ever captured."""
        from sqlalchemy import select

        from infrastructure.database.models.tenancy import Tenant
        from infrastructure.database.session import tenant_session

        async with tenant_session(self.tenant_id) as session:
            settings = (
                await session.execute(select(Tenant.settings).where(Tenant.id == self.tenant_id))
            ).scalar_one_or_none()

        stored = (settings or {}).get(BASELINE_KEY)
        return dict(stored) if stored else None

    async def capture(self, *, replace: bool = False, note: str | None = None) -> dict[str, Any]:
        """Photograph the current state and keep it.

        Refuses to overwrite silently. A starting baseline that quietly moves is
        not a baseline, and a pilot that recaptured one by accident would have no
        way of knowing it had happened.
        """
        from sqlalchemy import select, update

        from infrastructure.database.models.tenancy import Tenant
        from infrastructure.database.session import tenant_session

        existing = await self.read()
        if existing and not replace:
            raise ValidationError(
                "This workspace already has a starting baseline. Capturing another "
                "would replace the only 'before' picture you have.",
                details={"captured_at": existing.get("captured_at")},
            )

        metrics = await self._current_metrics()
        captured = {
            "captured_at": utcnow().isoformat(),
            "captured_by": str(self.user_id),
            "definition_version": DEFINITION_VERSION,
            "definitions": DEFINITIONS,
            "metrics": {key: metrics.get(key) for key in CAPTURED_METRICS},
            "insufficient_data": self._gaps(metrics),
            "note": (note or "").strip() or None,
            # Said once, here, so that anything rendering this cannot present it
            # as a result. It is the state the business was already in.
            "kind": "starting_baseline",
        }

        async with tenant_session(self.tenant_id) as session:
            current = (
                await session.execute(select(Tenant.settings).where(Tenant.id == self.tenant_id))
            ).scalar_one()
            settings = dict(current or {})

            if existing:
                # Never discarded. If somebody replaced a baseline there is now a
                # record that they did, which is the only honest way to allow it.
                superseded = list(settings.get(SUPERSEDED_KEY) or [])
                superseded.append(existing)
                settings[SUPERSEDED_KEY] = superseded[-10:]

            settings[BASELINE_KEY] = captured
            # Core update: `Tenant` carries an optimistic version column, and
            # bumping it here would fail an unrelated concurrent save.
            await session.execute(
                update(Tenant).where(Tenant.id == self.tenant_id).values(settings=settings)
            )

        logger.info(
            "starting_baseline_captured",
            tenant_id=str(self.tenant_id),
            replaced=bool(existing),
            definition_version=DEFINITION_VERSION,
        )
        return captured

    async def reconcile(self) -> dict[str, Any]:
        """Compare the stored baseline against the records as they stand now.

        Not a trend. Its purpose is to let anybody check that the stored figures
        were real when they were taken and still refer to the same definitions -
        the difference between a measurement and a decoration.
        """
        stored = await self.read()
        if stored is None:
            return {"has_baseline": False}

        live = await self._current_metrics()
        return {
            "has_baseline": True,
            "captured_at": stored.get("captured_at"),
            "definition_version": stored.get("definition_version"),
            "definitions_current": stored.get("definition_version") == DEFINITION_VERSION,
            "baseline": stored.get("metrics", {}),
            "current": {key: live.get(key) for key in CAPTURED_METRICS},
        }
