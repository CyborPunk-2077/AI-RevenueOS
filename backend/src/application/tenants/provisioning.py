"""Creating a workspace and the people in it. One implementation, several callers.

The demo seed grew these routines first, and a pilot needs exactly the same ones:
a tenant with Indian defaults, the system roles with their scopes, users who can
sign in, and - the part that is easy to forget and breaks everything when you do -
a branch and a team with real memberships.

That last point is why this is shared code rather than a second copy. A manager's
role scope is `team`, and the repository layer filters on the teams in their
token, correctly failing closed when there are none. A workspace provisioned with
managers and no team therefore produces a user who cannot see or reassign a single
record and is told "not found" for every one of them. Session 4 shipped that bug
to the founders. Provisioning a pilot through a second, younger copy of this logic
would ship it to a paying business instead.

Nothing here is demo-specific. The manifest that decides what a demo refresh may
delete lives in `application.tenants.demo_data` and is written only by the seed, so
a workspace provisioned through this module starts with no manifest at all - which
is precisely what makes every row in it undeletable by any refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from domain.auth.permissions import ROLE_PERMISSIONS, Role
from infrastructure.logging.setup import get_logger
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("application.tenants.provisioning")

#: What a workspace is *for*, recorded on the tenant so that every other decision
#: can be made from data rather than from a hardcoded list of slugs.
#:
#: This is the honest place for the distinction. Session 3 already established
#: that isolation between real and test data is a tenancy question, not an
#: `is_test` column smeared across every business table; this simply names the
#: kinds so the UI can say which workspace you are looking at and so destructive
#: maintenance can refuse to run against the wrong one.
WORKSPACE_KIND_KEY: Final = "workspace_kind"

FOUNDER: Final = "founder"  # the founders' own prospecting workspace
PILOT: Final = "pilot"  # a real SME running a shadow pilot
TEST: Final = "test"  # the browser suites; disposable by design
DEMO: Final = "demo"  # sample-only reference workspaces

WORKSPACE_KINDS: Final[frozenset[str]] = frozenset({FOUNDER, PILOT, TEST, DEMO})

#: Workspaces holding data somebody would be upset to lose. Used by the
#: destructive-maintenance guards, which is why it is stated once, here.
REAL_WORKSPACE_KINDS: Final[frozenset[str]] = frozenset({FOUNDER, PILOT})


@dataclass(frozen=True, slots=True)
class Person:
    """One person who will sign in. Scope is theirs, not their role's by accident."""

    email: str
    full_name: str
    role: Role
    scope: str


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    """Everything needed to stand a workspace up, with Indian defaults."""

    tenant_id: UUID
    name: str
    slug: str
    people: tuple[Person, ...]
    kind: str = PILOT
    industry_code: str = "other_sme"
    city: str = "Bengaluru"
    state: str = "Karnataka"
    branch_name: str = "Head office"
    branch_code: str = "HQ"
    team_name: str = "Sales"
    timezone: str = "Asia/Kolkata"
    currency: str = "INR"
    locale: str = "en-IN"


@dataclass(slots=True)
class ProvisionResult:
    tenant_id: UUID
    slug: str
    created_tenant: bool
    team_id: UUID
    branch_id: UUID
    users: dict[str, UUID] = field(default_factory=dict)
    created_users: list[str] = field(default_factory=list)


async def ensure_role(session: Any, tenant_id: UUID, role: Role, scope: str) -> UUID:
    """The system role and its permission rows. Idempotent."""
    from sqlalchemy import select

    from infrastructure.database.models.users import Role as RoleRow
    from infrastructure.database.models.users import RolePermission

    existing = (
        await session.execute(
            select(RoleRow.id).where(RoleRow.tenant_id == tenant_id, RoleRow.name == role.value)
        )
    ).scalar_one_or_none()
    if existing:
        return UUID(str(existing))

    role_id = uuid7()
    session.add(
        RoleRow(
            id=role_id,
            tenant_id=tenant_id,
            name=role.value,
            description=f"Sangam {role.value}",
            is_system=True,
            default_scope=scope,
            version=1,
        )
    )
    # Straight from the domain's permission table. A pilot must not get a
    # hand-written, quietly different set of permissions from the one every test
    # in the suite asserts against.
    for code in sorted(ROLE_PERMISSIONS[role]):
        session.add(RolePermission(tenant_id=tenant_id, role_id=role_id, permission_code=code))
    return role_id


async def ensure_tenant(session: Any, spec: WorkspaceSpec) -> bool:
    """The workspace row itself. Returns True when this call created it."""
    from sqlalchemy import select, update

    from infrastructure.database.models.tenancy import Tenant

    row = (
        await session.execute(select(Tenant.id, Tenant.settings).where(Tenant.id == spec.tenant_id))
    ).first()

    if row is None:
        session.add(
            Tenant(
                id=spec.tenant_id,
                name=spec.name,
                slug=spec.slug,
                industry_code=spec.industry_code,
                plan_code="growth",
                status="active",
                timezone=spec.timezone,
                currency=spec.currency,
                locale=spec.locale,
                settings={WORKSPACE_KIND_KEY: spec.kind},
                version=1,
            )
        )
        await session.flush()
        return True

    # Stamp the kind onto a workspace that predates this field, without touching
    # anything else in settings - the demo manifest lives in there too, and losing
    # it would put real founder rows back within reach of a refresh.
    settings = dict(row[1] or {})
    if settings.get(WORKSPACE_KIND_KEY) != spec.kind:
        settings[WORKSPACE_KIND_KEY] = spec.kind
        # Core update: `Tenant` carries an optimistic version column and bumping
        # it from a provisioning script would fail an unrelated concurrent save.
        await session.execute(
            update(Tenant).where(Tenant.id == spec.tenant_id).values(settings=settings)
        )
    return False


async def ensure_people(
    session: Any, spec: WorkspaceSpec, *, password_hash: str, reset_credentials: bool = True
) -> tuple[dict[str, UUID], list[str]]:
    """Users and their role grants. Returns every id, and which were new.

    `reset_credentials` exists for the demo seed, whose whole contract is that a
    re-run leaves every printed credential working. A pilot re-run must *not*
    silently reset a real person's password back to the provisioning one, so the
    pilot path passes False.
    """
    from sqlalchemy import select

    from infrastructure.database.models.users import User, UserRole

    users: dict[str, UUID] = {}
    created: list[str] = []

    for person in spec.people:
        role_id = await ensure_role(session, spec.tenant_id, person.role, person.scope)
        user = (
            await session.execute(
                select(User).where(User.tenant_id == spec.tenant_id, User.email == person.email)
            )
        ).scalar_one_or_none()

        if user is None:
            user_id = uuid7()
            session.add(
                User(
                    id=user_id,
                    tenant_id=spec.tenant_id,
                    email=person.email,
                    full_name=person.full_name,
                    password_hash=password_hash,
                    password_changed_at=utcnow(),
                    status="active",
                    email_verified_at=utcnow(),
                    is_owner=person.role is Role.OWNER,
                    timezone=spec.timezone,
                    version=1,
                )
            )
            session.add(UserRole(tenant_id=spec.tenant_id, user_id=user_id, role_id=role_id))
            created.append(person.email)
        else:
            if reset_credentials:
                user.password_hash = password_hash
                user.status = "active"
                user.failed_login_count = 0
                user.locked_until = None
                user.mfa_enabled = False
                user.mfa_secret_encrypted = None
                user.mfa_recovery_codes = []
            user_id = user.id
        users[person.email] = user_id

    # The team memberships written next reference these ids by foreign key.
    await session.flush()
    return users, created


async def ensure_branch_and_team(
    session: Any, spec: WorkspaceSpec, users: dict[str, UUID]
) -> tuple[UUID, UUID]:
    """One branch, one team, and everybody in it.

    Membership is not optional decoration. A `team`-scoped manager with no team
    matches nothing at all, so a workspace has to be internally consistent rather
    than merely populated.
    """
    from sqlalchemy import select

    from infrastructure.database.models.tenancy import Branch, Team, TeamMember

    branch_id = (
        await session.execute(
            select(Branch.id).where(
                Branch.tenant_id == spec.tenant_id, Branch.code == spec.branch_code
            )
        )
    ).scalar_one_or_none()
    if branch_id is None:
        branch_id = uuid7()
        session.add(
            Branch(
                id=branch_id,
                tenant_id=spec.tenant_id,
                name=spec.branch_name,
                code=spec.branch_code,
                address={"city": spec.city, "state": spec.state, "country": "IN"},
                timezone=spec.timezone,
                is_headquarters=True,
                version=1,
            )
        )
        await session.flush()

    team_id = (
        await session.execute(
            select(Team.id).where(Team.tenant_id == spec.tenant_id, Team.name == spec.team_name)
        )
    ).scalar_one_or_none()
    if team_id is None:
        team_id = uuid7()
        session.add(
            Team(
                id=team_id,
                tenant_id=spec.tenant_id,
                branch_id=branch_id,
                name=spec.team_name,
                version=1,
            )
        )
        await session.flush()

    for user_id in users.values():
        existing = (
            await session.execute(
                select(TeamMember.id).where(
                    TeamMember.team_id == team_id, TeamMember.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            session.add(
                TeamMember(id=uuid7(), tenant_id=spec.tenant_id, team_id=team_id, user_id=user_id)
            )

    # Flush before returning, so a caller reading this workspace back in the same
    # session sees a complete one. Without it "provisioned" means "queued", and
    # the memberships that make a manager's scope work are the last thing that
    # should exist only in Python.
    await session.flush()
    return UUID(str(branch_id)), UUID(str(team_id))


async def provision_workspace(
    session: Any, spec: WorkspaceSpec, *, password_hash: str, reset_credentials: bool = True
) -> ProvisionResult:
    """A complete, internally consistent workspace. Idempotent."""
    if spec.kind not in WORKSPACE_KINDS:
        raise ValueError(f"Unknown workspace kind: {spec.kind!r}")

    created_tenant = await ensure_tenant(session, spec)
    users, created_users = await ensure_people(
        session, spec, password_hash=password_hash, reset_credentials=reset_credentials
    )
    branch_id, team_id = await ensure_branch_and_team(session, spec, users)

    logger.info(
        "workspace_provisioned",
        tenant_id=str(spec.tenant_id),
        slug=spec.slug,
        kind=spec.kind,
        created_tenant=created_tenant,
        created_users=len(created_users),
    )
    return ProvisionResult(
        tenant_id=spec.tenant_id,
        slug=spec.slug,
        created_tenant=created_tenant,
        team_id=team_id,
        branch_id=branch_id,
        users=users,
        created_users=created_users,
    )


async def workspace_identity(tenant_id: UUID) -> dict[str, Any]:
    """Which company's workspace this is, for the signed-in chrome.

    The founders now hold three kinds of workspace open at once - their own, a
    pilot's, and the one the browser tests write to - and every one of them shows
    the same screens. Being certain which company you are looking at before you
    type a customer's name into it is not a nicety.
    """
    from sqlalchemy import select

    from infrastructure.database.models.tenancy import Tenant
    from infrastructure.database.session import tenant_session

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(Tenant.name, Tenant.slug, Tenant.settings).where(Tenant.id == tenant_id)
            )
        ).first()

    if row is None:
        return {"name": None, "slug": None, "kind": None}
    kind = (row[2] or {}).get(WORKSPACE_KIND_KEY)
    return {"name": row[0], "slug": row[1], "kind": str(kind) if kind else None}


async def workspace_kind(session: Any, tenant_id: UUID) -> str | None:
    """What this workspace is for, or None when it was never stamped."""
    from sqlalchemy import select

    from infrastructure.database.models.tenancy import Tenant

    settings = (
        await session.execute(select(Tenant.settings).where(Tenant.id == tenant_id))
    ).scalar_one_or_none()
    kind = (settings or {}).get(WORKSPACE_KIND_KEY)
    return str(kind) if kind else None
