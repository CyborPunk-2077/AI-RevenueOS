"""Declarative base and the mixins that make multi-tenancy structurally mandatory."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Index, MetaData, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from shared.utils.ids import uuid7

SCHEMA_APP = "app"
SCHEMA_PUBLIC = "public"
SCHEMA_AUDIT = "audit"
SCHEMA_ANALYTICS = "analytics"

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata_obj = MetaData(naming_convention=NAMING_CONVENTION)


def json_column(**kwargs: Any) -> Mapped[dict[str, Any]]:
    return mapped_column(JSONB, **kwargs)


class Base(DeclarativeBase):
    metadata = metadata_obj

    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        int: BigInteger,
    }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        pk = getattr(self, "id", None)
        return f"<{type(self).__name__} id={pk}>"


class IdMixin:
    """UUIDv7 primary key generated application side for time-ordered inserts."""

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid7, sort_order=-100
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, sort_order=101
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True, sort_order=102
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class VersionMixin:
    """Optimistic concurrency for editable records; surfaced to clients as an ETag."""

    version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1, sort_order=103)

    __mapper_args__ = {"version_id_col": None}


class TenantMixin:
    """Every tenant-owned row carries a non-null tenant_id indexed first."""

    tenant_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False, index=True, sort_order=-99
    )

    @declared_attr.directive
    def __table_args__(cls) -> tuple[Any, ...]:  # noqa: N805
        table_name: str = cls.__tablename__  # type: ignore[attr-defined]
        return (
            Index(f"ix_{table_name}_tenant_created", "tenant_id", "created_at"),
            {"schema": SCHEMA_APP},
        )


class ActorMixin:
    created_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, sort_order=104
    )
    updated_by: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True, sort_order=105
    )


def short_str(length: int = 255, **kwargs: Any) -> Mapped[str]:
    return mapped_column(String(length), **kwargs)


TENANT_OWNED_TABLES: set[str] = set()


def register_tenant_table(name: str) -> None:
    """Registry used by the RLS migration and the isolation test suite."""
    TENANT_OWNED_TABLES.add(name)
