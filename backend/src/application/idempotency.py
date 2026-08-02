"""Database-backed idempotency for security-sensitive mutations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from infrastructure.database.models.audit import IdempotencyRecord
from shared.exceptions import IdempotencyConflict, ValidationError
from shared.utils.ids import uuid7
from shared.utils.text import canonical_json
from shared.utils.timeutil import utcnow


def hash_payload(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


@dataclass(slots=True)
class DurableIdempotency:
    """Reservation committed in the same transaction as the business mutation."""

    record: IdempotencyRecord | None
    replay: dict[str, Any] | None = None

    def complete(self, *, status: int, body: dict[str, Any]) -> None:
        if self.record is None:
            return
        self.record.response_status = status
        self.record.response_body = body
        self.record.state = "completed"


async def reserve_idempotency(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    scope: str,
    key: str | None,
    request_hash: str,
) -> DurableIdempotency:
    """Serialize one tenant/key and return a committed replay when present."""
    normalized = (key or "").strip()
    if not normalized:
        raise ValidationError("An Idempotency-Key header is required for this operation.")
    if len(normalized) > 200:
        raise ValidationError("Idempotency-Key must be at most 200 characters.")

    lock_key = f"idempotency:{tenant_id}:{scope}:{normalized}"
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": lock_key}
    )
    existing = await session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.scope == scope,
            IdempotencyRecord.idempotency_key == normalized,
        )
    )
    if existing is not None:
        if existing.request_hash != request_hash:
            raise IdempotencyConflict(
                "This idempotency key was already used with a different payload.",
                details={"scope": scope},
            )
        if existing.state == "completed":
            return DurableIdempotency(record=None, replay=dict(existing.response_body or {}))
        raise IdempotencyConflict(
            "A request with this idempotency key is still being processed.",
            details={"scope": scope, "retry_after": 2},
        )

    now = utcnow()
    record = IdempotencyRecord(
        id=uuid7(),
        tenant_id=tenant_id,
        scope=scope,
        idempotency_key=normalized,
        request_hash=request_hash,
        response_status=0,
        response_body={},
        state="in_progress",
        created_at=now,
        expires_at=now + timedelta(hours=24),
    )
    session.add(record)
    await session.flush()
    return DurableIdempotency(record=record)
