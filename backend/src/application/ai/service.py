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
        from application.ai.prompt_registry import resolve_production_prompt
        from domain.ai.guards import scan_input

        if scan_input(message).blocked:
            return _degraded_without_provider("reply", "input_guard_blocked")

        prompt = await resolve_production_prompt(self.tenant_id, Task.CHAT)
        if prompt is None:
            return _degraded_without_provider("reply", "prompt_not_promoted")
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
                    **prompt,
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
        from application.ai.prompt_registry import resolve_production_prompt
        from domain.ai.guards import scan_input

        resolved_task = TASK_MAP.get(task, Task.GENERATE)
        if scan_input(text).blocked:
            return {
                "task": task,
                **_degraded_without_provider("output", "input_guard_blocked"),
                "structured": None,
            }
        prompt = await resolve_production_prompt(self.tenant_id, resolved_task)
        if prompt is None:
            return {
                "task": task,
                **_degraded_without_provider("output", "prompt_not_promoted"),
                "structured": None,
            }
        response = await get_gateway().complete(
            AIRequest(
                task=resolved_task,
                tenant_id=self.tenant_id,
                user_id=self.user_id,
                tier=self.tier,
                industry_code=self.industry_code,
                messages=[{"role": "user", "content": text}],
                response_schema=prompt["response_schema"] or None,
                metadata={**(options or {}), **prompt},
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


def _degraded_without_provider(output_field: str, reason: str) -> dict[str, Any]:
    message = {
        "input_guard_blocked": "The request was blocked by the AI input safety policy.",
        "prompt_not_promoted": "AI is unavailable until an evaluated prompt version is promoted.",
    }[reason]
    return {
        output_field: message,
        "degraded": True,
        "requires_review": True,
        "manual_path": _manual_path(reason),
        "metadata": {
            "provider": "",
            "model": "",
            "degraded": True,
            "degraded_reason": reason,
            "prompt_status": "not_promoted" if reason == "prompt_not_promoted" else "blocked",
            "provider_called": False,
        },
    }
