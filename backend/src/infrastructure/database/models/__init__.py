"""Import every model module so Alembic autogenerate sees the full metadata."""

from __future__ import annotations

from infrastructure.database.base import Base
from infrastructure.database.models import (  # noqa: F401
    ai,
    analytics,
    appointments,
    audit,
    communications,
    crm,
    documents,
    leads,
    operational,
    payments,
    reference,
    tenancy,
    users,
    workflows,
)

__all__ = ["Base"]
