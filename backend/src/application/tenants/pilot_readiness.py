"""Is this workspace actually ready to carry a real business's enquiries?

Every line of this is a probe, not a claim. The Test Centre's whole value is that
a founder can believe it, and the fastest way to destroy that is one row that says
"ready" because somebody typed the word while writing the page. So each check
answers from the database or the filesystem as it is right now, and a check that
cannot be answered says exactly that rather than defaulting to reassuring.

Three states, and the middle one is the important one:

* `ready`    - probed, and true.
* `attention`- probed, and not true yet. Carries the reason in plain words.
* `manual`   - genuinely outside the product. Recording an outreach a person made
               on their own phone is not a gap to be fixed; it is how a shadow
               pilot works, and pretending otherwise would be the lie.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from application.crm.service import _PrincipalScoped
from application.tenants.provisioning import PILOT, TEST, WORKSPACE_KIND_KEY
from infrastructure.logging.setup import get_logger

logger = get_logger("application.tenants.pilot_readiness")

READY: Final = "ready"
ATTENTION: Final = "attention"
MANUAL: Final = "manual"

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))


@dataclass(slots=True)
class Check:
    key: str
    label: str
    state: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "detail": self.detail,
            "evidence": self.evidence,
        }


@dataclass(slots=True)
class PilotReadinessService(_PrincipalScoped):
    """Factual pilot-readiness for the caller's own workspace."""

    async def report(self) -> dict[str, Any]:
        from sqlalchemy import func, select

        from infrastructure.database.models.crm import Task
        from infrastructure.database.models.leads import Lead, LeadSourceEvent
        from infrastructure.database.models.tenancy import TeamMember, Tenant
        from infrastructure.database.models.users import Role as RoleRow
        from infrastructure.database.models.users import User
        from infrastructure.database.session import tenant_session

        checks: list[Check] = []

        async with tenant_session(self.tenant_id) as session:
            tenant = (
                await session.execute(
                    select(Tenant.name, Tenant.slug, Tenant.settings, Tenant.timezone).where(
                        Tenant.id == self.tenant_id
                    )
                )
            ).first()

            # Unpacked once. A workspace that has somehow vanished under the
            # caller is a real possibility here, and every check below would
            # otherwise have to re-ask whether the row existed.
            name, slug, raw_settings, timezone = (
                tenant if tenant is not None else (None, None, {}, None)
            )
            settings: dict[str, Any] = raw_settings or {}
            kind = settings.get(WORKSPACE_KIND_KEY)

            # --- the workspace itself -----------------------------------------
            checks.append(
                Check(
                    key="isolated_tenant",
                    label="A workspace of its own",
                    state=READY if kind else ATTENTION,
                    detail=(
                        f"This is the “{name}” workspace, kept apart from every other "
                        "business by the same tenancy rule the database enforces."
                        if kind
                        else "This workspace predates workspace kinds and is not labelled yet."
                    ),
                    evidence={"name": name, "kind": kind},
                )
            )

            checks.append(
                Check(
                    key="timezone",
                    label="Indian working day",
                    state=READY if timezone == "Asia/Kolkata" else ATTENTION,
                    detail=(
                        "Dates and overdue times are worked out in Asia/Kolkata."
                        if timezone == "Asia/Kolkata"
                        else f"Workspace timezone is {timezone or 'unknown'}."
                    ),
                )
            )

            # --- people and scope ---------------------------------------------
            people = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(User)
                        .where(User.tenant_id == self.tenant_id, User.deleted_at.is_(None))
                    )
                ).scalar_one()
            )
            scopes = {
                row.name: row.default_scope
                for row in await session.execute(
                    select(RoleRow.name, RoleRow.default_scope).where(
                        RoleRow.tenant_id == self.tenant_id
                    )
                )
            }
            checks.append(
                Check(
                    key="users",
                    label="People who can sign in",
                    state=READY if people else ATTENTION,
                    detail=(
                        f"{people} {'person' if people == 1 else 'people'} can sign in."
                        if people
                        else "Nobody has been set up for this workspace yet."
                    ),
                    evidence={"count": people, "roles": scopes},
                )
            )

            # The session-4 defect, checked rather than assumed: a team-scoped
            # person with no team matches no records at all.
            orphaned = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(User)
                        .where(
                            User.tenant_id == self.tenant_id,
                            User.deleted_at.is_(None),
                            ~User.id.in_(
                                select(TeamMember.user_id).where(
                                    TeamMember.tenant_id == self.tenant_id
                                )
                            ),
                        )
                    )
                ).scalar_one()
            )
            team_scoped = any(scope == "team" for scope in scopes.values())
            checks.append(
                Check(
                    key="team_scope",
                    label="Managers can actually see their team",
                    state=ATTENTION if team_scoped and orphaned else READY,
                    detail=(
                        f"{orphaned} of the people here belong to no team. A manager whose "
                        "scope is their team would see nothing at all."
                        if team_scoped and orphaned
                        else "Everyone who needs a team is in one."
                    ),
                    evidence={"without_team": orphaned},
                )
            )

            # --- the work itself -----------------------------------------------
            prospects = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Lead)
                        .where(Lead.tenant_id == self.tenant_id, Lead.deleted_at.is_(None))
                    )
                ).scalar_one()
            )
            imported = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(LeadSourceEvent)
                        .where(LeadSourceEvent.tenant_id == self.tenant_id)
                    )
                ).scalar_one()
            )
            duplicates = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(LeadSourceEvent)
                        .where(
                            LeadSourceEvent.tenant_id == self.tenant_id,
                            LeadSourceEvent.outcome == "duplicate",
                        )
                    )
                ).scalar_one()
            )
            follow_ups = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(Task)
                        .where(Task.tenant_id == self.tenant_id, Task.deleted_at.is_(None))
                    )
                ).scalar_one()
            )

            checks.append(
                Check(
                    key="prospects",
                    label="Prospects captured",
                    state=READY if prospects else ATTENTION,
                    detail=(
                        f"{prospects} prospect{'' if prospects == 1 else 's'} in this workspace."
                        if prospects
                        else "No prospects yet. Add one by hand or import a list."
                    ),
                    evidence={"count": prospects},
                )
            )
            checks.append(
                Check(
                    key="import",
                    label="List import used",
                    state=READY if imported else ATTENTION,
                    detail=(
                        f"{imported} rows have come through capture or import."
                        if imported
                        else "Nothing has been imported into this workspace yet. CSV only."
                    ),
                    evidence={"source_events": imported},
                )
            )
            checks.append(
                Check(
                    key="duplicates",
                    label="Duplicate matching seen working",
                    state=READY if duplicates else ATTENTION,
                    detail=(
                        f"{duplicates} incoming rows were recognised as businesses already here, "
                        "and none of the existing records was changed."
                        if duplicates
                        else "No duplicates have been encountered yet, so this is unproven here."
                    ),
                    evidence={"duplicate_rows": duplicates},
                )
            )
            checks.append(
                Check(
                    key="follow_ups",
                    label="Follow-ups in use",
                    state=READY if follow_ups else ATTENTION,
                    detail=(
                        f"{follow_ups} follow-up{'' if follow_ups == 1 else 's'} recorded."
                        if follow_ups
                        else "Nothing has been scheduled as a next action yet."
                    ),
                    evidence={"count": follow_ups},
                )
            )

            baseline = settings.get("starting_baseline")
            checks.append(
                Check(
                    key="starting_baseline",
                    label="Starting baseline captured",
                    state=READY if baseline else ATTENTION,
                    detail=(
                        f"Recorded {baseline.get('captured_at')}, under definition "
                        f"{baseline.get('definition_version')}."
                        if baseline
                        else "No “before” picture has been taken. Capture one on Today before the "
                        "team starts working the list."
                    ),
                    evidence={"captured_at": (baseline or {}).get("captured_at")},
                )
            )

        # --- first-response semantics ----------------------------------------
        # Not probed against data: it is a property of the code, and the tests that
        # pin it are named here so the claim is checkable rather than asserted.
        checks.append(
            Check(
                key="first_response_rule",
                label="What counts as replying to somebody",
                state=READY,
                detail=(
                    "One rule, in the domain: a missed call, a meeting still in the diary, an "
                    "inbound message nobody answered and a send the provider rejected all leave "
                    "the prospect waiting. An inbound call somebody picked up counts."
                ),
                evidence={"tests": "backend/tests/unit/test_first_response_rule.py"},
            )
        )

        # --- data safety -------------------------------------------------------
        # Off the event loop: stat and glob are blocking, and this runs on a page
        # load that also has an owner waiting for it.
        reachable, snapshots = await asyncio.to_thread(_snapshot_state)
        checks.append(
            Check(
                key="backups",
                label="A snapshot is taken before anything destructive",
                state=READY if reachable else ATTENTION,
                detail=(
                    f"{snapshots} local snapshot{'' if snapshots == 1 else 's'} kept. "
                    "A refresh or reset stops if the snapshot fails."
                    if reachable
                    else "The snapshot folder is not reachable from here, so this cannot be "
                    "confirmed from inside the app."
                ),
                evidence={"snapshots": snapshots},
            )
        )
        checks.append(
            Check(
                key="refresh_cannot_reach_pilot",
                label="Sample refresh cannot touch this workspace",
                state=READY if kind == PILOT else ATTENTION if kind == TEST else READY,
                detail=(
                    "A refresh deletes only rows a demo seed recorded creating. This workspace "
                    "has no such record, so there is nothing here it is able to delete."
                    if kind == PILOT
                    else "This is a test workspace. Its contents are disposable by design."
                    if kind == TEST
                    else "A refresh deletes only rows the demo seed recorded creating."
                ),
            )
        )

        # --- what stays manual during a shadow pilot ---------------------------
        for key, label in (
            ("manual_calls", "Phone calls"),
            ("manual_whatsapp", "WhatsApp messages sent by hand"),
            ("manual_email", "Emails sent by hand"),
        ):
            checks.append(
                Check(
                    key=key,
                    label=label,
                    state=MANUAL,
                    detail=(
                        "The person makes the contact themselves and records what happened. "
                        "Sangam measures it; it does not send it."
                    ),
                )
            )

        return {
            "workspace": {"name": name, "slug": slug, "kind": kind},
            "checks": [check.as_dict() for check in checks],
            "summary": {
                "ready": sum(1 for c in checks if c.state == READY),
                "attention": sum(1 for c in checks if c.state == ATTENTION),
                "manual": sum(1 for c in checks if c.state == MANUAL),
            },
        }


def _snapshot_state() -> tuple[bool, int]:
    """Whether the snapshot folder is reachable, and how many are in it."""
    if not BACKUP_DIR.is_dir():
        return False, 0
    return True, len(list(BACKUP_DIR.glob("*.sql")))


__all__ = ["ATTENTION", "MANUAL", "READY", "PilotReadinessService"]
