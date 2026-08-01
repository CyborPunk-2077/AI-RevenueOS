"""Public booking. Concurrency safety comes from the slot_locks unique constraint."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from shared.exceptions import Conflict, ValidationError
from shared.utils.ids import uuid7
from shared.utils.timeutil import ensure_utc, utcnow

LOCK_TTL_MINUTES = 10


async def claim_public_slot(
    body: dict[str, Any], *, idempotency_key: str | None = None
) -> dict[str, Any]:
    """A second concurrent claim on the same slot raises 409, never a double booking."""
    from sqlalchemy.exc import IntegrityError

    from infrastructure.database.models.appointments import Appointment, SlotLock
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    for field in ("tenant_id", "resource_id", "start_at", "end_at"):
        if field not in body:
            raise ValidationError(f"'{field}' is required.")

    tenant_id = UUID(str(body["tenant_id"]))
    resource_id = UUID(str(body["resource_id"]))
    start_at = ensure_utc(datetime.fromisoformat(str(body["start_at"])))
    end_at = ensure_utc(datetime.fromisoformat(str(body["end_at"])))
    if end_at <= start_at:
        raise ValidationError("The appointment must end after it starts.")

    appointment_id = uuid7()
    try:
        async with SqlAlchemyUnitOfWork(tenant_id) as uow:
            uow.session.add(
                SlotLock(
                    tenant_id=tenant_id,
                    resource_id=resource_id,
                    start_at=start_at,
                    end_at=end_at,
                    slot_index=int(body.get("slot_index", 0)),
                    appointment_id=appointment_id,
                    idempotency_key=idempotency_key,
                    expires_at=utcnow() + timedelta(minutes=LOCK_TTL_MINUTES),
                )
            )
            uow.session.add(
                Appointment(
                    id=appointment_id,
                    tenant_id=tenant_id,
                    resource_id=resource_id,
                    title=str(body.get("title", "Appointment"))[:250],
                    start_at=start_at,
                    end_at=end_at,
                    status="scheduled",
                    location_type=str(body.get("location_type", "physical")),
                    intake=body.get("intake", {}),
                    version=1,
                )
            )
            await uow.flush()
    except IntegrityError as exc:
        raise Conflict(
            "That slot has just been taken. Please choose another time.",
            details={"start_at": start_at.isoformat()},
        ) from exc

    return {"appointment_id": str(appointment_id), "status": "scheduled"}
