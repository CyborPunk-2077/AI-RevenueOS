"""Stand up a workspace for one real SME running a shadow pilot. LOCAL ONLY.

A pilot business gets its own tenant. Not a folder, not a tag, not a filtered view
of the founders' workspace - a tenant, because tenancy is the boundary this system
already enforces all the way down to forced row-level security, and it is the only
boundary that cannot be forgotten by a query somebody writes next month.

What this deliberately does *not* do:

* it seeds no sample prospects. A pilot's numbers have to mean something, and
  fifteen invented Bengaluru businesses in the denominator would make the starting
  baseline a work of fiction;
* it writes no demo manifest, which is what makes every row the pilot ever creates
  permanently out of reach of `seed_sangam.py --refresh` - not by being recognised
  as real, but by never having been claimed as synthetic;
* it does not email anybody. Email is provider-gated and cannot deliver an
  invitation, so the credentials are printed here for the founder to hand over.
  Pretending otherwise would leave a pilot user waiting for a message that was
  never going to arrive.

    python src/scripts/provision_pilot.py --name "Sharma Motors" --slug sharma-motors \
        --owner owner@sharmamotors.in "Rakesh Sharma" \
        --manager manager@sharmamotors.in "Deepa Sharma" \
        --member sales@sharmamotors.in "Imran Khan"

A re-run is safe: existing people keep their passwords, missing ones are created.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from application.tenants.provisioning import (
    PILOT,
    Person,
    WorkspaceSpec,
    provision_workspace,
)
from domain.auth.permissions import Role
from infrastructure.auth.passwords import hash_password, validate_password
from infrastructure.database.session import admin_session
from infrastructure.logging.setup import configure_logging, get_logger
from shared.utils.ids import uuid7

logger = get_logger("scripts.provision_pilot")

#: Slugs the pilot provisioner must never be pointed at. Reusing one of these
#: would drop a pilot's people and prospects into the founders' own workspace,
#: which is the exact confusion this script exists to prevent.
RESERVED_SLUGS = frozenset({"sangam", "sangam-e2e", "acme", "globex"})


@dataclass(frozen=True, slots=True)
class PilotReport:
    """What provisioning did, in a shape the printing code can rely on."""

    tenant_id: str
    slug: str
    reused_workspace: bool
    created_tenant: bool
    created_users: list[str]
    users: dict[str, str]


def _generated_password() -> str:
    """A strong password nobody has to invent under pressure."""
    return f"pilot-{secrets.token_urlsafe(18)}"


async def _tenant_id_for(slug: str) -> tuple[UUID, bool]:
    """Reuse this workspace's id if it exists, otherwise mint one."""
    from infrastructure.database.models.tenancy import Tenant

    async with admin_session() as session:
        existing = (
            await session.execute(select(Tenant.id).where(Tenant.slug == slug))
        ).scalar_one_or_none()
    if existing:
        return UUID(str(existing)), True
    return uuid7(), False


async def provision(
    *,
    name: str,
    slug: str,
    owner: tuple[str, str],
    managers: list[tuple[str, str]],
    members: list[tuple[str, str]],
    city: str,
    state: str,
    password: str,
) -> PilotReport:
    if slug in RESERVED_SLUGS:
        raise SystemExit(
            f"'{slug}' is a Sangam workspace, not a pilot. Choose a slug for the pilot business."
        )

    check = validate_password(password)
    if not check.ok:
        raise SystemExit("Password rejected: " + "; ".join(check.problems))

    tenant_id, reused = await _tenant_id_for(slug)

    people = [Person(email=owner[0], full_name=owner[1], role=Role.OWNER, scope="global")]
    # A manager sees their team. That is only meaningful because provisioning also
    # creates the team and puts them in it.
    people += [
        Person(email=email, full_name=full_name, role=Role.MANAGER, scope="team")
        for email, full_name in managers
    ]
    # A salesperson sees their own work. Narrower on purpose: "clear ownership" is
    # a claim this product has to be able to demonstrate, not assert.
    people += [
        Person(email=email, full_name=full_name, role=Role.MEMBER, scope="self")
        for email, full_name in members
    ]

    spec = WorkspaceSpec(
        tenant_id=tenant_id,
        name=name,
        slug=slug,
        kind=PILOT,
        people=tuple(people),
        city=city,
        state=state,
    )

    async with admin_session() as session:
        result = await provision_workspace(
            session,
            spec,
            password_hash=hash_password(password),
            # A re-run must never reset a real person's password back to the one
            # printed on day one. The demo seed wants the opposite; a pilot does
            # not, because these are working accounts belonging to somebody else.
            reset_credentials=False,
        )

    return PilotReport(
        tenant_id=str(result.tenant_id),
        slug=result.slug,
        reused_workspace=reused,
        created_tenant=result.created_tenant,
        created_users=result.created_users,
        users={email: str(user_id) for email, user_id in result.users.items()},
    )


def _pair(value: list[str]) -> tuple[str, str]:
    return (value[0].strip().lower(), value[1].strip())


async def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a shadow-pilot workspace")
    parser.add_argument("--name", required=True, help="the business's name, as they write it")
    parser.add_argument("--slug", required=True, help="short url-safe id, e.g. sharma-motors")
    parser.add_argument(
        "--owner", nargs=2, metavar=("EMAIL", "NAME"), required=True, help="the business owner"
    )
    parser.add_argument(
        "--manager", nargs=2, metavar=("EMAIL", "NAME"), action="append", default=[]
    )
    parser.add_argument("--member", nargs=2, metavar=("EMAIL", "NAME"), action="append", default=[])
    parser.add_argument("--city", default="Bengaluru")
    parser.add_argument("--state", default="Karnataka")
    parser.add_argument(
        "--password",
        default=None,
        help="shared starting password; generated and printed when omitted",
    )
    args = parser.parse_args()

    configure_logging(json_output=False)

    password = args.password or _generated_password()
    report = await provision(
        name=args.name,
        slug=args.slug,
        owner=_pair(args.owner),
        managers=[_pair(m) for m in args.manager],
        members=[_pair(m) for m in args.member],
        city=args.city,
        state=args.state,
        password=password,
    )

    print("\n" + "=" * 68)  # noqa: T201
    print(f"  Pilot workspace: {args.name}")  # noqa: T201
    print("=" * 68)  # noqa: T201
    print(f"  Workspace id   : {report.slug}")  # noqa: T201
    print(f"  Existing       : {'yes' if report.reused_workspace else 'no, created now'}")  # noqa: T201
    print(f"  People         : {len(report.users)}")  # noqa: T201
    print("\n  Sign-in details to hand over:\n")  # noqa: T201
    for email in report.users:
        state = "new" if email in report.created_users else "already existed"
        print(f"    {email:38} ({state})")  # noqa: T201
    if report.created_users:
        print(f"\n  Starting password for the new accounts: {password}")  # noqa: T201
        print("  Give this to them directly and ask them to change it after signing in.")  # noqa: T201
        print("  Sangam cannot email it: no email provider is connected.")  # noqa: T201
    else:
        print("\n  No new accounts, so no password was set. Existing ones are unchanged.")  # noqa: T201
    print("\n  This workspace holds no sample data. Every prospect in it will be real,")  # noqa: T201
    print("  and no demo refresh can reach any of it.")  # noqa: T201
    print("=" * 68 + "\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
