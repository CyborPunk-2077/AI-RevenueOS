"""Public form configuration and submission. Source events are always preserved."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from shared.exceptions import Forbidden, NotFound
from shared.utils.ids import uuid7


async def get_published_form(form_id: UUID) -> dict[str, Any] | None:
    from sqlalchemy import select

    from infrastructure.database.models.leads import Form
    from infrastructure.database.session import unscoped_session

    async with unscoped_session() as session:
        form = (
            await session.execute(
                select(Form).where(Form.id == form_id, Form.is_published.is_(True))
            )
        ).scalar_one_or_none()
    if form is None:
        return None
    return {
        "id": str(form.id),
        "name": form.name,
        "type": form.form_type,
        "schema": form.published_schema,
        "allowed_origins": form.allowed_origins,
    }


def origin_allowed(origin: str, allowed: list[str]) -> bool:
    if not allowed:
        return True
    return origin in allowed


async def submit_public_form(
    *,
    form_id: UUID,
    payload: dict[str, Any],
    origin: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> dict[str, Any]:
    import hashlib

    from domain.leads.lifecycle import dedupe_key
    from infrastructure.database.models.leads import LeadSourceEvent
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    form = await get_published_form(form_id)
    if form is None:
        raise NotFound("Form not found.")
    if not origin_allowed(origin, form.get("allowed_origins", [])):
        raise Forbidden("This origin is not permitted to submit the form.")

    from sqlalchemy import select

    from infrastructure.database.models.leads import Form
    from infrastructure.database.session import unscoped_session

    async with unscoped_session() as session:
        tenant_id = (
            await session.execute(select(Form.tenant_id).where(Form.id == form_id))
        ).scalar_one()

    event_id = uuid7()
    async with SqlAlchemyUnitOfWork(tenant_id) as uow:
        uow.session.add(
            LeadSourceEvent(
                id=event_id,
                tenant_id=tenant_id,
                source=f"form:{form_id}",
                source_channel="web_form",
                source_idempotency_key=str(event_id),
                raw_payload={k: v for k, v in payload.items() if k != "anti_abuse_token"},
                normalized={
                    "dedupe_key": dedupe_key(
                        email=payload.get("email"),
                        phone=payload.get("phone"),
                        name=payload.get("first_name"),
                    )
                },
                utm=payload.get("utm", {}),
                ip_hash=hashlib.sha256((ip or "").encode()).hexdigest() if ip else None,
                user_agent=(user_agent or "")[:500] or None,
                form_id=form_id,
                outcome="received",
            )
        )
    return {"source_event_id": str(event_id)}
