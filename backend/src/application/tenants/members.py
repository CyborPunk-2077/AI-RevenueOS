"""Who works here: the list every "assign to" control needs.

Deliberately narrow. This returns the id, display name, email and active flag of
the people in one organisation and nothing else - not their roles, not their
sessions, not their MFA state. An assignee picker is not a reason to hand the
browser a user directory.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID


async def list_members(*, tenant_id: UUID) -> list[dict[str, Any]]:
    """Active users first, then alphabetical, so the picker is stable."""
    from sqlalchemy import select

    from infrastructure.database.models.users import User
    from infrastructure.database.session import tenant_session

    async with tenant_session(tenant_id) as session:
        rows = (
            (
                await session.execute(
                    select(User)
                    .where(User.tenant_id == tenant_id, User.deleted_at.is_(None))
                    .order_by(User.full_name.asc())
                    .limit(500)
                )
            )
            .scalars()
            .all()
        )

    members = [
        {
            "id": str(row.id),
            "full_name": row.full_name,
            "email": row.email,
            "is_active": row.status == "active",
        }
        for row in rows
    ]
    members.sort(key=lambda m: (not m["is_active"], str(m["full_name"] or "").lower()))
    return members
