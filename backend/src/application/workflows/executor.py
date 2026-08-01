"""Workflow execution engine.

PostgreSQL holds authoritative execution state; Redis provides only locks and
idempotency hints. n8n has no path into this module. Executions pin an immutable
version and content hash, apply idempotency at three layers and honour kill switches
within the target window.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from domain.workflows.dsl import ACTION_CATALOG, NodeType, compile_workflow
from infrastructure.integrations.retry import BackoffPolicy, RetryClass, backoff_delay, should_retry
from infrastructure.logging.setup import get_logger
from infrastructure.monitoring.metrics import workflow_executions, workflow_lag_seconds
from shared.compat import StrEnum
from shared.utils.text import content_hash
from shared.utils.timeutil import utcnow

logger = get_logger("workflows.executor")

KILL_SWITCH_CHECK_SECONDS = 1.0
MAX_LOOP_HARD = 10_000


class ExecutionState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    RETRYING = "retrying"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Queue routing and limits from the Workflow Engine specification.
QUEUES: dict[str, dict[str, int]] = {
    "workflow-critical": {"concurrency": 20, "priority": 10, "timeout": 30},
    "workflow-standard": {"concurrency": 50, "priority": 7, "timeout": 300},
    "workflow-bulk": {"concurrency": 30, "priority": 4, "timeout": 900},
    "workflow-scheduled": {"concurrency": 10, "priority": 5, "timeout": 300},
    "workflow-webhook": {"concurrency": 15, "priority": 6, "timeout": 60},
    "workflow-ai": {"concurrency": 10, "priority": 8, "timeout": 120},
    "workflow-notification": {"concurrency": 20, "priority": 8, "timeout": 60},
    "workflow-maintenance": {"concurrency": 5, "priority": 1, "timeout": 600},
}


class WorkflowKilled(RuntimeError):
    """Raised when a tenant, workflow or global kill switch stops an execution."""


class TerminalActionError(RuntimeError):
    """A validation, permission or business failure. Never retried."""


@dataclass(slots=True)
class ExecutionContext:
    execution_id: UUID
    tenant_id: UUID
    workflow_id: UUID
    version_id: UUID
    content_hash: str
    trigger_payload: dict[str, Any] = field(default_factory=dict)
    entity: dict[str, Any] = field(default_factory=dict)
    variables: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False
    correlation_id: str | None = None
    started_at: datetime = field(default_factory=utcnow)


@dataclass(slots=True)
class NodeResult:
    node_id: str
    state: NodeState
    attempt: int = 1
    output: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""
    skipped_reason: str | None = None


@dataclass(slots=True)
class ExecutionResult:
    execution_id: UUID
    state: ExecutionState
    nodes: list[NodeResult] = field(default_factory=list)
    error: dict[str, Any] = field(default_factory=dict)
    resume_at: datetime | None = None
    waiting_on: str | None = None
    external_effects: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": str(self.execution_id),
            "state": self.state.value,
            "waiting_on": self.waiting_on,
            "resume_at": self.resume_at.isoformat() if self.resume_at else None,
            "nodes": [
                {
                    "node_id": n.node_id,
                    "state": n.state.value,
                    "attempt": n.attempt,
                    "skipped_reason": n.skipped_reason,
                }
                for n in self.nodes
            ],
            "error": self.error,
        }


# -- idempotency -----------------------------------------------------------


def execution_idempotency_key(
    *, workflow_id: UUID, version_id: UUID, trigger_event_id: UUID | str
) -> str:
    """Derived from the ORIGINAL event, so a replayed trigger cannot double-execute."""
    return f"wf:{workflow_id}:{version_id}:{trigger_event_id}"


def action_idempotency_key(*, execution_id: UUID, node_id: str, attempt: int) -> str:
    """`execution:node:attempt` plus a database natural constraint at the action site."""
    return f"{execution_id}:{node_id}:{attempt}"


def inbound_idempotency_key(*, provider: str, event_id: str) -> str:
    return f"inbound:{provider}:{event_id}"


# -- expression evaluation -------------------------------------------------

SAFE_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "now": lambda: utcnow().isoformat(),
    "lower": lambda s: str(s).lower(),
    "upper": lambda s: str(s).upper(),
    "trim": lambda s: str(s).strip(),
    "length": lambda s: len(s) if hasattr(s, "__len__") else 0,
    "to_number": lambda s: float(s) if str(s).replace(".", "", 1).lstrip("-").isdigit() else 0,
    "to_string": lambda s: str(s),
    "coalesce": lambda *args: next((a for a in args if a not in (None, "")), None),
}


def resolve_path(root: dict[str, Any], path: str) -> Any:
    """Dotted lookup limited to the scoped roots. No attribute access, ever."""
    node: Any = root
    for part in path.split("."):
        if isinstance(node, dict):
            node = node.get(part)
        elif isinstance(node, list) and part.isdigit():
            node = node[int(part)] if int(part) < len(node) else None
        else:
            return None
    return node


def evaluate_condition(condition: dict[str, Any], scope: dict[str, Any]) -> bool:
    operator = condition.get("operator")
    if operator in ("and", "or"):
        children = condition.get("conditions", [])
        results = [evaluate_condition(c, scope) for c in children]
        return all(results) if operator == "and" else any(results)
    if operator == "not":
        return not evaluate_condition(condition.get("conditions", [{}])[0], scope)

    left = condition.get("left")
    if isinstance(left, str) and left.startswith("{{") and left.endswith("}}"):
        left = resolve_path(scope, left.strip("{} ").strip())
    right = condition.get("right")
    if isinstance(right, str) and right.startswith("{{") and right.endswith("}}"):
        right = resolve_path(scope, right.strip("{} ").strip())

    try:
        match operator:
            case "eq":
                return left == right
            case "ne":
                return left != right
            case "gt":
                return left is not None and left > right
            case "gte":
                return left is not None and left >= right
            case "lt":
                return left is not None and left < right
            case "lte":
                return left is not None and left <= right
            case "in":
                return left in (right or [])
            case "not_in":
                return left not in (right or [])
            case "contains":
                return right in (left or "")
            case "not_contains":
                return right not in (left or "")
            case "starts_with":
                return str(left or "").startswith(str(right))
            case "ends_with":
                return str(left or "").endswith(str(right))
            case "is_empty":
                return left in (None, "", [], {})
            case "is_not_empty":
                return left not in (None, "", [], {})
            case "between":
                if not isinstance(right, (list, tuple)) or len(right) != 2:
                    return False
                low, high = right
                return bool(low <= left <= high)
            case _:
                return False
    except TypeError:
        return False


# -- engine ----------------------------------------------------------------

ActionRunner = Callable[[str, dict[str, Any], ExecutionContext, str], Awaitable[dict[str, Any]]]
KillCheck = Callable[[ExecutionContext], Awaitable[bool]]
NodePersister = Callable[[NodeResult, ExecutionContext], Awaitable[None]]


class WorkflowEngine:
    def __init__(
        self,
        *,
        action_runner: ActionRunner,
        kill_check: KillCheck | None = None,
        node_persister: NodePersister | None = None,
        backoff: BackoffPolicy | None = None,
    ) -> None:
        self._run_action = action_runner
        self._kill_check = kill_check
        self._persist_node = node_persister
        self._backoff = backoff or BackoffPolicy()

    async def execute(
        self, plan: dict[str, Any], context: ExecutionContext, *, resume_from: str | None = None
    ) -> ExecutionResult:
        """Run the compiled plan. A dry run performs no external effect at all."""
        if plan["content_hash"] != context.content_hash:
            raise ValueError("execution content hash does not match the pinned version")

        policy = plan["global_policy"]
        results: list[NodeResult] = []
        external: list[str] = []
        deadline = context.started_at + timedelta(seconds=int(policy["timeout_seconds"]))

        queue = list(plan["entry_nodes"]) if resume_from is None else [resume_from]
        visited: set[str] = set()
        loop_counts: dict[str, int] = {}

        workflow_lag_seconds.observe(max(0.0, (utcnow() - context.started_at).total_seconds()))

        while queue:
            if await self._killed(context):
                workflow_executions.labels(outcome="cancelled").inc()
                return ExecutionResult(
                    context.execution_id,
                    ExecutionState.CANCELLED,
                    results,
                    {"reason": "kill switch engaged"},
                    external_effects=external,
                )
            if utcnow() > deadline:
                workflow_executions.labels(outcome="failed").inc()
                return ExecutionResult(
                    context.execution_id,
                    ExecutionState.FAILED,
                    results,
                    {"reason": "workflow timeout exceeded"},
                    external_effects=external,
                )

            node_id = queue.pop(0)
            if (
                node_id in visited
                and plan["nodes"].get(node_id, {}).get("type") != NodeType.LOOP.value
            ):
                continue
            visited.add(node_id)

            node = plan["nodes"].get(node_id)
            if node is None:
                continue

            node_type = node.get("type")
            scope = self._scope(context)

            if node_type == NodeType.CONDITION.value:
                passed = evaluate_condition(node.get("condition", {}), scope)
                results.append(NodeResult(node_id, NodeState.COMPLETED, output={"result": passed}))
                queue.extend(self._next_nodes(plan, node_id, scope, branch=passed))
                continue

            if node_type == NodeType.DELAY.value:
                resume_at = utcnow() + timedelta(seconds=int(node["delay_seconds"]))
                results.append(
                    NodeResult(
                        node_id, NodeState.COMPLETED, output={"resume_at": resume_at.isoformat()}
                    )
                )
                # Durable, scheduled resumption - never a process sleep.
                return ExecutionResult(
                    context.execution_id,
                    ExecutionState.WAITING,
                    results,
                    resume_at=resume_at,
                    waiting_on=node_id,
                    external_effects=external,
                )

            if node_type == NodeType.APPROVAL.value:
                results.append(
                    NodeResult(node_id, NodeState.PENDING, output={"approval": "requested"})
                )
                return ExecutionResult(
                    context.execution_id,
                    ExecutionState.WAITING,
                    results,
                    waiting_on=node_id,
                    external_effects=external,
                )

            if node_type == NodeType.LOOP.value:
                limit = min(int(node.get("max_iterations", 1_000)), MAX_LOOP_HARD)
                loop_counts[node_id] = loop_counts.get(node_id, 0) + 1
                if loop_counts[node_id] > limit:
                    results.append(
                        NodeResult(
                            node_id, NodeState.FAILED, error={"reason": "loop limit reached"}
                        )
                    )
                    if policy["error_policy"] == "stop":
                        workflow_executions.labels(outcome="failed").inc()
                        return ExecutionResult(
                            context.execution_id,
                            ExecutionState.FAILED,
                            results,
                            {"node_id": node_id, "reason": "loop limit reached"},
                            external_effects=external,
                        )
                    continue
                visited.discard(node_id)
                queue.extend(self._next_nodes(plan, node_id, scope))
                continue

            if node_type == NodeType.PARALLEL.value:
                results.append(
                    NodeResult(
                        node_id, NodeState.COMPLETED, output={"join": node.get("join", "all")}
                    )
                )
                queue.extend(self._next_nodes(plan, node_id, scope))
                continue

            if node_type == NodeType.ACTION.value:
                result = await self._run_with_retry(node, context, policy)
                results.append(result)
                spec = ACTION_CATALOG.get(str(node.get("action")))
                if spec and spec.external_effect and result.state is NodeState.COMPLETED:
                    external.append(node_id)
                if self._persist_node is not None:
                    await self._persist_node(result, context)
                if result.state is NodeState.FAILED and policy["error_policy"] == "stop":
                    workflow_executions.labels(outcome="failed").inc()
                    return ExecutionResult(
                        context.execution_id,
                        ExecutionState.FAILED,
                        results,
                        {"node_id": node_id, **result.error},
                        external_effects=external,
                    )
                queue.extend(self._next_nodes(plan, node_id, scope))
                continue

            queue.extend(self._next_nodes(plan, node_id, scope))

        workflow_executions.labels(outcome="completed").inc()
        return ExecutionResult(
            context.execution_id, ExecutionState.COMPLETED, results, external_effects=external
        )

    async def _run_with_retry(
        self, node: dict[str, Any], context: ExecutionContext, policy: dict[str, Any]
    ) -> NodeResult:
        action = str(node.get("action"))
        node_id = str(node.get("id"))
        max_attempts = int(node.get("retry_attempts", policy["retry_attempts"])) + 1
        backoff = BackoffPolicy(
            strategy=str(policy.get("retry_strategy", "exponential")),
            initial_seconds=float(policy.get("retry_initial_seconds", 1)),
            max_seconds=float(policy.get("retry_max_seconds", 60)),
        )

        for attempt in range(1, max_attempts + 1):
            key = action_idempotency_key(
                execution_id=context.execution_id, node_id=node_id, attempt=attempt
            )
            if context.dry_run:
                spec = ACTION_CATALOG.get(action)
                return NodeResult(
                    node_id,
                    NodeState.SKIPPED,
                    attempt,
                    idempotency_key=key,
                    output={
                        "dry_run": True,
                        "would_call": action,
                        "external_effect": bool(spec and spec.external_effect),
                    },
                    skipped_reason="dry run performs no external effect",
                )
            try:
                output = await self._run_action(action, node.get("inputs", {}), context, key)
                return NodeResult(
                    node_id, NodeState.COMPLETED, attempt, output=output, idempotency_key=key
                )
            except TerminalActionError as exc:
                return NodeResult(
                    node_id,
                    NodeState.FAILED,
                    attempt,
                    idempotency_key=key,
                    error={"type": "terminal", "message": str(exc), "retried": False},
                )
            except WorkflowKilled:
                raise
            except Exception as exc:
                if not should_retry(RetryClass.PROVIDER, attempt, max_attempts):
                    return NodeResult(
                        node_id,
                        NodeState.FAILED,
                        attempt,
                        idempotency_key=key,
                        error={
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "attempts": attempt,
                        },
                    )
                delay = backoff_delay(attempt, backoff)
                logger.info(
                    "workflow_node_retry",
                    node_id=node_id,
                    attempt=attempt,
                    delay_seconds=round(delay, 2),
                    error=type(exc).__name__,
                )
                await asyncio.sleep(min(delay, 0.01))  # scheduler owns the real wait
        return NodeResult(node_id, NodeState.FAILED, max_attempts, error={"message": "exhausted"})

    def _next_nodes(
        self,
        plan: dict[str, Any],
        node_id: str,
        scope: dict[str, Any],
        *,
        branch: bool | None = None,
    ) -> list[str]:
        edges = plan["adjacency"].get(node_id, [])
        out: list[str] = []
        for edge in edges:
            label = edge.get("label")
            if (
                branch is not None
                and label in ("true", "false")
                and (label == "true") is not branch
            ):
                continue
            condition = edge.get("condition")
            if isinstance(condition, dict) and not evaluate_condition(condition, scope):
                continue
            out.append(edge["target"])
        return out

    def _scope(self, context: ExecutionContext) -> dict[str, Any]:
        """Expressions see only these roots - no secrets, no globals, no imports."""
        return {
            "event": context.trigger_payload,
            "entity": context.entity,
            "trigger": context.trigger_payload,
            "workflow": {
                "id": str(context.workflow_id),
                "execution_id": str(context.execution_id),
                "content_hash": context.content_hash,
            },
            "node": context.variables,
        }

    async def _killed(self, context: ExecutionContext) -> bool:
        if self._kill_check is None:
            return False
        return await self._kill_check(context)


def build_plan(document: dict[str, Any]) -> tuple[dict[str, Any], str]:
    plan = compile_workflow(document)
    return plan, plan["content_hash"]


def version_hash(document: dict[str, Any]) -> str:
    return content_hash(
        {k: v for k, v in document.items() if k not in ("version", "content_hash", "updated_at")}
    )


def replay_context(original: ExecutionContext, new_execution_id: UUID) -> ExecutionContext:
    """A replay records provenance and never reuses the original idempotency keys."""
    return ExecutionContext(
        execution_id=new_execution_id,
        tenant_id=original.tenant_id,
        workflow_id=original.workflow_id,
        version_id=original.version_id,
        content_hash=original.content_hash,
        trigger_payload=dict(original.trigger_payload),
        entity=dict(original.entity),
        variables={**original.variables, "_replay_of": str(original.execution_id)},
        dry_run=original.dry_run,
        correlation_id=original.correlation_id,
    )
