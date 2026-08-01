"""AI application service. Confirmation gating and manual fallback are enforced here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from application.ai.registry import get_gateway
from infrastructure.ai.gateway import AIRequest
from infrastructure.ai.models import Task

TASK_MAP: dict[str, Task] = {
    "generate": Task.GENERATE,
    "classify": Task.CLASSIFY,
    "extract": Task.EXTRACT,
    "summarize": Task.SUMMARIZE,
    "search": Task.RAG,
    "analyze": Task.ANALYZE,
    "translate": Task.TRANSLATE,
}


@dataclass(slots=True)
class AiService:
    tenant_id: UUID
    user_id: UUID
    industry_code: str = "other_sme"
    tier: str = "basic"

    @classmethod
    def for_principal(cls, principal: Any) -> AiService:
        return cls(tenant_id=principal.tenant_id, user_id=principal.user_id)

    async def chat(
        self, message: str, *, entity_type: str | None = None, entity_id: UUID | None = None
    ) -> dict[str, Any]:
        response = await get_gateway().complete(
            AIRequest(
                task=Task.CHAT,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                tier=self.tier,
                industry_code=self.industry_code,
                messages=[{"role": "user", "content": message}],
                allowed_tools=list(READONLY_TOOLS),
                metadata={
                    "entity_type": entity_type,
                    "entity_id": str(entity_id) if entity_id else None,
                },
            )
        )
        return {
            "reply": response.text,
            "degraded": response.degraded,
            "manual_path": _manual_path(response.degraded_reason),
            "metadata": response.to_metadata(),
        }

    async def run_task(
        self, task: str, text: str, *, options: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = await get_gateway().complete(
            AIRequest(
                task=TASK_MAP.get(task, Task.GENERATE),
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                tier=self.tier,
                industry_code=self.industry_code,
                messages=[{"role": "user", "content": text}],
                metadata=options or {},
            )
        )
        return {
            "task": task,
            "output": response.text,
            "structured": response.structured,
            "degraded": response.degraded,
            # Generated content is always human reviewed before it is sent or used.
            "requires_review": True,
            "manual_path": _manual_path(response.degraded_reason),
            "metadata": response.to_metadata(),
        }

    async def usage(self) -> dict[str, Any]:
        from sqlalchemy import func, select

        from infrastructure.database.models.ai import AiUsageRecord
        from infrastructure.database.session import tenant_session
        from shared.utils.timeutil import utcnow

        month_start = utcnow().replace(day=1).date()
        async with tenant_session(self.tenant_id) as session:
            row = (
                await session.execute(
                    select(
                        func.coalesce(func.sum(AiUsageRecord.input_tokens), 0),
                        func.coalesce(func.sum(AiUsageRecord.output_tokens), 0),
                        func.coalesce(func.sum(AiUsageRecord.cost_micro_inr), 0),
                        func.count(),
                    ).where(AiUsageRecord.usage_date >= month_start)
                )
            ).one()
        return {
            "period_start": month_start.isoformat(),
            "input_tokens": int(row[0]),
            "output_tokens": int(row[1]),
            "cost_micro_inr": int(row[2]),
            "calls": int(row[3]),
        }


READONLY_TOOLS = (
    "search_leads",
    "get_lead_detail",
    "get_conversation",
    "search_knowledge_base",
    "get_pipeline_stats",
)


def _manual_path(reason: str | None) -> str | None:
    if reason is None:
        return None
    return (
        "Continue manually: the record, its history and every action remain fully "
        "available without AI assistance."
    )
