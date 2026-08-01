"""Explicit ports. These are extraction seams, not authorisation to split services."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from domain.base import DomainEvent


class UnitOfWork(Protocol):
    """Commits state change and outbox rows in a single database transaction."""

    async def __aenter__(self) -> UnitOfWork: ...
    async def __aexit__(self, *exc: Any) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
    def collect(self, *events: DomainEvent) -> None: ...


class EventBus(Protocol):
    async def publish(self, events: Sequence[DomainEvent]) -> None: ...


class CachePort(Protocol):
    async def get_json(self, key: str) -> Any | None: ...
    async def set_json(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, *keys: str) -> None: ...


@dataclass(frozen=True, slots=True)
class PresignedUpload:
    url: str
    fields: dict[str, str]
    object_key: str
    expires_at: datetime
    max_bytes: int


class StoragePort(ABC):
    @abstractmethod
    async def presign_upload(
        self, *, tenant_id: UUID, key: str, content_type: str, max_bytes: int
    ) -> PresignedUpload: ...

    @abstractmethod
    async def presign_download(self, *, bucket: str, key: str, ttl_seconds: int) -> str: ...

    @abstractmethod
    async def head(self, *, bucket: str, key: str) -> dict[str, Any]: ...

    @abstractmethod
    async def delete(self, *, bucket: str, key: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ProviderResult:
    """Uniform provider outcome. `queued` means the effect is durable but not yet done."""

    ok: bool
    provider: str
    operation: str
    external_id: str | None = None
    queued: bool = False
    degraded: bool = False
    error_code: str | None = None
    error_message: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    tenant_id: UUID
    to: str
    channel: str
    body: str | None = None
    template_name: str | None = None
    template_variables: dict[str, Any] = field(default_factory=dict)
    media: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None
    correlation_id: str | None = None


class MessagingPort(ABC):
    """Implemented by the WhatsApp, email, SMS and webchat adapters."""

    channel: str = "unknown"

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def send(self, message: OutboundMessage) -> ProviderResult: ...

    @abstractmethod
    async def health(self) -> ProviderResult: ...

    @abstractmethod
    def verify_webhook(self, *, body: bytes, headers: dict[str, str]) -> bool: ...

    @abstractmethod
    def parse_webhook(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...


class PaymentPort(ABC):
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def create_order(
        self,
        *,
        tenant_id: UUID,
        amount_minor: int,
        currency: str,
        receipt: str,
        notes: dict[str, Any],
        idempotency_key: str,
    ) -> ProviderResult: ...

    @abstractmethod
    async def fetch_payment(self, external_payment_id: str) -> ProviderResult: ...

    @abstractmethod
    async def refund(
        self, *, external_payment_id: str, amount_minor: int, idempotency_key: str
    ) -> ProviderResult: ...

    @abstractmethod
    def verify_webhook_signature(self, *, body: bytes, signature: str) -> bool: ...


class CalendarPort(ABC):
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def create_event(self, *, tenant_id: UUID, payload: dict[str, Any]) -> ProviderResult: ...

    @abstractmethod
    async def cancel_event(self, *, tenant_id: UUID, event_id: str) -> ProviderResult: ...


class VoicePort(ABC):
    """Present for completeness; disabled until legal and consent gates pass."""

    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    async def place_call(self, *, tenant_id: UUID, payload: dict[str, Any]) -> ProviderResult: ...


class ScannerPort(ABC):
    @abstractmethod
    async def scan(self, *, bucket: str, key: str) -> ProviderResult: ...
