"""Invitations against real PostgreSQL: durable, isolated, single-use, audited."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from application.auth.invitations import (
    INVITATION_TTL,
    accept_invitation,
    invite_user,
    list_invitations,
    peek_invitation,
    revoke_invitation,
)
from infrastructure.database.models.audit import AuditLog
from infrastructure.database.models.users import Invitation, User, UserRole
from infrastructure.database.session import tenant_session
from shared.exceptions import Conflict, Forbidden, NotFound, ValidationError
from shared.utils.timeutil import utcnow

pytestmark = pytest.mark.postgres

PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=4$fakehashforatestonly"


def _email() -> str:
    return f"invitee-{uuid4().hex}@example.in"


async def test_invitation_is_durable_scoped_and_audited(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    actor = uuid4()
    email = _email()

    issued = await invite_user(
        tenant_id=tenant_a, actor_id=actor, actor_roles=("owner",), email=email, role="manager"
    )

    assert issued.email == email
    assert issued.token.startswith(f"{tenant_a}.")
    assert timedelta(days=6) < issued.expires_at - utcnow() <= INVITATION_TTL

    async with tenant_session(tenant_a) as session:
        row = (
            await session.execute(select(Invitation).where(Invitation.id == issued.invitation_id))
        ).scalar_one()
        # Only the hash is stored: a database reader cannot mint a working link.
        assert row.token_hash != issued.token
        assert issued.token not in row.token_hash
        assert row.accepted_at is None and row.revoked_at is None

        audited = (
            await session.execute(
                select(func.count())
                .select_from(AuditLog)
                .where(AuditLog.action == "user.invited", AuditLog.tenant_id == tenant_a)
            )
        ).scalar_one()
        assert audited >= 1


async def test_inviting_creates_no_user_until_the_link_is_redeemed(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    """An abandoned invitation must not leave a half-member or consume a seat."""
    tenant_a, _ = seeded_tenants
    email = _email()

    await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
    )

    async with tenant_session(tenant_a) as session:
        users = (
            await session.execute(
                select(func.count())
                .select_from(User)
                .where(User.tenant_id == tenant_a, func.lower(User.email) == email)
            )
        ).scalar_one()
    assert users == 0


async def test_acceptance_creates_the_user_and_the_role_grant_together(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    email = _email()
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="manager"
    )

    result = await accept_invitation(
        token=issued.token, full_name="Asha Menon", password_hash=PASSWORD_HASH
    )

    assert result["email"] == email
    assert result["role"] == "manager"

    async with tenant_session(tenant_a) as session:
        user = (
            await session.execute(select(User).where(User.id == UUID(result["user_id"])))
        ).scalar_one()
        assert user.status == "active"
        assert user.email_verified_at is not None  # redeeming the link proved it
        assert user.is_owner is False

        grants = (
            await session.execute(
                select(func.count()).select_from(UserRole).where(UserRole.user_id == user.id)
            )
        ).scalar_one()
        assert grants == 1

        invitation = (
            await session.execute(select(Invitation).where(Invitation.id == issued.invitation_id))
        ).scalar_one()
        assert invitation.accepted_at is not None


async def test_a_link_cannot_be_redeemed_twice(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=_email(), role="member"
    )
    await accept_invitation(
        token=issued.token, full_name="First Arrival", password_hash=PASSWORD_HASH
    )

    with pytest.raises(NotFound):
        await accept_invitation(
            token=issued.token, full_name="Second Arrival", password_hash=PASSWORD_HASH
        )


async def test_a_revoked_link_stops_working(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants
    actor = uuid4()
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=actor, actor_roles=("owner",), email=_email(), role="member"
    )

    first = await revoke_invitation(
        tenant_id=tenant_a, actor_id=actor, invitation_id=issued.invitation_id
    )
    # Revoking twice is a no-op rather than an error: the caller wanted it gone.
    second = await revoke_invitation(
        tenant_id=tenant_a, actor_id=actor, invitation_id=issued.invitation_id
    )
    assert first["status"] == second["status"] == "revoked"

    with pytest.raises(NotFound):
        await accept_invitation(
            token=issued.token, full_name="Too Late", password_hash=PASSWORD_HASH
        )


async def test_an_expired_link_is_refused_and_can_be_reissued(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    email = _email()
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
    )

    async with tenant_session(tenant_a) as session:
        row = (
            await session.execute(select(Invitation).where(Invitation.id == issued.invitation_id))
        ).scalar_one()
        row.expires_at = utcnow() - timedelta(minutes=1)

    with pytest.raises(NotFound):
        await accept_invitation(
            token=issued.token, full_name="Late Arrival", password_hash=PASSWORD_HASH
        )

    # The partial unique index only covers live rows, so a fresh invitation to the
    # same address must still be possible.
    reissued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
    )
    assert reissued.invitation_id != issued.invitation_id


async def test_one_live_invitation_per_address(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants
    email = _email()
    await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
    )

    with pytest.raises(Conflict):
        await invite_user(
            tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="admin"
        )


async def test_an_existing_member_cannot_be_invited_again(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    email = _email()
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
    )
    await accept_invitation(token=issued.token, full_name="Member", password_hash=PASSWORD_HASH)

    with pytest.raises(Conflict):
        await invite_user(
            tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
        )


async def test_an_admin_cannot_invite_an_owner(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants

    with pytest.raises(Forbidden):
        await invite_user(
            tenant_id=tenant_a,
            actor_id=uuid4(),
            actor_roles=("admin",),
            email=_email(),
            role="owner",
        )


async def test_an_invitation_is_invisible_to_another_tenant(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, tenant_b = seeded_tenants
    email = _email()
    await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="member"
    )

    listed_b = await list_invitations(tenant_id=tenant_b)
    assert all(item["email"] != email for item in listed_b)

    listed_a = await list_invitations(tenant_id=tenant_a)
    assert any(item["email"] == email and item["status"] == "pending" for item in listed_a)


async def test_a_forged_tenant_prefix_matches_nothing(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    """The tenant id in the token is routing, not authority."""
    tenant_a, tenant_b = seeded_tenants
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=_email(), role="member"
    )
    _, _, secret = issued.token.partition(".")

    with pytest.raises(NotFound):
        await accept_invitation(
            token=f"{tenant_b}.{secret}", full_name="Forger", password_hash=PASSWORD_HASH
        )


async def test_preview_discloses_only_what_the_recipient_needs(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    email = _email()
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=email, role="viewer"
    )

    preview = await peek_invitation(issued.token)
    assert preview["email"] == email
    assert preview["role"] == "viewer"
    assert set(preview) == {"email", "role", "organisation", "tenant_slug", "expires_at"}


async def test_acceptance_requires_a_name(wired_engine: Any, seeded_tenants: Any) -> None:
    tenant_a, _ = seeded_tenants
    issued = await invite_user(
        tenant_id=tenant_a, actor_id=uuid4(), actor_roles=("owner",), email=_email(), role="member"
    )

    with pytest.raises(ValidationError):
        await accept_invitation(token=issued.token, full_name="   ", password_hash=PASSWORD_HASH)
