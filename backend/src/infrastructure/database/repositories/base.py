"""Repository base. Tenant filtering here is the first of two isolation layers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Generic, TypeVar
from uuid import UUID

from sqlalchemy import Select, false, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from domain.auth.permissions import EffectivePermissions, Scope
from infrastructure.monitoring.metrics import tenant_isolation_violations
from shared.exceptions import NotFound, PreconditionFailed
from shared.pagination import Page, clamp_page_size, decode_cursor, encode_cursor
from shared.utils.timeutil import utcnow

M = TypeVar("M")


class TenantRepository(Generic[M]):
    """Every query is tenant filtered before it is executed, never after fetching."""

    model: type[Any]
    soft_delete = True

    def __init__(self, session: AsyncSession, tenant_id: UUID) -> None:
        if tenant_id is None:
            tenant_isolation_violations.labels(surface="repository").inc()
            raise ValueError("repository requires a tenant id")
        self.session = session
        self.tenant_id = tenant_id

    # -- query construction ------------------------------------------------
    def base_query(self, *, include_deleted: bool = False) -> Select[Any]:
        stmt = select(self.model).where(self.model.tenant_id == self.tenant_id)
        if self.soft_delete and not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        return stmt

    def apply_scope(self, stmt: Select[Any], perms: EffectivePermissions) -> Select[Any]:
        """Apply branch/team/self scope inside the query, per the role matrix.

        Fails closed: if the model carries the scoping column but the principal has
        no qualifying identifiers, the query returns nothing rather than everything.
        """
        if perms.scope is Scope.GLOBAL:
            return stmt

        if perms.scope is Scope.BRANCH:
            if not hasattr(self.model, "branch_id"):
                return stmt
            ids = [UUID(b) for b in perms.branch_ids]
            return stmt.where(self.model.branch_id.in_(ids)) if ids else stmt.where(false())

        if perms.scope is Scope.TEAM:
            if not hasattr(self.model, "team_id"):
                return stmt
            ids = [UUID(t) for t in perms.team_ids]
            return stmt.where(self.model.team_id.in_(ids)) if ids else stmt.where(false())

        if perms.scope is Scope.SELF:
            if not hasattr(self.model, "assignee_id"):
                return stmt
            # "Assigned to me" is a predicate on the acting user, never on their
            # teams. A principal without a user id can see nothing at self scope.
            if not perms.user_id:
                return stmt.where(false())
            return stmt.where(self.model.assignee_id == UUID(perms.user_id))

        return stmt

    def scoped_query(
        self, perms: EffectivePermissions, *, include_deleted: bool = False
    ) -> Select[Any]:
        """Tenant filter plus role scope. List endpoints must use this, not `base_query`."""
        return self.apply_scope(self.base_query(include_deleted=include_deleted), perms)

    # -- reads -------------------------------------------------------------
    async def get(self, entity_id: UUID, *, include_deleted: bool = False) -> M | None:
        stmt = self.base_query(include_deleted=include_deleted).where(self.model.id == entity_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_or_404(self, entity_id: UUID) -> M:
        found = await self.get(entity_id)
        if found is None:
            raise NotFound(f"{self.model.__name__} not found.")
        return found

    async def get_scoped(
        self, entity_id: UUID, perms: EffectivePermissions, *, include_deleted: bool = False
    ) -> M | None:
        """Object read under role scope as well as tenant scope.

        Scoping only list queries would leave an in-tenant IDOR: a self-scoped
        principal could still read any record by guessing or replaying its id.
        """
        stmt = self.scoped_query(perms, include_deleted=include_deleted).where(
            self.model.id == entity_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_scoped_or_404(self, entity_id: UUID, perms: EffectivePermissions) -> M:
        """Out-of-scope records are indistinguishable from absent ones, by design."""
        found = await self.get_scoped(entity_id, perms)
        if found is None:
            raise NotFound(f"{self.model.__name__} not found.")
        return found

    async def count(self, stmt: Select[Any] | None = None) -> int:
        base = stmt if stmt is not None else self.base_query()
        counted = select(func.count()).select_from(base.subquery())
        return int((await self.session.execute(counted)).scalar_one())

    async def paginate_cursor(
        self,
        stmt: Select[Any] | None = None,
        *,
        cursor: str | None = None,
        page_size: int | None = None,
        order_desc: bool = True,
    ) -> Page:
        """Keyset pagination on the time-ordered UUIDv7 primary key."""
        size = clamp_page_size(page_size)
        query = stmt if stmt is not None else self.base_query()
        if cursor:
            last_id = UUID(decode_cursor(cursor)["id"])
            query = query.where(self.model.id < last_id if order_desc else self.model.id > last_id)
        order = self.model.id.desc() if order_desc else self.model.id.asc()
        rows: Sequence[Any] = (
            (await self.session.execute(query.order_by(order).limit(size + 1))).scalars().all()
        )
        has_more = len(rows) > size
        items = list(rows[:size])
        return Page(
            items=items,
            next_cursor=encode_cursor({"id": str(items[-1].id)}) if has_more and items else None,
            page_size=size,
        )

    # -- writes ------------------------------------------------------------
    def add(self, entity: M) -> M:
        entity.tenant_id = self.tenant_id  # type: ignore[attr-defined]
        self.session.add(entity)
        return entity

    async def soft_delete_by_id(self, entity_id: UUID) -> None:
        entity = await self.get_or_404(entity_id)
        if hasattr(entity, "deleted_at"):
            entity.deleted_at = utcnow()  # type: ignore[attr-defined]
        else:
            await self.session.delete(entity)

    async def bump_version(self, entity: M, expected_version: int | None) -> None:
        """Optimistic concurrency. A mismatch is a 412, never a silent overwrite."""
        current = getattr(entity, "version", None)
        if current is None:
            return
        if expected_version is not None and expected_version != current:
            raise PreconditionFailed(
                "The resource was modified by someone else.",
                details={"expected_version": expected_version, "current_version": current},
            )
        entity.version = current + 1  # type: ignore[attr-defined]

    async def update_where(self, values: dict[str, Any], *conditions: Any) -> int:
        stmt = (
            update(self.model)
            .where(self.model.tenant_id == self.tenant_id, *conditions)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


def etag_for(entity: Any) -> str:
    """Weak ETag derived from the optimistic version column."""
    return f'W/"{getattr(entity, "version", 0)}"'


def parse_if_match(header: str | None) -> int | None:
    if not header:
        return None
    cleaned = header.strip().removeprefix("W/").strip('"')
    return int(cleaned) if cleaned.isdigit() else None
