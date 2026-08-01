"""SQLAlchemy unit of work: state change and outbox row share one transaction."""

from __future__ import annotations

from types import TracebackType
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from domain.base import DomainEvent
from infrastructure.database.models.audit import EventOutbox
from infrastructure.database.session import bind_tenant, get_sessionmaker
from infrastructure.logging.context import get_correlation_id
from infrastructure.logging.setup import get_logger
from shared.exceptions import TenantContextMissing

logger = get_logger("infra.uow")


class SqlAlchemyUnitOfWork:
    """Usage:

    >>> async with SqlAlchemyUnitOfWork(tenant_id) as uow:
    ...     repo = ContactRepository(uow.session, tenant_id)
    ...     contact = await repo.add(...)
    ...     uow.collect(*contact.pull_events())
    """

    def __init__(
        self,
        tenant_id: UUID | None,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        require_tenant: bool = True,
    ) -> None:
        if require_tenant and tenant_id is None:
            raise TenantContextMissing()
        self.tenant_id = tenant_id
        self._factory = session_factory or get_sessionmaker()
        self._session: AsyncSession | None = None
        self._events: list[DomainEvent] = []
        self._committed = False

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        return self._session

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._factory()
        await self._session.begin()
        if self.tenant_id is not None:
            await bind_tenant(self._session, self.tenant_id)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
            elif not self._committed:
                await self.commit()
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None

    def collect(self, *events: DomainEvent) -> None:
        """Queue domain events for outbox insertion at commit time."""
        self._events.extend(events)

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("unit of work is not active")
        if self._events:
            self._write_outbox()
        await self._session.commit()
        self._committed = True
        if self._events:
            logger.info("outbox_committed", event_count=len(self._events))
            self._events.clear()

    async def rollback(self) -> None:
        if self._session is not None:
            await self._session.rollback()
        self._events.clear()

    async def flush(self) -> None:
        await self.session.flush()

    def _write_outbox(self) -> None:
        correlation = get_correlation_id()
        for event in self._events:
            self.session.add(
                EventOutbox(
                    occurred_at=event.occurred_at,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    tenant_id=event.tenant_id,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    payload=event.to_outbox_payload(),
                    correlation_id=event.correlation_id or correlation,
                    attempts=0,
                )
            )


class PlatformUnitOfWork(SqlAlchemyUnitOfWork):
    """Reference-schema and platform work only. Never used for tenant business data."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(None, require_tenant=False, **kwargs)
