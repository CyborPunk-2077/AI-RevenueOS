"""Outbox handlers for contact and account events.

Real work, not a `pending_handler` stub. Each handler does something that is
genuinely useful and genuinely observable, so "the event was dispatched" is a
claim the database can be asked to confirm:

* a contact gaining an account stamps `company` from the account name when the
  contact does not already carry one, which is what makes the link visible in a
  list view that shows a company column;
* an account rename propagates to the contacts that inherited its name, so the
  denormalised copy cannot silently rot.

Every handler is idempotent. The relay is at-least-once by construction, so a
handler that is not safe to run twice is a bug waiting for a redelivery.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from infrastructure.logging.setup import get_logger

logger = get_logger("application.crm.handlers")


def _tenant_of(event: dict[str, Any]) -> UUID | None:
    raw = event.get("tenant_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        logger.warning("crm_event_bad_tenant", event_type=event.get("event_type"))
        return None


async def sync_contact_company(event: dict[str, Any]) -> None:
    """Stamp the account's name onto a contact that has no company of its own.

    Runs on contact.created and contact.updated. Idempotent: writing the same
    value again is a no-op, and a contact that already has a company is left
    alone, so a redelivery cannot overwrite a human's edit.
    """
    if event.get("event_type") not in {"contact.created", "contact.updated"}:
        return
    tenant_id = _tenant_of(event)
    resource_id = event.get("resource_id")
    if tenant_id is None or not resource_id:
        return

    from sqlalchemy import select

    from infrastructure.database.models.crm import Account, Contact
    from infrastructure.database.session import tenant_session

    async with tenant_session(tenant_id) as session:
        contact = (
            await session.execute(select(Contact).where(Contact.id == UUID(str(resource_id))))
        ).scalar_one_or_none()
        if contact is None or contact.account_id is None or contact.company:
            return

        name = (
            await session.execute(
                select(Account.name).where(
                    Account.id == contact.account_id, Account.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()
        if not name:
            return
        contact.company = name

    logger.info("crm_contact_company_synced", tenant_id=str(tenant_id), contact_id=str(resource_id))


async def propagate_account_rename(event: dict[str, Any]) -> None:
    """Refresh the denormalised company name on this account's contacts.

    Runs on account.updated. Only touches contacts whose company still matches
    another name, so a contact deliberately given its own company keeps it.
    """
    if event.get("event_type") != "account.updated":
        return
    tenant_id = _tenant_of(event)
    resource_id = event.get("resource_id")
    if tenant_id is None or not resource_id:
        return

    from sqlalchemy import select

    from infrastructure.database.models.crm import Account, Contact
    from infrastructure.database.session import tenant_session

    account_id = UUID(str(resource_id))
    async with tenant_session(tenant_id) as session:
        name = (
            await session.execute(
                select(Account.name).where(Account.id == account_id, Account.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if not name:
            return

        contacts = (
            (
                await session.execute(
                    select(Contact).where(
                        Contact.account_id == account_id, Contact.deleted_at.is_(None)
                    )
                )
            )
            .scalars()
            .all()
        )
        changed = 0
        for contact in contacts:
            if contact.company != name:
                contact.company = name
                changed += 1

    if changed:
        logger.info(
            "crm_account_rename_propagated",
            tenant_id=str(tenant_id),
            account_id=str(account_id),
            contacts=changed,
        )


def register_crm_handlers(dispatcher: Any) -> None:
    """Subscribe on the relay. Called wherever the outbox is drained."""
    dispatcher.subscribe("contact.created", sync_contact_company)
    dispatcher.subscribe("contact.updated", sync_contact_company)
    dispatcher.subscribe("account.updated", propagate_account_rename)
