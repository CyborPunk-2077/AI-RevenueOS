"""The restricted workflow JSON DSL.

n8n may author this document; it may never execute it. Every construct here is
declarative - there is no arbitrary code, filesystem, shell or network escape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.compat import StrEnum
from shared.utils.text import content_hash

MAX_NAME = 200
MAX_DESCRIPTION = 2_000
MAX_NODES = 200
MAX_LOOP_DEFAULT = 1_000
MAX_LOOP_HARD = 10_000
MAX_SEQUENTIAL_TOOL_CALLS = 5


class NodeType(StrEnum):
    CONDITION = "condition"
    ACTION = "action"
    DELAY = "delay"
    APPROVAL = "approval"
    SUBWORKFLOW = "subworkflow"
    PARALLEL = "parallel"
    LOOP = "loop"


class Category(StrEnum):
    LEAD_NURTURE = "lead_nurture"
    DEAL_AUTOMATION = "deal_automation"
    NOTIFICATION = "notification"
    APPROVAL = "approval"
    CUSTOM = "custom"


class ErrorPolicy(StrEnum):
    STOP = "stop"
    CONTINUE = "continue"
    CUSTOM = "custom"


TRIGGER_TYPES = frozenset(
    {
        "entity.created",
        "entity.updated",
        "entity.field_changed",
        "deal.stage_changed",
        "schedule.at",
        "schedule.cron",
        "schedule.relative",
        "form.submitted",
        "message.inbound",
        "payment.event",
        "appointment.event",
        "document.event",
        "approval.event",
        "threshold.aggregate",
        "webhook.custom",
        "manual",
    }
)


# Every action declares permission, feature gate, retry class, idempotency and audit.
@dataclass(frozen=True, slots=True)
class ActionSpec:
    key: str
    permission: str
    feature_flag: str | None = None
    retry_class: str = "transient"  # transient | none | provider
    timeout_seconds: int = 60
    external_effect: bool = False
    irreversible: bool = False
    requires_approval: bool = False
    queue: str = "workflow-standard"


ACTION_CATALOG: dict[str, ActionSpec] = {
    "lead.create": ActionSpec("lead.create", "lead:create"),
    "lead.update": ActionSpec("lead.update", "lead:update"),
    "lead.assign": ActionSpec("lead.assign", "lead:assign"),
    "contact.create": ActionSpec("contact.create", "contact:create"),
    "contact.update": ActionSpec("contact.update", "contact:update"),
    "deal.create": ActionSpec("deal.create", "deal:create"),
    "deal.update": ActionSpec("deal.update", "deal:update"),
    "deal.move_stage": ActionSpec("deal.move_stage", "deal:update"),
    "task.create": ActionSpec("task.create", "task:create"),
    "tag.add": ActionSpec("tag.add", "tag:update"),
    "tag.remove": ActionSpec("tag.remove", "tag:update"),
    "note.create": ActionSpec("note.create", "note:create"),
    "activity.create": ActionSpec("activity.create", "activity:create"),
    "message.send_whatsapp": ActionSpec(
        "message.send_whatsapp",
        "message:send",
        "whatsapp_enabled",
        retry_class="provider",
        external_effect=True,
        queue="workflow-critical",
    ),
    "message.send_email": ActionSpec(
        "message.send_email",
        "message:send",
        "email_enabled",
        retry_class="provider",
        external_effect=True,
    ),
    "message.send_sms": ActionSpec(
        "message.send_sms",
        "message:send",
        "sms_enabled",
        retry_class="provider",
        external_effect=True,
    ),
    "notification.in_app": ActionSpec(
        "notification.in_app", "notification:create", queue="workflow-notification"
    ),
    "appointment.create": ActionSpec("appointment.create", "appointment:create"),
    "appointment.cancel": ActionSpec(
        "appointment.cancel", "appointment:update", irreversible=True, requires_approval=True
    ),
    "document.generate": ActionSpec("document.generate", "document:create"),
    "document.send": ActionSpec(
        "document.send",
        "document:send",
        "signatures_enabled",
        external_effect=True,
        requires_approval=True,
    ),
    "payment.create_link": ActionSpec(
        "payment.create_link",
        "payment_link:create",
        "payments_enabled",
        external_effect=True,
        requires_approval=True,
    ),
    "payment.refund": ActionSpec(
        "payment.refund",
        "payment:refund",
        "payments_enabled",
        external_effect=True,
        irreversible=True,
        requires_approval=True,
    ),
    "webhook.call": ActionSpec(
        "webhook.call",
        "webhook:execute",
        retry_class="provider",
        external_effect=True,
        queue="workflow-webhook",
    ),
    "ai.task": ActionSpec(
        "ai.task",
        "ai:execute",
        "ai_enabled",
        retry_class="provider",
        timeout_seconds=120,
        queue="workflow-ai",
    ),
    "analytics.emit": ActionSpec("analytics.emit", "analytics:read"),
}

# Expressions may reference only these roots and call only these pure functions.
ALLOWED_EXPRESSION_ROOTS = frozenset({"event", "entity", "workflow", "node", "trigger", "now"})
ALLOWED_FUNCTIONS = frozenset(
    {
        "now",
        "uuid",
        "lower",
        "upper",
        "trim",
        "concat",
        "length",
        "contains",
        "startswith",
        "endswith",
        "replace",
        "split",
        "join",
        "json_get",
        "json_set",
        "base64_encode",
        "base64_decode",
        "to_number",
        "to_string",
        "coalesce",
        "date_add",
        "date_diff",
        "format_date",
    }
)
FORBIDDEN_EXPRESSION_TOKENS = (
    "__",
    "import",
    "eval",
    "exec",
    "open(",
    "os.",
    "sys.",
    "subprocess",
    "lambda",
    "globals",
    "locals",
    "getattr",
    "setattr",
    "compile",
    "input(",
    "require(",
    "process.",
    "child_process",
    "fetch(",
    "XMLHttpRequest",
)

COMPARISON_OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "gt",
        "gte",
        "lt",
        "lte",
        "in",
        "not_in",
        "contains",
        "not_contains",
        "starts_with",
        "ends_with",
        "is_empty",
        "is_not_empty",
        "matches",
        "between",
    }
)
LOGICAL_OPERATORS = frozenset({"and", "or", "not"})


# Depth-first search colours for cycle detection.
_WHITE, _GREY, _BLACK = 0, 1, 2


class DslValidationError(ValueError):
    """Raised with the full list of problems so the builder can show them at once."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("; ".join(problems[:10]))


@dataclass(slots=True)
class ValidationReport:
    valid: bool
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    node_count: int = 0
    external_effect_nodes: list[str] = field(default_factory=list)
    approval_required_nodes: list[str] = field(default_factory=list)
    content_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "problems": self.problems,
            "warnings": self.warnings,
            "node_count": self.node_count,
            "external_effect_nodes": self.external_effect_nodes,
            "approval_required_nodes": self.approval_required_nodes,
            "content_hash": self.content_hash,
        }


def validate_expression(expr: str, path: str, problems: list[str]) -> None:
    lowered = expr.lower()
    for token in FORBIDDEN_EXPRESSION_TOKENS:
        if token in lowered:
            problems.append(f"{path}: expression contains forbidden token '{token}'")
            return
    if len(expr) > 2_000:
        problems.append(f"{path}: expression exceeds 2000 characters")
    for segment in expr.replace("}}", "{{").split("{{"):
        candidate = segment.strip()
        if not candidate or ("." not in candidate and "(" not in candidate):
            continue
        root = candidate.split(".")[0].split("(")[0].strip()
        if root and root not in ALLOWED_EXPRESSION_ROOTS and root not in ALLOWED_FUNCTIONS:
            problems.append(f"{path}: expression references unavailable root '{root}'")


def _validate_condition(node: dict[str, Any], path: str, problems: list[str]) -> None:
    cond = node.get("condition")
    if not isinstance(cond, dict):
        problems.append(f"{path}: condition node requires a 'condition' object")
        return
    op = cond.get("operator")
    if op in LOGICAL_OPERATORS:
        children = cond.get("conditions") or []
        if not isinstance(children, list) or not children:
            problems.append(f"{path}: logical condition requires child conditions")
        return
    if op not in COMPARISON_OPERATORS:
        problems.append(f"{path}: unsupported condition operator '{op}'")
    if "left" not in cond:
        problems.append(f"{path}: condition requires a 'left' operand")
    if isinstance(cond.get("left"), str):
        validate_expression(str(cond["left"]), f"{path}.left", problems)


def validate_workflow(doc: dict[str, Any]) -> ValidationReport:
    """Full structural, semantic and safety validation of a workflow document."""
    problems: list[str] = []
    warnings: list[str] = []
    external: list[str] = []
    approvals: list[str] = []

    name = doc.get("name", "")
    if not isinstance(name, str) or not 1 <= len(name) <= MAX_NAME:
        problems.append(f"name must be 1-{MAX_NAME} characters")
    if len(str(doc.get("description", ""))) > MAX_DESCRIPTION:
        problems.append(f"description must be at most {MAX_DESCRIPTION} characters")
    try:
        Category(doc.get("category", "custom"))
    except ValueError:
        problems.append(f"unknown category '{doc.get('category')}'")

    trigger = doc.get("trigger") or {}
    if trigger.get("type") not in TRIGGER_TYPES:
        problems.append(f"unknown trigger type '{trigger.get('type')}'")

    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []
    if not isinstance(nodes, list) or not nodes:
        problems.append("a workflow must declare at least one node")
        nodes = []
    if len(nodes) > MAX_NODES:
        problems.append(f"a workflow may not exceed {MAX_NODES} nodes")

    node_ids: set[str] = set()
    for index, node in enumerate(nodes):
        path = f"nodes[{index}]"
        node_id = node.get("id")
        if not node_id or not isinstance(node_id, str):
            problems.append(f"{path}: node requires a string id")
            continue
        if node_id in node_ids:
            problems.append(f"{path}: duplicate node id '{node_id}'")
        node_ids.add(node_id)

        try:
            node_type = NodeType(node.get("type"))
        except ValueError:
            problems.append(f"{path}: unknown node type '{node.get('type')}'")
            continue

        if node_type is NodeType.ACTION:
            action = node.get("action")
            spec = ACTION_CATALOG.get(str(action))
            if spec is None:
                problems.append(f"{path}: unknown action '{action}'")
            else:
                if spec.external_effect:
                    external.append(node_id)
                if spec.requires_approval and not _has_upstream_approval(node_id, nodes, edges):
                    approvals.append(node_id)
                    problems.append(
                        f"{path}: action '{action}' is irreversible or externally visible and "
                        "requires an upstream approval node or explicit confirmation policy"
                    )
        elif node_type is NodeType.CONDITION:
            _validate_condition(node, path, problems)
        elif node_type is NodeType.DELAY:
            seconds = node.get("delay_seconds")
            if not isinstance(seconds, int) or not 1 <= seconds <= 31_536_000:
                problems.append(f"{path}: delay_seconds must be between 1 and 31536000")
        elif node_type is NodeType.LOOP:
            limit = node.get("max_iterations", MAX_LOOP_DEFAULT)
            if not isinstance(limit, int) or not 1 <= limit <= MAX_LOOP_HARD:
                problems.append(f"{path}: max_iterations must be between 1 and {MAX_LOOP_HARD}")
        elif node_type is NodeType.PARALLEL:
            join = node.get("join", "all")
            if join not in ("all", "any", "majority", "count"):
                problems.append(f"{path}: unsupported parallel join '{join}'")
        elif node_type is NodeType.APPROVAL:
            approvals.append(node_id)
            assignees = node.get("assignees")
            if not isinstance(assignees, list) or not assignees:
                problems.append(f"{path}: approval node requires assignees")
            strategy = str(node.get("strategy") or "any")
            if strategy not in {"any", "all", "quorum"}:
                problems.append(f"{path}: unsupported approval strategy '{strategy}'")
            quorum = node.get("quorum", 1)
            if strategy == "quorum" and (
                not isinstance(quorum, int)
                or quorum < 1
                or not isinstance(assignees, list)
                or quorum > len(assignees)
            ):
                problems.append(f"{path}: approval quorum must fit the assignee count")

        for key, value in (node.get("inputs") or {}).items():
            if isinstance(value, str) and "{{" in value:
                validate_expression(value, f"{path}.inputs.{key}", problems)

    for index, edge in enumerate(edges):
        path = f"edges[{index}]"
        source, target = edge.get("source"), edge.get("target")
        if source not in node_ids:
            problems.append(f"{path}: unknown source node '{source}'")
        if target not in node_ids:
            problems.append(f"{path}: unknown target node '{target}'")
        if isinstance(edge.get("condition"), str):
            validate_expression(edge["condition"], f"{path}.condition", problems)

    if node_ids and edges and _has_cycle(node_ids, edges):
        problems.append("workflow graph must be acyclic; a cycle was detected")

    unreachable = _unreachable_nodes(nodes, edges)
    if unreachable:
        warnings.append(f"unreachable nodes: {sorted(unreachable)}")

    policy = doc.get("global_policy") or {}
    problems.extend(_validate_policy(policy))

    return ValidationReport(
        valid=not problems,
        problems=problems,
        warnings=warnings,
        node_count=len(nodes),
        external_effect_nodes=external,
        approval_required_nodes=approvals,
        content_hash=canonical_hash(doc),
    )


def _validate_policy(policy: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    checks = (
        ("concurrency", 1, 100, 10),
        ("timeout_seconds", 60, 86_400, 3_600),
        ("retry_attempts", 0, 10, 3),
        ("retry_initial_seconds", 1, 300, 1),
        ("retry_max_seconds", 60, 3_600, 60),
    )
    for key, low, high, _default in checks:
        if key in policy:
            value = policy[key]
            if not isinstance(value, int) or not low <= value <= high:
                problems.append(f"global_policy.{key} must be an integer between {low} and {high}")
    if "error_policy" in policy:
        try:
            ErrorPolicy(policy["error_policy"])
        except ValueError:
            problems.append(f"unknown error policy '{policy['error_policy']}'")
    if "retry_strategy" in policy and policy["retry_strategy"] not in (
        "fixed",
        "exponential",
        "linear",
    ):
        problems.append("retry_strategy must be fixed, exponential or linear")
    return problems


def _has_upstream_approval(
    node_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> bool:
    approval_ids = {n.get("id") for n in nodes if n.get("type") == NodeType.APPROVAL.value}
    if not approval_ids:
        return False
    incoming: dict[str, list[str]] = {}
    for edge in edges:
        incoming.setdefault(str(edge.get("target")), []).append(str(edge.get("source")))
    seen: set[str] = set()
    stack = list(incoming.get(node_id, []))
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        if current in approval_ids:
            return True
        stack.extend(incoming.get(current, []))
    return False


def _has_cycle(node_ids: set[str], edges: list[dict[str, Any]]) -> bool:
    adjacency: dict[str, list[str]] = {n: [] for n in node_ids}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    colour = dict.fromkeys(node_ids, _WHITE)

    def visit(node: str) -> bool:
        colour[node] = _GREY
        for neighbour in adjacency[node]:
            if colour[neighbour] == _GREY:
                return True
            if colour[neighbour] == _WHITE and visit(neighbour):
                return True
        colour[node] = _BLACK
        return False

    return any(colour[n] == _WHITE and visit(n) for n in list(node_ids))


def _unreachable_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> set[str]:
    ids = {str(n.get("id")) for n in nodes if n.get("id")}
    if not ids:
        return set()
    targets = {str(e.get("target")) for e in edges}
    roots = ids - targets
    if not roots:
        return set()
    # Only the declared entry node participates in execution; other roots are orphans.
    entry = {sorted(roots)[0]} if len(roots) > 1 else roots
    adjacency: dict[str, list[str]] = {n: [] for n in ids}
    for edge in edges:
        source = str(edge.get("source"))
        if source in adjacency:
            adjacency[source].append(str(edge.get("target")))
    reachable: set[str] = set()
    stack = list(entry)
    while stack:
        current = stack.pop()
        if current in reachable:
            continue
        reachable.add(current)
        stack.extend(adjacency.get(current, []))
    return ids - reachable


def canonical_hash(doc: dict[str, Any]) -> str:
    """Normalises key order, whitespace, NFC strings and numeric form before hashing."""
    stripped = {k: v for k, v in doc.items() if k not in ("version", "content_hash", "updated_at")}
    return content_hash(stripped)


def compile_workflow(doc: dict[str, Any]) -> dict[str, Any]:
    """Validate then produce the immutable execution plan pinned by a version row."""
    report = validate_workflow(doc)
    if not report.valid:
        raise DslValidationError(report.problems)
    adjacency: dict[str, list[dict[str, Any]]] = {}
    for edge in doc.get("edges", []):
        adjacency.setdefault(str(edge["source"]), []).append(
            {
                "target": str(edge["target"]),
                "condition": edge.get("condition"),
                "label": edge.get("label"),
                "priority": int(edge.get("priority", 0)),
            }
        )
    for targets in adjacency.values():
        targets.sort(key=lambda e: -e["priority"])
    targets_all = {str(e["target"]) for e in doc.get("edges", [])}
    entry = [str(n["id"]) for n in doc["nodes"] if str(n["id"]) not in targets_all]
    return {
        "content_hash": report.content_hash,
        "entry_nodes": entry,
        "nodes": {str(n["id"]): n for n in doc["nodes"]},
        "adjacency": adjacency,
        "trigger": doc.get("trigger", {}),
        "global_policy": {
            "error_policy": "stop",
            "concurrency": 10,
            "timeout_seconds": 3_600,
            "retry_attempts": 3,
            "retry_strategy": "exponential",
            "retry_initial_seconds": 1,
            "retry_max_seconds": 60,
            **(doc.get("global_policy") or {}),
        },
        "external_effect_nodes": report.external_effect_nodes,
        "validation": report.to_dict(),
    }
