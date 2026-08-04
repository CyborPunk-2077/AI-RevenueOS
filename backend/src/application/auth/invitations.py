"""Team invitations: invite, list, revoke, accept.

Three decisions worth stating, because each one is a place this could go wrong
quietly.

**An invitation is not a membership.** Inviting creates a token and nothing else.
The `app.users` row and its `user_roles` grant are written when the link is
redeemed, in one transaction with the acceptance. An abandoned invitation
therefore leaves no half-member behind, and the seat count reflects people who
actually joined.

**The inviter can never exceed their own authority.** A manager cannot mint an
owner. `assignable_roles` is the single source of that rule and both the service
and the API use it, so the check cannot drift between them.

**Acceptance runs before anyone is authenticated.** The token carries its tenant
(`<tenant_id>.<secret>`, the same shape the verification and reset tokens use), so
the lookup happens inside `tenant_session(...)` under the ordinary isolation
policy rather than through an elevated credential. Only the SHA-256 is stored: a
database reader cannot mint a link, and the row is found by hashing the whole
string, so a forged tenant prefix matches nothing.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import func, select

from application.audit.recorder import AuditRecorder
from domain.auth.permissions import ROLE_PERMISSIONS, Role
from infrastructure.database.models.users import Invitation, User, UserRole
from infrastructure.database.models.users import Role as RoleRow
from infrastructure.database.session import tenant_session
from infrastructure.logging.setup import get_logger
from infrastructure.observability.tracing import start_span
from shared.exceptions import Conflict, Forbidden, NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.text import normalize_email
from shared.utils.timeutil import utcnow

logger = get_logger("application.auth.invitations")

INVITATION_TTL: Final = timedelta(days=7)

_INVALID_LINK: Final = "This invitation is invalid, expired, or has already been used."

#: Who may hand out what. An invitation can never grant more than the inviter
#: holds: privilege escalation by invitation is otherwise a one-request attack.
ASSIGNABLE_ROLES: Final[dict[Role, frozenset[Role]]] = {
    Role.OWNER: frozenset({Role.OWNER, Role.ADMIN, Role.MANAGER, Role.MEMBER, Role.VIEWER}),
    Role.ADMIN: frozenset({Role.ADMIN, Role.MANAGER, Role.MEMBER, Role.VIEWER}),
    Role.MANAGER: frozenset({Role.MEMBER, Role.VIEWER}),
    Role.MEMBER: frozenset(),
    Role.VIEWER: frozenset(),
    # Support is a platform persona operating inside a tenant under an approved
    # grant. It reads; it does not staff the tenant.
    Role.SUPPORT: frozenset(),
}


def assignable_roles(actor_roles: tuple[str, ...] | list[str]) -> frozenset[Role]:
    """The widest set of roles this actor may invite someone into."""
    allowed: set[Role] = set()
    for raw in actor_roles:
        try:
            allowed |= ASSIGNABLE_ROLES[Role(raw)]
        except ValueError:  # an unknown role grants nothing
            continue
    return frozenset(allowed)


def _hash_token(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def _new_token(tenant_id: UUID) -> tuple[str, str]:
    plaintext = f"{tenant_id}.{secrets.token_urlsafe(32)}"
    return plaintext, _hash_token(plaintext)


def _split_token(plaintext: str) -> tuple[UUID, str]:
    prefix, _, secret = plaintext.partition(".")
    if not prefix or not secret:
        raise NotFound(_INVALID_LINK)
    try:
        return UUID(prefix), _hash_token(plaintext)
    except ValueError as exc:
        raise NotFound(_INVALID_LINK) from exc


@dataclass(frozen=True, slots=True)
class InvitationIssued:
    invitation_id: UUID
    tenant_id: UUID
    email: str
    role: Role
    expires_at: Any
    # Handed back rather than sent: email delivery is externally gated (ADR 0003),
    # so the route decides whether the environment may surface it.
    token: str


async def _role_row(session: Any, tenant_id: UUID, role: Role) -> RoleRow:
    """The tenant's row for a built-in role, created on first use.

    Sign-up only materialises `owner`. Inviting the first admin would otherwise
    fail on a missing row, which reads as a server error rather than what it is.
    """
    existing = (
        await session.execute(
            select(RoleRow).where(RoleRow.tenant_id == tenant_id, RoleRow.name == role.value)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    from infrastructure.database.models.users import RolePermission

    row = RoleRow(id=uuid7(), tenant_id=tenant_id, name=role.value, version=1)
    session.add(row)
    await session.flush()
    for code in sorted(ROLE_PERMISSIONS[role]):
        session.add(RolePermission(tenant_id=tenant_id, role_id=row.id, permission_code=code))
    return row


async def invite_user(
    *,
    tenant_id: UUID,
    actor_id: UUID,
    actor_roles: tuple[str, ...] | list[str],
    email: str,
    role: str,
) -> InvitationIssued:
    """Issue an invitation. Creates no user and grants nothing until redeemed."""
    normalized = normalize_email(email)
    if not normalized:
        raise ValidationError("A valid email address is required.")

    try:
        requested = Role(role)
    except ValueError as exc:
        raise ValidationError(f"{role!r} is not a role.") from exc

    permitted = assignable_roles(actor_roles)
    if requested not in permitted:
        raise Forbidden(
            "You cannot invite someone into a role above your own.",
            details={
                "requested_role": requested.value,
                "assignable": sorted(r.value for r in permitted),
            },
        )

    plaintext, token_hash = _new_token(tenant_id)
    invitation_id = uuid7()
    expires_at = utcnow() + INVITATION_TTL

    with start_span(
        "invitation issue",
        **{"tenant.id": str(tenant_id), "entity.type": "invitation"},
    ):
        async with tenant_session(tenant_id) as session:
            already_member = (
                await session.execute(
                    select(func.count())
                    .select_from(User)
                    .where(
                        User.tenant_id == tenant_id,
                        func.lower(User.email) == normalized,
                        User.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            if already_member:
                raise Conflict("That person is already a member of this organisation.")

            live = (
                await session.execute(
                    select(Invitation).where(
                        Invitation.tenant_id == tenant_id,
                        func.lower(Invitation.email) == normalized,
                        Invitation.accepted_at.is_(None),
                        Invitation.revoked_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if live is not None and live.expires_at > utcnow():
                raise Conflict(
                    "That person already has a pending invitation.",
                    details={"invitation_id": str(live.id)},
                )
            if live is not None:
                # Expired: retire it so the partial unique index stays satisfied.
                live.revoked_at = utcnow()

            role_row = await _role_row(session, tenant_id, requested)
            session.add(
                Invitation(
                    id=invitation_id,
                    tenant_id=tenant_id,
                    email=normalized,
                    role_id=role_row.id,
                    token_hash=token_hash,
                    invited_by=actor_id,
                    expires_at=expires_at,
                )
            )
            AuditRecorder(session).record(
                action="user.invited",
                resource_type="invitation",
                resource_id=invitation_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                # The address is the subject of the record, not a payload leak: an
                # audit trail that cannot say who was invited is not a trail.
                new_values={"email": normalized, "role": requested.value},
            )

    logger.info("invitation_issued", tenant_id=str(tenant_id), role=requested.value)
    return InvitationIssued(
        invitation_id=invitation_id,
        tenant_id=tenant_id,
        email=normalized,
        role=requested,
        expires_at=expires_at,
        token=plaintext,
    )


async def list_invitations(
    *, tenant_id: UUID, include_settled: bool = False
) -> list[dict[str, Any]]:
    """Pending invitations, newest first. Settled rows are opt-in."""
    async with tenant_session(tenant_id) as session:
        statement = select(Invitation, RoleRow.name).join(
            RoleRow, RoleRow.id == Invitation.role_id, isouter=True
        )
        statement = statement.where(Invitation.tenant_id == tenant_id)
        if not include_settled:
            statement = statement.where(
                Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None)
            )
        rows = (await session.execute(statement.order_by(Invitation.created_at.desc()))).all()

    now = utcnow()
    return [
        {
            "id": str(invitation.id),
            "email": invitation.email,
            "role": role_name,
            "invited_by": str(invitation.invited_by) if invitation.invited_by else None,
            "expires_at": invitation.expires_at.isoformat(),
            "accepted_at": invitation.accepted_at.isoformat() if invitation.accepted_at else None,
            "revoked_at": invitation.revoked_at.isoformat() if invitation.revoked_at else None,
            "status": _status(invitation, now),
        }
        for invitation, role_name in rows
    ]


def _status(invitation: Invitation, now: Any) -> str:
    if invitation.accepted_at is not None:
        return "accepted"
    if invitation.revoked_at is not None:
        return "revoked"
    if invitation.expires_at <= now:
        return "expired"
    return "pending"


async def revoke_invitation(
    *, tenant_id: UUID, actor_id: UUID, invitation_id: UUID
) -> dict[str, Any]:
    """Retire a pending invitation. Idempotent: revoking twice is not an error."""
    async with tenant_session(tenant_id) as session:
        invitation = (
            await session.execute(
                select(Invitation).where(
                    Invitation.id == invitation_id, Invitation.tenant_id == tenant_id
                )
            )
        ).scalar_one_or_none()
        if invitation is None:
            raise NotFound("That invitation does not exist.")
        if invitation.accepted_at is not None:
            raise Conflict(
                "That invitation was already accepted. Deactivate the user instead.",
                details={"invitation_id": str(invitation_id)},
            )
        if invitation.revoked_at is None:
            invitation.revoked_at = utcnow()
            AuditRecorder(session).record(
                action="user.invitation_revoked",
                resource_type="invitation",
                resource_id=invitation_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                old_values={"status": "pending"},
                new_values={"status": "revoked"},
            )
        revoked_at = invitation.revoked_at

    logger.info("invitation_revoked", tenant_id=str(tenant_id))
    return {"id": str(invitation_id), "status": "revoked", "revoked_at": revoked_at.isoformat()}


async def peek_invitation(token: str) -> dict[str, Any]:
    """What the acceptance screen may show before anyone has signed in.

    Deliberately thin: the organisation name and the email the link was issued to,
    so the recipient can tell they are joining the right place. No member list, no
    inviter identity, nothing that a leaked link should disclose.
    """
    tenant_id, token_hash = _split_token(token)

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                select(Invitation, RoleRow.name)
                .join(RoleRow, RoleRow.id == Invitation.role_id, isouter=True)
                .where(Invitation.token_hash == token_hash, Invitation.tenant_id == tenant_id)
            )
        ).first()
        if row is None:
            raise NotFound(_INVALID_LINK)
        invitation, role_name = row
        if _status(invitation, utcnow()) != "pending":
            raise NotFound(_INVALID_LINK)

        from infrastructure.database.models.tenancy import Tenant

        tenant = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()

    return {
        "email": invitation.email,
        "role": role_name,
        "organisation": tenant.name if tenant else None,
        "tenant_slug": tenant.slug if tenant else None,
        "expires_at": invitation.expires_at.isoformat(),
    }


async def accept_invitation(*, token: str, full_name: str, password_hash: str) -> dict[str, Any]:
    """Redeem an invitation: create the user, grant the role, settle the token.

    One transaction. A crash between creating the user and granting the role would
    otherwise leave someone signed in with no permissions and no way to fix it
    themselves.

    The caller hashes the password. This module does not import the password
    hasher so that the argon2 parameters live in exactly one place.
    """
    tenant_id, token_hash = _split_token(token)
    user_id = uuid7()

    with start_span("invitation accept", **{"tenant.id": str(tenant_id)}):
        async with tenant_session(tenant_id) as session:
            invitation = (
                await session.execute(
                    select(Invitation).where(
                        Invitation.token_hash == token_hash, Invitation.tenant_id == tenant_id
                    )
                )
            ).scalar_one_or_none()
            if invitation is None or _status(invitation, utcnow()) != "pending":
                raise NotFound(_INVALID_LINK)

            clash = (
                await session.execute(
                    select(func.count())
                    .select_from(User)
                    .where(
                        User.tenant_id == tenant_id,
                        func.lower(User.email) == invitation.email,
                        User.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            if clash:
                # Someone signed up with the invited address in the meantime.
                # Settling the invitation keeps the state machine honest.
                invitation.accepted_at = utcnow()
                raise Conflict("That address already belongs to a member of this organisation.")

            name = full_name.strip()[:200]
            if not name:
                raise ValidationError("A name is required.")

            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=invitation.email,
                    full_name=name,
                    password_hash=password_hash,
                    password_changed_at=utcnow(),
                    # Redeeming the link proves the address, so there is no second
                    # confirmation email to send.
                    email_verified_at=utcnow(),
                    status="active",
                    is_owner=False,
                    version=1,
                )
            )
            if invitation.role_id is not None:
                session.add(
                    UserRole(tenant_id=tenant_id, user_id=user_id, role_id=invitation.role_id)
                )
            invitation.accepted_at = utcnow()

            role_name = (
                await session.execute(select(RoleRow.name).where(RoleRow.id == invitation.role_id))
            ).scalar_one_or_none()

            AuditRecorder(session).record(
                action="user.invitation_accepted",
                resource_type="user",
                resource_id=user_id,
                tenant_id=tenant_id,
                actor_id=user_id,
                actor_type="user",
                new_values={"email": invitation.email, "role": role_name, "status": "active"},
                metadata={"invitation_id": str(invitation.id)},
            )

    logger.info("invitation_accepted", tenant_id=str(tenant_id), user_id=str(user_id))
    return {
        "user_id": str(user_id),
        "tenant_id": str(tenant_id),
        "email": invitation.email,
        "role": role_name,
    }
