"""AIGateway - the only path to a model.

Pipeline: authorize/entitle -> task schema -> input guard -> prompt assembly ->
provider router -> tool loop -> output guard -> usage/audit -> human confirmation.
Product modules never call a provider directly.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from opentelemetry.trace import SpanKind

from domain.ai.guards import GuardResult, requires_human_confirmation, scan_input, scan_output
from infrastructure.ai.models import (
    DEGRADED_MESSAGES,
    LATENCY_TARGETS_MS,
    MODELS,
    RoutePolicy,
    Task,
    cost_micro_inr,
    route_for,
)
from infrastructure.integrations.circuit import CircuitOpen, registry
from infrastructure.logging.setup import get_logger
from infrastructure.monitoring.metrics import (
    ai_cost_micro_inr,
    ai_guard_blocks,
    ai_tokens,
    provider_calls,
    provider_latency,
)
from infrastructure.observability.tracing import set_attributes, start_span

logger = get_logger("ai.gateway")

MAX_SEQUENTIAL_TOOL_CALLS = 5
MAX_TOOL_CALLS_PER_SESSION = 20
TOOL_OUTPUT_TRUNCATE = 4_000


@dataclass(slots=True)
class AIRequest:
    task: Task | str
    tenant_id: UUID
    messages: list[dict[str, str]] = field(default_factory=list)
    user_id: UUID | None = None
    tier: str = "basic"
    allowed_tools: list[str] = field(default_factory=list)
    response_schema: dict[str, Any] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    industry_code: str | None = None
    require_citations: bool = False
    untrusted_context: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


@dataclass(slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_tokens: int = 0
    cost_micro_inr: int = 0


@dataclass(slots=True)
class AIResponse:
    ok: bool
    text: str = ""
    structured: dict[str, Any] | None = None
    provider: str = ""
    model: str = ""
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0
    tool_trace: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    degraded_reason: str | None = None
    fallback_from: str | None = None
    guard: dict[str, Any] = field(default_factory=dict)
    requires_confirmation: bool = False
    citations: list[dict[str, Any]] = field(default_factory=list)
    request_id: str = ""

    def to_metadata(self) -> dict[str, Any]:
        """Provider/model/request/cost-safe metadata attached to every AI response."""
        return {
            "provider": self.provider,
            "model": self.model,
            "request_id": self.request_id,
            "latency_ms": self.latency_ms,
            "degraded": self.degraded,
            "degraded_reason": self.degraded_reason,
            "fallback_from": self.fallback_from,
            "usage": {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cache_tokens": self.usage.cache_tokens,
                "cost_micro_inr": self.usage.cost_micro_inr,
            },
            "warnings": self.warnings,
            "requires_confirmation": self.requires_confirmation,
        }


class ProviderClient:
    """Adapter contract. A real client wraps an HTTP SDK; tests supply a fake."""

    name: str = "unset"

    def is_configured(self) -> bool:
        raise NotImplementedError

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_output_tokens: int,
        response_schema: dict[str, Any] | None,
    ) -> tuple[str, Usage]:
        raise NotImplementedError

    async def stream(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_output_tokens: int,
    ) -> AsyncIterator[str]:
        raise NotImplementedError


class BudgetExhausted(RuntimeError):
    """Raised at 100% of the tenant monthly token budget."""


class AIGateway:
    def __init__(
        self,
        clients: dict[str, ProviderClient],
        *,
        usage_recorder: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        budget_checker: Callable[[UUID, int], Awaitable[tuple[bool, int]]] | None = None,
        tool_runner: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self._clients = clients
        self._record_usage = usage_recorder
        self._check_budget = budget_checker
        self._run_tool = tool_runner

    # -- health -----------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            "providers": {
                name: {"configured": client.is_configured()}
                for name, client in self._clients.items()
            },
            "circuits": registry.snapshot(),
        }

    # -- main entry point -------------------------------------------------
    async def complete(self, request: AIRequest) -> AIResponse:
        # Task, provider, model and token counts only. Prompts, completions, tool
        # arguments and retrieved context never become span attributes.
        with start_span(
            "ai complete", kind=SpanKind.CLIENT, attributes={"ai.task": str(request.task)}
        ):
            return await self._complete(request)

    async def _complete(self, request: AIRequest) -> AIResponse:
        started = time.perf_counter()
        policy = route_for(request.task, request.tier)
        request_id = request.correlation_id or f"ai-{int(time.time() * 1000)}"

        guard = self._guard_input(request)
        if guard.blocked:
            ai_guard_blocks.labels(guard="input", reason=(guard.reasons or ["blocked"])[0]).inc()
            return self._degraded(
                policy,
                "input_guard_blocked",
                request_id,
                warnings=guard.reasons,
                guard=guard.to_dict(),
            )

        messages = self._assemble(request, guard)

        if self._check_budget is not None:
            allowed, remaining = await self._check_budget(request.tenant_id, 0)
            if not allowed:
                return self._degraded(
                    policy,
                    "budget_exhausted",
                    request_id,
                    warnings=[f"Monthly AI budget exhausted (remaining {remaining})."],
                )

        attempted: list[str] = []
        for model_name in (policy.primary, *policy.fallbacks):
            spec = MODELS.get(model_name)
            if spec is None:
                continue
            client = self._clients.get(spec.provider.value)
            if client is None or not client.is_configured():
                attempted.append(model_name)
                continue
            breaker = registry.get(spec.provider.value)
            try:
                breaker.require()
            except CircuitOpen:
                attempted.append(model_name)
                continue

            try:
                text, usage = await self._call(
                    client, spec.provider.value, model_name, policy, request, messages
                )
            except Exception as exc:
                breaker.record_failure()
                provider_calls.labels(
                    provider=spec.provider.value, operation=str(request.task), outcome="error"
                ).inc()
                logger.warning(
                    "ai_provider_failed",
                    provider=spec.provider.value,
                    model=model_name,
                    error=type(exc).__name__,
                )
                attempted.append(model_name)
                continue

            breaker.record_success()
            usage.cost_micro_inr = cost_micro_inr(
                model_name, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens
            )
            latency_ms = int((time.perf_counter() - started) * 1000)

            out_guard = scan_output(
                text,
                industry_code=request.industry_code,
                schema=request.response_schema if policy.requires_schema else None,
                require_citations=request.require_citations,
                citations=request.metadata.get("citations"),
            )
            if out_guard.blocked:
                ai_guard_blocks.labels(
                    guard="output", reason=(out_guard.reasons or ["blocked"])[0]
                ).inc()
                await self._persist_usage(
                    request,
                    model_name,
                    spec.provider.value,
                    usage,
                    latency_ms,
                    "guard_blocked",
                    request_id,
                    True,
                )
                return self._degraded(
                    policy,
                    "output_guard_blocked",
                    request_id,
                    warnings=out_guard.reasons,
                    guard=out_guard.to_dict(),
                )

            await self._persist_usage(
                request,
                model_name,
                spec.provider.value,
                usage,
                latency_ms,
                "success",
                request_id,
                False,
            )
            self._publish_metrics(spec.provider.value, model_name, request.task, usage, latency_ms)
            set_attributes(
                {
                    "ai.provider": spec.provider.value,
                    "ai.model": model_name,
                    "ai.tokens_input": getattr(usage, "input_tokens", None),
                    "ai.tokens_output": getattr(usage, "output_tokens", None),
                }
            )

            fallback_from = policy.primary if model_name != policy.primary else None
            warnings = list(out_guard.reasons)
            if fallback_from:
                warnings.append(f"Primary model unavailable; served by {model_name}.")
            if latency_ms > LATENCY_TARGETS_MS.get(Task(request.task), 10_000):
                warnings.append("This response was slower than the target latency.")

            structured = None
            if policy.requires_schema:
                import json

                try:
                    structured = json.loads(out_guard.text)
                except json.JSONDecodeError:
                    structured = None

            return AIResponse(
                ok=True,
                text=out_guard.text,
                structured=structured,
                provider=spec.provider.value,
                model=model_name,
                usage=usage,
                latency_ms=latency_ms,
                warnings=warnings,
                fallback_from=fallback_from,
                guard=out_guard.to_dict(),
                request_id=request_id,
                citations=request.metadata.get("citations", []),
                requires_confirmation=any(
                    requires_human_confirmation(t) for t in request.allowed_tools
                ),
            )

        logger.warning("ai_all_providers_exhausted", task=str(request.task), attempted=attempted)
        return self._degraded(
            policy,
            "all_providers_unavailable",
            request_id,
            warnings=[f"attempted: {', '.join(attempted) or 'none configured'}"],
        )

    # -- internals --------------------------------------------------------
    def _guard_input(self, request: AIRequest) -> GuardResult:
        combined = "\n".join(
            m.get("content", "") for m in request.messages if m.get("role") == "user"
        )
        result = scan_input(combined)
        if result.blocked:
            return result
        for block in request.untrusted_context:
            context_result = scan_input(block, is_untrusted_context=True)
            if context_result.blocked:
                return context_result
        return result

    def _assemble(self, request: AIRequest, guard: GuardResult) -> list[dict[str, str]]:
        """Context order: system/task/schema -> user facts -> history -> RAG -> examples."""
        messages: list[dict[str, str]] = []
        system = request.metadata.get("system_prompt")
        if system:
            messages.append({"role": "system", "content": str(system)})
        for block in request.untrusted_context:
            delimited = scan_input(block, is_untrusted_context=True)
            messages.append({"role": "user", "content": delimited.text})
        for message in request.messages:
            if message.get("role") == "user" and guard.text:
                messages.append({"role": "user", "content": guard.text})
                guard = GuardResult(guard.action, guard.score, guard.reasons, "", guard.detected)
            else:
                messages.append(message)
        return messages

    async def _call(
        self,
        client: ProviderClient,
        provider: str,
        model: str,
        policy: RoutePolicy,
        request: AIRequest,
        messages: list[dict[str, str]],
    ) -> tuple[str, Usage]:
        with provider_latency.labels(provider=provider, operation=str(request.task)).time():
            text, usage = await client.complete(
                model=model,
                messages=messages,
                temperature=request.temperature
                if request.temperature is not None
                else policy.temperature,
                max_output_tokens=request.max_output_tokens or policy.max_output_tokens,
                response_schema=request.response_schema if policy.requires_schema else None,
            )
        provider_calls.labels(
            provider=provider, operation=str(request.task), outcome="success"
        ).inc()
        return text, usage

    def _degraded(
        self,
        policy: RoutePolicy,
        reason: str,
        request_id: str,
        *,
        warnings: list[str] | None = None,
        guard: dict[str, Any] | None = None,
    ) -> AIResponse:
        """Never fabricate a successful AI result; always leave a manual path."""
        return AIResponse(
            ok=False,
            text=DEGRADED_MESSAGES.get(policy.degraded_behaviour, DEGRADED_MESSAGES["manual"]),
            degraded=True,
            degraded_reason=reason,
            warnings=warnings or [],
            guard=guard or {},
            request_id=request_id,
        )

    async def _persist_usage(
        self,
        request: AIRequest,
        model: str,
        provider: str,
        usage: Usage,
        latency_ms: int,
        outcome: str,
        request_id: str,
        degraded: bool,
    ) -> None:
        if self._record_usage is None:
            return
        await self._record_usage(
            {
                "tenant_id": request.tenant_id,
                "user_id": request.user_id,
                "task": str(request.task),
                "provider": provider,
                "model": model,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_tokens": usage.cache_tokens,
                "cost_micro_inr": usage.cost_micro_inr,
                "latency_ms": latency_ms,
                "request_id": request_id,
                "outcome": outcome,
                "degraded": degraded,
            }
        )

    def _publish_metrics(
        self, provider: str, model: str, task: Task | str, usage: Usage, latency_ms: int
    ) -> None:
        ai_tokens.labels(provider=provider, model=model, kind="input").inc(usage.input_tokens)
        ai_tokens.labels(provider=provider, model=model, kind="output").inc(usage.output_tokens)
        ai_cost_micro_inr.labels(provider=provider, model=model).inc(usage.cost_micro_inr)

    # -- tool loop --------------------------------------------------------
    async def run_tool_loop(
        self, request: AIRequest, tool_calls: list[dict[str, Any]], *, session_calls: int = 0
    ) -> list[dict[str, Any]]:
        """At most 5 sequential calls and 20 per session; mutating tools need approval."""
        if len(tool_calls) > MAX_SEQUENTIAL_TOOL_CALLS:
            raise ValueError(
                f"a maximum of {MAX_SEQUENTIAL_TOOL_CALLS} sequential tool calls is permitted"
            )
        if session_calls + len(tool_calls) > MAX_TOOL_CALLS_PER_SESSION:
            raise ValueError(
                f"a maximum of {MAX_TOOL_CALLS_PER_SESSION} tool calls per session is permitted"
            )
        trace: list[dict[str, Any]] = []
        for call in tool_calls:
            name = str(call.get("name"))
            if name not in request.allowed_tools:
                trace.append({"tool": name, "status": "denied", "reason": "tool not allowlisted"})
                continue
            if requires_human_confirmation(name):
                trace.append(
                    {
                        "tool": name,
                        "status": "awaiting_confirmation",
                        "reason": (
                            "this action changes customer state and requires explicit approval"
                        ),
                        "proposed_arguments": call.get("arguments", {}),
                    }
                )
                continue
            if self._run_tool is None:
                trace.append({"tool": name, "status": "unavailable"})
                continue
            result = await self._run_tool(name, call.get("arguments", {}))
            trace.append(
                {
                    "tool": name,
                    "status": "ok",
                    "output": str(result)[:TOOL_OUTPUT_TRUNCATE],
                    "truncated": len(str(result)) > TOOL_OUTPUT_TRUNCATE,
                }
            )
        return trace


# Read-only tools may run without confirmation; mutating tools never do.
READONLY_TOOLS = (
    "search_leads",
    "get_lead_detail",
    "get_conversation",
    "search_knowledge_base",
    "get_pipeline_stats",
)
MUTATING_TOOLS = (
    "create_task",
    "schedule_appointment",
    "send_message",
    "update_lead_stage",
    "generate_document",
)
