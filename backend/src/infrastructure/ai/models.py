"""Pinned model versions and the routing table. A `latest` alias is never used."""

from __future__ import annotations

from dataclasses import dataclass

from shared.compat import StrEnum


class Provider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    LOCAL = "local"


class Task(StrEnum):
    CHAT = "chat"
    GENERATE = "generate"
    CLASSIFY = "classify"
    QUALIFY_LEAD = "qualify_lead"
    EXTRACT = "extract"
    SUMMARIZE = "summarize"
    RAG = "rag"
    ANALYZE = "analyze"
    TRANSCRIBE = "transcribe"
    TRANSLATE = "translate"
    EMBED = "embed"


@dataclass(frozen=True, slots=True)
class ModelSpec:
    provider: Provider
    model: str
    input_micro_inr_per_1k: int
    output_micro_inr_per_1k: int
    max_output_tokens: int = 4_096
    supports_streaming: bool = True


# Exact pinned versions from the AI System specification.
MODELS: dict[str, ModelSpec] = {
    "claude-sonnet-4-20250514": ModelSpec(
        Provider.ANTHROPIC, "claude-sonnet-4-20250514", 249_000, 1_245_000
    ),
    "claude-haiku-3-5-20241022": ModelSpec(
        Provider.ANTHROPIC, "claude-haiku-3-5-20241022", 66_000, 332_000
    ),
    "gpt-4o-2024-08-06": ModelSpec(Provider.OPENAI, "gpt-4o-2024-08-06", 207_000, 830_000),
    "gpt-4o-mini-2024-07-18": ModelSpec(Provider.OPENAI, "gpt-4o-mini-2024-07-18", 12_450, 49_800),
    "gemini-2.0-flash-001": ModelSpec(Provider.GOOGLE, "gemini-2.0-flash-001", 8_300, 33_200),
    "whisper-1": ModelSpec(Provider.OPENAI, "whisper-1", 0, 0, supports_streaming=False),
    "text-embedding-3-small": ModelSpec(
        Provider.OPENAI, "text-embedding-3-small", 1_660, 0, supports_streaming=False
    ),
}


@dataclass(frozen=True, slots=True)
class RoutePolicy:
    """Selection depends on task policy, plan, budget, health and evaluation - never
    on the user's prompt text."""

    task: Task
    tier: str  # "basic" | "pro"
    primary: str
    fallbacks: tuple[str, ...] = ()
    latency_target_ms: int = 5_000
    temperature: float = 0.2
    max_output_tokens: int = 2_048
    requires_schema: bool = False
    degraded_behaviour: str = "manual"


ROUTES: dict[tuple[Task, str], RoutePolicy] = {
    (Task.CHAT, "pro"): RoutePolicy(
        Task.CHAT,
        "pro",
        "claude-sonnet-4-20250514",
        ("gpt-4o-2024-08-06",),
        3_000,
        0.4,
        degraded_behaviour="explain_limitation",
    ),
    (Task.CHAT, "basic"): RoutePolicy(
        Task.CHAT,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001",),
        3_000,
        0.4,
        degraded_behaviour="explain_limitation",
    ),
    (Task.GENERATE, "pro"): RoutePolicy(
        Task.GENERATE,
        "pro",
        "claude-sonnet-4-20250514",
        ("gpt-4o-2024-08-06",),
        5_000,
        0.5,
        degraded_behaviour="offer_template",
    ),
    (Task.GENERATE, "basic"): RoutePolicy(
        Task.GENERATE,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001",),
        5_000,
        0.5,
        degraded_behaviour="offer_template",
    ),
    (Task.ANALYZE, "pro"): RoutePolicy(
        Task.ANALYZE,
        "pro",
        "claude-sonnet-4-20250514",
        ("gpt-4o-2024-08-06",),
        10_000,
        0.2,
        degraded_behaviour="return_raw_data",
    ),
    (Task.ANALYZE, "basic"): RoutePolicy(
        Task.ANALYZE,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001",),
        10_000,
        0.2,
        degraded_behaviour="return_raw_data",
    ),
    (Task.CLASSIFY, "basic"): RoutePolicy(
        Task.CLASSIFY,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001", "claude-haiku-3-5-20241022"),
        2_000,
        0.0,
        requires_schema=True,
        degraded_behaviour="neutral_score_review",
    ),
    (Task.QUALIFY_LEAD, "basic"): RoutePolicy(
        Task.QUALIFY_LEAD,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001", "claude-haiku-3-5-20241022"),
        2_000,
        0.0,
        requires_schema=True,
        degraded_behaviour="neutral_score_review",
    ),
    (Task.EXTRACT, "basic"): RoutePolicy(
        Task.EXTRACT,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001", "claude-haiku-3-5-20241022"),
        2_000,
        0.0,
        requires_schema=True,
        degraded_behaviour="empty_manual",
    ),
    (Task.SUMMARIZE, "basic"): RoutePolicy(
        Task.SUMMARIZE,
        "basic",
        "claude-haiku-3-5-20241022",
        ("gemini-2.0-flash-001",),
        5_000,
        0.3,
        degraded_behaviour="display_source",
    ),
    (Task.RAG, "basic"): RoutePolicy(
        Task.RAG,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001",),
        3_000,
        0.1,
        degraded_behaviour="keyword_search",
    ),
    (Task.TRANSLATE, "basic"): RoutePolicy(
        Task.TRANSLATE,
        "basic",
        "gpt-4o-mini-2024-07-18",
        ("gemini-2.0-flash-001",),
        2_000,
        0.0,
        degraded_behaviour="retain_original",
    ),
    (Task.TRANSCRIBE, "basic"): RoutePolicy(
        Task.TRANSCRIBE,
        "basic",
        "whisper-1",
        (),
        30_000,
        0.0,
        degraded_behaviour="queue_manual_retry",
    ),
    (Task.EMBED, "basic"): RoutePolicy(
        Task.EMBED,
        "basic",
        "text-embedding-3-small",
        (),
        2_000,
        0.0,
        degraded_behaviour="queue_manual_retry",
    ),
}

# Latency targets published in the AI System table.
LATENCY_TARGETS_MS: dict[Task, int] = {
    Task.CHAT: 3_000,
    Task.GENERATE: 5_000,
    Task.CLASSIFY: 2_000,
    Task.QUALIFY_LEAD: 2_000,
    Task.EXTRACT: 2_000,
    Task.SUMMARIZE: 5_000,
    Task.RAG: 3_000,
    Task.ANALYZE: 10_000,
    Task.TRANSCRIBE: 30_000,
    Task.TRANSLATE: 2_000,
    Task.EMBED: 2_000,
}

DEGRADED_MESSAGES: dict[str, str] = {
    "explain_limitation": (
        "The assistant is temporarily unavailable. You can continue working manually."
    ),
    "offer_template": "Automatic drafting is unavailable. A template has been offered instead.",
    "neutral_score_review": (
        "Automatic qualification is unavailable. A neutral score was assigned for review."
    ),
    "empty_manual": "Automatic extraction is unavailable. Please enter the values manually.",
    "display_source": "Summarisation is unavailable. The full source is shown instead.",
    "keyword_search": "Semantic search is unavailable. Keyword search was used instead.",
    "return_raw_data": "Analysis is unavailable. The underlying data is available for export.",
    "retain_original": "Translation is unavailable. The original text has been retained.",
    "queue_manual_retry": "The request was queued and will be retried automatically.",
    "manual": "The AI feature is unavailable. A manual path is available.",
}


def route_for(task: Task | str, tier: str = "basic") -> RoutePolicy:
    key = (Task(task), tier)
    if key not in ROUTES:
        key = (Task(task), "basic")
    if key not in ROUTES:
        raise KeyError(f"no route configured for task {task}")
    return ROUTES[key]


def cost_micro_inr(model: str, *, input_tokens: int, output_tokens: int) -> int:
    spec = MODELS[model]
    return (
        input_tokens * spec.input_micro_inr_per_1k // 1_000
        + output_tokens * spec.output_micro_inr_per_1k // 1_000
    )


def assert_no_latest_aliases() -> None:
    """Release gate: a floating alias would silently change model behaviour."""
    for name in MODELS:
        if "latest" in name or name.endswith("-preview"):
            raise AssertionError(f"model '{name}' uses a floating alias")
