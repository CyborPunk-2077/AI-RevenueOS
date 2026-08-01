"""Request-scoped context propagated into every log line, span and audit record."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any

_correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_tenant_id: ContextVar[str | None] = ContextVar("tenant_id", default=None)
_user_id: ContextVar[str | None] = ContextVar("user_id", default=None)
_actor_type: ContextVar[str] = ContextVar("actor_type", default="anonymous")


@dataclass(slots=True)
class ContextTokens:
    correlation: Token[str | None]
    tenant: Token[str | None]
    user: Token[str | None]
    actor: Token[str]


def bind_context(
    *,
    correlation_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
    actor_type: str = "anonymous",
) -> ContextTokens:
    return ContextTokens(
        correlation=_correlation_id.set(correlation_id),
        tenant=_tenant_id.set(tenant_id),
        user=_user_id.set(user_id),
        actor=_actor_type.set(actor_type),
    )


def reset_context(tokens: ContextTokens) -> None:
    _correlation_id.reset(tokens.correlation)
    _tenant_id.reset(tokens.tenant)
    _user_id.reset(tokens.user)
    _actor_type.reset(tokens.actor)


def current_context() -> dict[str, Any]:
    return {
        "correlation_id": _correlation_id.get(),
        "tenant_id": _tenant_id.get(),
        "user_id": _user_id.get(),
        "actor_type": _actor_type.get(),
    }


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def get_tenant_id() -> str | None:
    return _tenant_id.get()


def set_tenant_id(value: str | None) -> Token[str | None]:
    return _tenant_id.set(value)
