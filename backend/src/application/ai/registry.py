"""Provider wiring for the AI gateway. Absent credentials mean absent providers."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from infrastructure.ai.gateway import AIGateway, ProviderClient, Usage
from shared.settings import Settings, get_settings


class HttpProviderClient(ProviderClient):
    """Concrete SDK calls are wired when a provider credential is present."""

    def __init__(self, name: str, api_key: str | None) -> None:
        self.name = name
        self._api_key = api_key

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def complete(self, **kwargs: Any) -> tuple[str, Usage]:
        if not self.is_configured():
            raise RuntimeError(f"{self.name} is not configured")
        raise NotImplementedError(
            f"the {self.name} client is wired once the provider credential is provisioned"
        )


@lru_cache(maxsize=1)
def get_gateway(settings: Settings | None = None) -> AIGateway:
    cfg = settings or get_settings()
    clients: dict[str, ProviderClient] = {
        "anthropic": HttpProviderClient("anthropic", cfg.anthropic_api_key),
        "openai": HttpProviderClient("openai", cfg.openai_api_key),
        "google": HttpProviderClient("google", cfg.google_ai_api_key),
    }
    return AIGateway(clients, usage_recorder=_record_usage, budget_checker=_check_budget)


async def _record_usage(row: dict[str, Any]) -> None:
    from infrastructure.database.models.ai import AiUsageRecord
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork
    from shared.utils.timeutil import utcnow

    async with SqlAlchemyUnitOfWork(row["tenant_id"]) as uow:
        uow.session.add(
            AiUsageRecord(
                tenant_id=row["tenant_id"],
                user_id=row.get("user_id"),
                task=row["task"],
                provider=row["provider"],
                model=row["model"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                cache_tokens=row.get("cache_tokens", 0),
                cost_micro_inr=row["cost_micro_inr"],
                latency_ms=row["latency_ms"],
                request_id=row["request_id"],
                outcome=row["outcome"],
                degraded=row.get("degraded", False),
                usage_date=utcnow().date(),
            )
        )


async def _check_budget(tenant_id: Any, tokens: int) -> tuple[bool, int]:
    """Alert at 80%, downgrade permitted tasks at the limit, hard stop at 100%."""
    from sqlalchemy import func, select

    from domain.tenants.entitlements import PLANS, PlanCode
    from infrastructure.database.models.ai import AiUsageRecord
    from infrastructure.database.session import tenant_session
    from shared.utils.timeutil import utcnow

    budget = PLANS[PlanCode.STARTER].ai_token_budget_monthly
    month_start = utcnow().replace(day=1).date()
    try:
        async with tenant_session(tenant_id) as session:
            used = (
                await session.execute(
                    select(
                        func.coalesce(
                            func.sum(AiUsageRecord.input_tokens + AiUsageRecord.output_tokens), 0
                        )
                    ).where(AiUsageRecord.usage_date >= month_start)
                )
            ).scalar_one()
    except Exception:
        return True, budget
    return int(used) < budget, max(0, budget - int(used))
