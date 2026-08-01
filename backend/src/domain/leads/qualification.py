"""Deterministic qualification scoring driven by the tenant's industry rubric.

The AI qualifier proposes; this module is the arbiter of score bands and of what
counts as evidence. A missing model or a guard block degrades to neutral-50 plus a
review flag - it never fabricates a confident score.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.compat import StrEnum

HOT_THRESHOLD = 80
WARM_THRESHOLD = 40
NEUTRAL_DEGRADED_SCORE = 50


class Category(StrEnum):
    HOT = "hot"
    WARM = "warm"
    COLD = "cold"


class ReviewState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"
    DEFERRED = "deferred"


def categorize(score: int) -> Category:
    if not 0 <= score <= 100:
        raise ValueError("qualification score must be between 0 and 100")
    if score >= HOT_THRESHOLD:
        return Category.HOT
    if score >= WARM_THRESHOLD:
        return Category.WARM
    return Category.COLD


@dataclass(frozen=True, slots=True)
class Criterion:
    """One rubric line: a weighted, evidence-backed signal."""

    key: str
    label: str
    weight: int
    required: bool = False


@dataclass(frozen=True, slots=True)
class Evidence:
    criterion: str
    value: Any
    source: str  # "capture" | "enrichment" | "conversation" | "document" | "manual"
    excerpt: str | None = None
    confidence: float = 1.0


@dataclass(frozen=True, slots=True)
class QualificationResult:
    score: int
    category: Category
    evidence: list[Evidence] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    qualified_by: str = "rule"  # "rule" | "ai" | "manual"
    degraded: bool = False
    review_state: ReviewState = ReviewState.PENDING
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": self.score,
            "category": self.category.value,
            "evidence": [
                {
                    "criterion": e.criterion,
                    "value": e.value,
                    "source": e.source,
                    "excerpt": e.excerpt,
                    "confidence": e.confidence,
                }
                for e in self.evidence
            ],
            "reasons": self.reasons,
            "missing_fields": self.missing_fields,
            "qualified_by": self.qualified_by,
            "degraded": self.degraded,
            "review_state": self.review_state.value,
            "provenance": self.provenance,
        }


def score_from_rubric(
    rubric: list[Criterion] | list[dict[str, Any]], capture: dict[str, Any]
) -> QualificationResult:
    """Weighted rubric scoring. Absent signals become explicit `missing_fields`."""
    criteria = [
        c if isinstance(c, Criterion) else Criterion(**c)  # type: ignore[arg-type]
        for c in rubric
    ]
    total_weight = sum(c.weight for c in criteria) or 1
    earned = 0
    evidence: list[Evidence] = []
    missing: list[str] = []
    reasons: list[str] = []

    for criterion in criteria:
        value = capture.get(criterion.key)
        present = value not in (None, "", [], {})
        if present:
            earned += criterion.weight
            evidence.append(Evidence(criterion=criterion.key, value=value, source="capture"))
            reasons.append(f"{criterion.label} provided")
        else:
            missing.append(criterion.key)
            if criterion.required:
                reasons.append(f"{criterion.label} is required and missing")

    score = round(earned * 100 / total_weight)
    return QualificationResult(
        score=score,
        category=categorize(score),
        evidence=evidence,
        reasons=reasons,
        missing_fields=missing,
        qualified_by="rule",
        provenance={"method": "rubric", "criteria_count": len(criteria)},
    )


def degraded_result(reason: str) -> QualificationResult:
    """Used whenever the AI path is unavailable, blocked or schema-invalid."""
    return QualificationResult(
        score=NEUTRAL_DEGRADED_SCORE,
        category=categorize(NEUTRAL_DEGRADED_SCORE),
        reasons=[f"Automatic qualification unavailable: {reason}. Manual review required."],
        qualified_by="rule",
        degraded=True,
        review_state=ReviewState.PENDING,
        provenance={"method": "degraded", "reason": reason},
    )


def apply_human_decision(
    result: QualificationResult,
    *,
    decision: str,
    edited_score: int | None = None,
    note: str | None = None,
) -> QualificationResult:
    """Human accept/edit/reject/defer. Every path is auditable and reversible."""
    state = ReviewState(decision)
    score = result.score
    qualified_by = result.qualified_by
    reasons = list(result.reasons)

    if state is ReviewState.EDITED:
        if edited_score is None:
            raise ValueError("an edited decision must supply a score")
        score = edited_score
        qualified_by = "manual"
        reasons.append(f"Score edited by reviewer to {edited_score}.")
    elif state is ReviewState.REJECTED:
        qualified_by = "manual"
        reasons.append("AI qualification rejected by reviewer.")
    if note:
        reasons.append(note)

    return QualificationResult(
        score=score,
        category=categorize(score),
        evidence=result.evidence,
        reasons=reasons,
        missing_fields=result.missing_fields,
        qualified_by=qualified_by,
        degraded=result.degraded,
        review_state=state,
        provenance={**result.provenance, "reviewed": True},
    )
