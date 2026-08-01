"""Contact and account application services.

Deliberately shaped like `application/leads/service.py`: constructed per request
from the authenticated principal, every read through `scoped_query`/`get_scoped`,
every write inside a `SqlAlchemyUnitOfWork` so the row and its outbox event commit
or roll back together.

Two rules are load-bearing and easy to get wrong:

* Reads use the *scoped* helpers, not a bare tenant filter. A tenant filter alone
  lets a self-scoped Member read any record in the tenant by guessing an id --
  the in-tenant IDOR the audit recorded as A4.
* The audit entry is written inside the same unit of work as the change. Recording
  it afterwards would leave a successful write with no trail whenever the process
  died in between, which is precisely when the trail matters.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from domain.auth.permissions import EffectivePermissions, Scope
from domain.base import DomainEvent
from domain.events.catalog import (
    ACCOUNT_CREATED,
    ACCOUNT_UPDATED,
    CONTACT_CREATED,
    CONTACT_UPDATED,
)
from infrastructure.logging.setup import get_logger
from shared.exceptions import Conflict, NotFound, ValidationError
from shared.pagination import Page
from shared.utils.ids import uuid7

logger = get_logger("application.crm")

CONTACT_STATUSES = frozenset({"active", "inactive", "archived"})


def _json_safe(value: Any) -> Any:
    """JSONB cannot hold UUID or datetime objects; Pydantic hands us real ones."""
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def serialize_contact(contact: Any, *, account_name: str | None = None) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "phone": contact.phone,
        "company": contact.company,
        "title": contact.title,
        "status": contact.status,
        "source": contact.source,
        "tags": list(contact.tags or []),
        "account_id": str(contact.account_id) if contact.account_id else None,
        "account_name": account_name,
        "assignee_id": str(contact.assignee_id) if contact.assignee_id else None,
        "version": contact.version,
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


def serialize_account(account: Any, *, contact_count: int | None = None) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "name": account.name,
        "industry": account.industry,
        "website": account.website,
        "phone": account.phone,
        "employee_count": account.employee_count,
        "owner_id": str(account.owner_id) if account.owner_id else None,
        "contact_count": contact_count,
        "version": account.version,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
    }


@dataclass(slots=True)
class _PrincipalScoped:
    """Shared construction and scope resolution."""

    tenant_id: UUID
    user_id: UUID
    permissions: frozenset[str]
    scope: Scope = Scope.GLOBAL
    branch_ids: frozenset[str] = frozenset()
    team_ids: frozenset[str] = frozenset()

    @classmethod
    def for_principal(cls, principal: Any) -> Any:
        return cls(
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            permissions=principal.permissions,
            scope=principal.scope,
            branch_ids=principal.branch_ids,
            team_ids=principal.team_ids,
        )

    def permissions_scope(self) -> EffectivePermissions:
        return EffectivePermissions(
            permissions=self.permissions,
            scope=self.scope,
            branch_ids=self.branch_ids,
            team_ids=self.team_ids,
            user_id=str(self.user_id),
        )


@dataclass(slots=True)
class ContactService(_PrincipalScoped):
    """Contacts: list, search, read, create, update, and link to an account."""

    async def list_contacts(self, query: Any, *, search: str | None = None) -> Page:
        from sqlalchemy import func, or_

        from infrastructure.database.models.crm import Account, Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        async with tenant_session(self.tenant_id) as session:
            repo = ContactRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())

            if search and search.strip():
                # Filtered in SQL, inside the already-scoped statement. Searching
                # after the fetch would page over rows the caller may not read.
                needle = f"%{search.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Contact.first_name).like(needle),
                        func.lower(func.coalesce(Contact.last_name, "")).like(needle),
                        func.lower(func.coalesce(Contact.email, "")).like(needle),
                        func.lower(func.coalesce(Contact.company, "")).like(needle),
                        func.coalesce(Contact.phone, "").like(needle),
                    )
                )

            page = await repo.paginate_cursor(stmt, cursor=query.cursor, page_size=query.page_size)

            # One extra query for the account names rather than N+1 per row.
            account_ids = {c.account_id for c in page.items if c.account_id}
            names: dict[UUID, str] = {}
            if account_ids:
                from sqlalchemy import select

                rows = await session.execute(
                    select(Account.id, Account.name).where(
                        Account.id.in_(account_ids),
                        Account.tenant_id == self.tenant_id,
                        Account.deleted_at.is_(None),
                    )
                )
                names = {row[0]: row[1] for row in rows}

            page.items = [
                serialize_contact(c, account_name=names.get(c.account_id) if c.account_id else None)
                for c in page.items
            ]
            return page

    async def get(self, contact_id: UUID) -> dict[str, Any]:
        from sqlalchemy import select

        from infrastructure.database.models.crm import Account, Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        async with tenant_session(self.tenant_id) as session:
            contact = await ContactRepository(session, self.tenant_id).get_scoped(
                contact_id, self.permissions_scope()
            )
            if contact is None:
                # Another tenant's record is invisible under RLS and reports as
                # absent, which is the same answer as a record that never existed.
                raise NotFound("Contact not found.")

            account_name = None
            if contact.account_id:
                account_name = (
                    await session.execute(
                        select(Account.name).where(
                            Account.id == contact.account_id,
                            Account.tenant_id == self.tenant_id,
                            Account.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
            return serialize_contact(contact, account_name=account_name)

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Contact
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        if not payload.get("email") and not payload.get("phone"):
            # Mirrors the table's `email_or_phone` check constraint, so the caller
            # gets a typed 422 instead of an IntegrityError surfacing as a 500.
            raise ValidationError("A contact needs an email address or a phone number.")

        contact_id = uuid7()
        account_id = payload.get("account_id")

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            if account_id:
                await self._assert_account_exists(uow.session, account_id)

            uow.session.add(
                Contact(
                    id=contact_id,
                    tenant_id=self.tenant_id,
                    first_name=payload["first_name"],
                    last_name=payload.get("last_name"),
                    email=payload.get("email"),
                    phone=payload.get("phone"),
                    company=payload.get("company"),
                    title=payload.get("title"),
                    status="active",
                    source=payload.get("source", "manual"),
                    address=_json_safe(payload.get("address") or {}),
                    custom_fields=_json_safe(payload.get("custom_fields") or {}),
                    tags=list(payload.get("tags") or []),
                    account_id=account_id,
                    assignee_id=payload.get("assignee_id") or self.user_id,
                    branch_id=payload.get("branch_id"),
                    team_id=payload.get("team_id"),
                    created_by=self.user_id,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="contact.create",
                resource_type="contact",
                resource_id=contact_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"email": payload.get("email"), "first_name": payload["first_name"]},
            )
            uow.collect(
                DomainEvent(
                    event_type=CONTACT_CREATED,
                    tenant_id=self.tenant_id,
                    resource_type="contact",
                    resource_id=contact_id,
                    actor_id=self.user_id,
                    payload={"account_id": str(account_id) if account_id else None},
                )
            )

        logger.info("contact_created", tenant_id=str(self.tenant_id), contact_id=str(contact_id))
        return await self.get(contact_id)

    async def update(
        self, contact_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder, diff_for_audit
        from infrastructure.database.models.crm import Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        if "status" in changes and changes["status"] not in CONTACT_STATUSES:
            raise ValidationError(
                f"Unknown status. Expected one of: {', '.join(sorted(CONTACT_STATUSES))}."
            )

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = ContactRepository(uow.session, self.tenant_id)
            contact = await repo.get_scoped_or_404(contact_id, self.permissions_scope())

            before = serialize_contact(contact)
            if changes.get("account_id"):
                await self._assert_account_exists(uow.session, changes["account_id"])

            for field_name, value in changes.items():
                # `account_id: None` is a real instruction -- unlink -- so it is
                # applied, unlike the other fields where None means "not supplied".
                if field_name == "account_id" or value is not None:
                    setattr(contact, field_name, value)

            await repo.bump_version(contact, expected_version)
            contact.updated_by = self.user_id
            after = serialize_contact(contact)

            old_values, new_values = diff_for_audit(before, after)
            AuditRecorder(uow.session).record(
                action="contact.update",
                resource_type="contact",
                resource_id=contact_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values=old_values,
                new_values=new_values,
            )
            uow.collect(
                DomainEvent(
                    event_type=CONTACT_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="contact",
                    resource_id=contact_id,
                    actor_id=self.user_id,
                    payload={"changed": sorted(changes)},
                )
            )
        return await self.get(contact_id)

    async def _assert_account_exists(self, session: Any, account_id: UUID) -> None:
        """An account from another tenant must be as absent as one that never was."""
        from infrastructure.database.models.crm import Account
        from infrastructure.database.repositories.base import TenantRepository

        class AccountRepository(TenantRepository[Account]):
            model = Account

        if await AccountRepository(session, self.tenant_id).get(account_id) is None:
            raise NotFound("Account not found.")


@dataclass(slots=True)
class AccountService(_PrincipalScoped):
    """Accounts: list, read, create, update, and list their contacts."""

    async def list_accounts(self, query: Any, *, search: str | None = None) -> Page:
        from sqlalchemy import func, or_, select

        from infrastructure.database.models.crm import Account, Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class AccountRepository(TenantRepository[Account]):
            model = Account

        async with tenant_session(self.tenant_id) as session:
            repo = AccountRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope())
            if search and search.strip():
                needle = f"%{search.strip().lower()}%"
                stmt = stmt.where(
                    or_(
                        func.lower(Account.name).like(needle),
                        func.lower(func.coalesce(Account.industry, "")).like(needle),
                    )
                )
            page = await repo.paginate_cursor(stmt, cursor=query.cursor, page_size=query.page_size)

            ids = [a.id for a in page.items]
            counts: dict[UUID, int] = {}
            if ids:
                rows = await session.execute(
                    select(Contact.account_id, func.count())
                    .where(
                        Contact.account_id.in_(ids),
                        Contact.tenant_id == self.tenant_id,
                        Contact.deleted_at.is_(None),
                    )
                    .group_by(Contact.account_id)
                )
                counts = {row[0]: int(row[1]) for row in rows}

            page.items = [
                serialize_account(a, contact_count=counts.get(a.id, 0)) for a in page.items
            ]
            return page

    async def get(self, account_id: UUID) -> dict[str, Any]:
        from sqlalchemy import func, select

        from infrastructure.database.models.crm import Account, Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class AccountRepository(TenantRepository[Account]):
            model = Account

        async with tenant_session(self.tenant_id) as session:
            account = await AccountRepository(session, self.tenant_id).get_scoped(
                account_id, self.permissions_scope()
            )
            if account is None:
                raise NotFound("Account not found.")
            count = (
                await session.execute(
                    select(func.count()).where(
                        Contact.account_id == account_id,
                        Contact.tenant_id == self.tenant_id,
                        Contact.deleted_at.is_(None),
                    )
                )
            ).scalar_one()
            return serialize_account(account, contact_count=int(count))

    async def contacts_for(self, account_id: UUID) -> list[dict[str, Any]]:
        """The contacts linked to one account, scoped like every other read."""
        from infrastructure.database.models.crm import Contact
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.database.session import tenant_session

        class ContactRepository(TenantRepository[Contact]):
            model = Contact

        await self.get(account_id)  # 404s before revealing anything about the account

        async with tenant_session(self.tenant_id) as session:
            repo = ContactRepository(session, self.tenant_id)
            stmt = repo.scoped_query(self.permissions_scope()).where(
                Contact.account_id == account_id
            )
            rows = (await session.execute(stmt)).scalars().all()
            return [serialize_contact(c) for c in rows]

    async def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        from sqlalchemy import func, select

        from application.audit.recorder import AuditRecorder
        from infrastructure.database.models.crm import Account
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        name = str(payload["name"]).strip()
        account_id = uuid7()

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            # `uq_accounts_tenant_name_active` would raise an IntegrityError, which
            # surfaces as a 500. Checking first turns it into a typed 409.
            clash = (
                await uow.session.execute(
                    select(Account.id).where(
                        Account.tenant_id == self.tenant_id,
                        func.lower(Account.name) == name.lower(),
                        Account.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise Conflict("An account with that name already exists.")

            uow.session.add(
                Account(
                    id=account_id,
                    tenant_id=self.tenant_id,
                    name=name,
                    industry=payload.get("industry"),
                    website=payload.get("website"),
                    phone=payload.get("phone"),
                    address=_json_safe(payload.get("address") or {}),
                    custom_fields=_json_safe(payload.get("custom_fields") or {}),
                    employee_count=payload.get("employee_count"),
                    owner_id=payload.get("owner_id") or self.user_id,
                    created_by=self.user_id,
                    version=1,
                )
            )
            AuditRecorder(uow.session).record(
                action="account.create",
                resource_type="account",
                resource_id=account_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                new_values={"name": name},
            )
            uow.collect(
                DomainEvent(
                    event_type=ACCOUNT_CREATED,
                    tenant_id=self.tenant_id,
                    resource_type="account",
                    resource_id=account_id,
                    actor_id=self.user_id,
                    payload={"name": name},
                )
            )

        logger.info("account_created", tenant_id=str(self.tenant_id), account_id=str(account_id))
        return await self.get(account_id)

    async def update(
        self, account_id: UUID, changes: dict[str, Any], *, expected_version: int | None = None
    ) -> dict[str, Any]:
        from application.audit.recorder import AuditRecorder, diff_for_audit
        from infrastructure.database.models.crm import Account
        from infrastructure.database.repositories.base import TenantRepository
        from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

        class AccountRepository(TenantRepository[Account]):
            model = Account

        async with SqlAlchemyUnitOfWork(self.tenant_id) as uow:
            repo = AccountRepository(uow.session, self.tenant_id)
            account = await repo.get_scoped_or_404(account_id, self.permissions_scope())
            before = serialize_account(account)

            for field_name, value in changes.items():
                if value is not None:
                    setattr(account, field_name, value)

            await repo.bump_version(account, expected_version)
            account.updated_by = self.user_id
            after = serialize_account(account)

            old_values, new_values = diff_for_audit(before, after)
            AuditRecorder(uow.session).record(
                action="account.update",
                resource_type="account",
                resource_id=account_id,
                tenant_id=self.tenant_id,
                actor_id=self.user_id,
                old_values=old_values,
                new_values=new_values,
            )
            uow.collect(
                DomainEvent(
                    event_type=ACCOUNT_UPDATED,
                    tenant_id=self.tenant_id,
                    resource_type="account",
                    resource_id=account_id,
                    actor_id=self.user_id,
                    payload={"changed": sorted(changes)},
                )
            )
        return await self.get(account_id)
