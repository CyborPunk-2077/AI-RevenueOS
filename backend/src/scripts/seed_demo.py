"""Seed local demo data for the vertical-slice demo. LOCAL ONLY.

Creates two tenants so tenant isolation is demonstrable, one active user each, and
a couple of leads for the first tenant.

The demo password is read from `DEMO_PASSWORD`; when unset a random one is
generated and printed once. Nothing is committed and nothing is written to a file.
The script refuses to run outside the `local` environment.

    python src/scripts/seed_demo.py
    DEMO_PASSWORD='choose-your-own' python src/scripts/seed_demo.py --reset
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, text

from domain.auth.permissions import ROLE_PERMISSIONS, Role
from infrastructure.auth.passwords import hash_password, validate_password
from infrastructure.database.models.leads import Lead
from infrastructure.database.models.tenancy import Tenant
from infrastructure.database.models.users import (
    Role as RoleRow,
)
from infrastructure.database.models.users import (
    RolePermission,
    User,
    UserRole,
)
from infrastructure.database.session import admin_session, tenant_session
from infrastructure.logging.setup import configure_logging, get_logger
from shared.settings import get_settings
from shared.utils.ids import uuid7
from shared.utils.timeutil import utcnow

logger = get_logger("scripts.seed_demo")

# Fixed ids keep the demo reproducible and let the isolation test target them.
ACME_ID = UUID("01890000-0000-7000-8000-0000000ac3e0")
GLOBEX_ID = UUID("01890000-0000-7000-8000-0000000916ex".replace("x", "0"))

TENANTS = (
    (ACME_ID, "Acme Realty", "acme", "asha@acme.test", "Asha Kumar", "real_estate"),
    (GLOBEX_ID, "Globex Clinic", "globex", "ravi@globex.test", "Ravi Shankar", "clinics"),
)

DEMO_LEADS = (
    {
        "first_name": "Meera",
        "last_name": "Iyer",
        "email": "meera.iyer@example.in",
        "phone": "+919876500001",
        "source": "web_form",
        "capture": {"location": "Pune", "budget_minor": 8_500_000, "timeline": "3_months"},
    },
    {
        "first_name": "Sunil",
        "last_name": "Rao",
        "email": "sunil.rao@example.in",
        "phone": "+919876500002",
        "source": "referral",
        "capture": {"location": "Mumbai", "budget_minor": 12_000_000, "timeline": "immediate"},
    },
)


def resolve_password() -> tuple[str, bool]:
    supplied = os.environ.get("DEMO_PASSWORD")
    if supplied:
        check = validate_password(supplied)
        if not check.ok:
            raise SystemExit("DEMO_PASSWORD rejected: " + "; ".join(check.problems))
        return supplied, False
    # 32 URL-safe characters comfortably clears the 12-character policy floor.
    return f"demo-{secrets.token_urlsafe(24)}", True


async def ensure_roles(session, tenant_id: UUID) -> UUID:  # type: ignore[no-untyped-def]
    """Create the owner role for a tenant and grant it its permission set."""
    existing = (
        await session.execute(
            select(RoleRow.id).where(RoleRow.tenant_id == tenant_id, RoleRow.name == "owner")
        )
    ).scalar_one_or_none()
    if existing:
        return UUID(str(existing))

    role_id = uuid7()
    session.add(
        RoleRow(
            id=role_id,
            tenant_id=tenant_id,
            name=Role.OWNER.value,
            description="Demo owner",
            is_system=True,
            default_scope="global",
            version=1,
        )
    )
    for code in sorted(ROLE_PERMISSIONS[Role.OWNER]):
        session.add(RolePermission(tenant_id=tenant_id, role_id=role_id, permission_code=code))
    return role_id


async def reset() -> None:
    """Remove demo rows only. Never touches anything outside the demo tenants."""
    async with admin_session() as session:
        for tenant_id, *_ in TENANTS:
            # Fixed, in-repo allowlist; no user input reaches this string.
            for table in (
                "app.lead_source_events",
                "app.leads",
                "app.user_roles",
                "app.role_permissions",
                "app.refresh_tokens",
                "app.users",
                "app.roles",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE tenant_id = :t"),  # noqa: S608
                    {"t": tenant_id},
                )
            await session.execute(text("DELETE FROM app.tenants WHERE id = :t"), {"t": tenant_id})
    logger.info("demo_reset")


async def seed(password: str) -> dict[str, object]:
    settings = get_settings()
    if settings.environment != "local":
        raise SystemExit(f"seed_demo refuses to run in the '{settings.environment}' environment")

    password_hash = hash_password(password)
    created: list[dict[str, str]] = []

    async with admin_session() as session:
        for tenant_id, name, slug, email, full_name, industry in TENANTS:
            exists = (
                await session.execute(select(Tenant.id).where(Tenant.id == tenant_id))
            ).scalar_one_or_none()
            if not exists:
                session.add(
                    Tenant(
                        id=tenant_id,
                        name=name,
                        slug=slug,
                        industry_code=industry,
                        plan_code="growth",
                        status="active",
                        timezone="Asia/Kolkata",
                        currency="INR",
                        locale="en-IN",
                        version=1,
                    )
                )
                await session.flush()

            role_id = await ensure_roles(session, tenant_id)

            user = (
                await session.execute(
                    select(User).where(User.tenant_id == tenant_id, User.email == email)
                )
            ).scalar_one_or_none()
            if user is None:
                user_id = uuid7()
                session.add(
                    User(
                        id=user_id,
                        tenant_id=tenant_id,
                        email=email,
                        full_name=full_name,
                        password_hash=password_hash,
                        password_changed_at=utcnow(),
                        status="active",
                        email_verified_at=utcnow(),
                        is_owner=True,
                        timezone="Asia/Kolkata",
                        version=1,
                    )
                )
                session.add(UserRole(tenant_id=tenant_id, user_id=user_id, role_id=role_id))
            else:
                # Re-running the seed refreshes the password so the printed one works.
                user.password_hash = password_hash
                user.status = "active"
                user.failed_login_count = 0
                user.locked_until = None
                user_id = user.id

            created.append({"tenant": slug, "email": email, "user_id": str(user_id)})

    # Leads are tenant-owned, so they are written under that tenant's context.
    lead_count = 0
    async with tenant_session(ACME_ID) as session:
        for payload in DEMO_LEADS:
            already = (
                await session.execute(select(Lead.id).where(Lead.email == payload["email"]))
            ).scalar_one_or_none()
            if already:
                continue
            session.add(
                Lead(
                    id=uuid7(),
                    tenant_id=ACME_ID,
                    first_name=payload["first_name"],
                    last_name=payload["last_name"],
                    email=payload["email"],
                    phone=payload["phone"],
                    source=payload["source"],
                    source_channel="web",
                    capture=payload["capture"],
                    utm={},
                    status="new",
                    dedupe_key=f"e:{payload['email']}",
                    version=1,
                )
            )
            lead_count += 1

    return {"users": created, "leads_created": lead_count}


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed local demo data")
    parser.add_argument("--reset", action="store_true", help="remove demo rows first")
    args = parser.parse_args()

    configure_logging(json_output=False)
    password, generated = resolve_password()

    if args.reset:
        await reset()
    result = await seed(password)

    print("\n" + "=" * 66)  # noqa: T201
    print("  Demo data ready")  # noqa: T201
    print("=" * 66)  # noqa: T201
    for entry in result["users"]:  # type: ignore[index]
        print(f"  tenant {entry['tenant']:8} sign in as  {entry['email']}")  # noqa: T201
    print(f"\n  password: {password}")  # noqa: T201
    if generated:
        print("  (generated for this run only and not stored anywhere;")  # noqa: T201
        print("   set DEMO_PASSWORD to choose your own)")  # noqa: T201
    print(f"\n  leads created for acme: {result['leads_created']}")  # noqa: T201
    print("=" * 66 + "\n")  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
