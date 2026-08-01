"""Lead lifecycle state machine and normalised duplicate detection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.base import InvalidTransition
from shared.compat import StrEnum
from shared.utils.phone import try_normalize_phone
from shared.utils.text import normalize_name_key


class LeadStatus(StrEnum):
    NEW = "new"
    QUALIFIED = "qualified"
    CONTACTED = "contacted"
    NURTURING = "nurturing"
    CONVERTED = "converted"
    DISQUALIFIED = "disqualified"
    ARCHIVED = "archived"


TERMINAL = frozenset({LeadStatus.CONVERTED, LeadStatus.DISQUALIFIED, LeadStatus.ARCHIVED})

ALLOWED_TRANSITIONS: dict[LeadStatus, frozenset[LeadStatus]] = {
    LeadStatus.NEW: frozenset(
        {
            LeadStatus.QUALIFIED,
            LeadStatus.CONTACTED,
            LeadStatus.NURTURING,
            LeadStatus.DISQUALIFIED,
            LeadStatus.ARCHIVED,
        }
    ),
    LeadStatus.QUALIFIED: frozenset(
        {
            LeadStatus.CONTACTED,
            LeadStatus.NURTURING,
            LeadStatus.CONVERTED,
            LeadStatus.DISQUALIFIED,
            LeadStatus.ARCHIVED,
        }
    ),
    LeadStatus.CONTACTED: frozenset(
        {
            LeadStatus.QUALIFIED,
            LeadStatus.NURTURING,
            LeadStatus.CONVERTED,
            LeadStatus.DISQUALIFIED,
            LeadStatus.ARCHIVED,
        }
    ),
    LeadStatus.NURTURING: frozenset(
        {
            LeadStatus.CONTACTED,
            LeadStatus.QUALIFIED,
            LeadStatus.CONVERTED,
            LeadStatus.DISQUALIFIED,
            LeadStatus.ARCHIVED,
        }
    ),
    LeadStatus.CONVERTED: frozenset(),
    LeadStatus.DISQUALIFIED: frozenset({LeadStatus.NURTURING, LeadStatus.ARCHIVED}),
    LeadStatus.ARCHIVED: frozenset({LeadStatus.NEW}),
}

REQUIRES_REASON = frozenset({LeadStatus.DISQUALIFIED})


def can_transition(current: LeadStatus | str, target: LeadStatus | str) -> bool:
    return LeadStatus(target) in ALLOWED_TRANSITIONS[LeadStatus(current)]


def assert_transition(
    current: LeadStatus | str, target: LeadStatus | str, *, reason: str | None = None
) -> LeadStatus:
    cur, tgt = LeadStatus(current), LeadStatus(target)
    if cur == tgt:
        return tgt
    if tgt not in ALLOWED_TRANSITIONS[cur]:
        raise InvalidTransition(f"cannot move a lead from {cur.value} to {tgt.value}")
    if tgt in REQUIRES_REASON and not reason:
        raise InvalidTransition(f"a reason is required to move a lead to {tgt.value}")
    return tgt


# -- duplicate detection ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class DuplicateCandidate:
    lead_id: str
    match_reason: str
    confidence: float


MATCH_WEIGHTS = {
    "email_exact": 1.0,
    "phone_exact": 0.95,
    "name_and_company": 0.72,
    "name_and_source_window": 0.55,
}
AUTO_MERGE_THRESHOLD = 0.95
REVIEW_THRESHOLD = 0.50


def dedupe_key(
    *, email: str | None = None, phone: str | None = None, name: str | None = None
) -> str | None:
    """Deterministic natural key used for the concurrent-capture unique constraint."""
    if email:
        return f"e:{email.strip().lower()}"
    normalized = try_normalize_phone(phone) if phone else None
    if normalized:
        return f"p:{normalized}"
    if name:
        key = normalize_name_key(name)
        return f"n:{key}" if key else None
    return None


def find_duplicates(
    candidate: dict[str, Any], existing: list[dict[str, Any]]
) -> list[DuplicateCandidate]:
    """Normalised matching. The raw source event is preserved regardless of outcome."""
    email = (candidate.get("email") or "").strip().lower() or None
    phone = try_normalize_phone(candidate.get("phone"))
    name_key = normalize_name_key(
        f"{candidate.get('first_name', '')} {candidate.get('last_name', '')}"
    )
    company_key = normalize_name_key(candidate.get("company") or "")

    results: list[DuplicateCandidate] = []
    for row in existing:
        row_email = (row.get("email") or "").strip().lower() or None
        row_phone = try_normalize_phone(row.get("phone"))
        row_name = normalize_name_key(f"{row.get('first_name', '')} {row.get('last_name', '')}")
        row_company = normalize_name_key(row.get("company") or "")

        reason: str | None = None
        if email and row_email and email == row_email:
            reason = "email_exact"
        elif phone and row_phone and phone == row_phone:
            reason = "phone_exact"
        elif name_key and company_key and name_key == row_name and company_key == row_company:
            reason = "name_and_company"
        elif (
            name_key
            and name_key == row_name
            and candidate.get("source")
            and candidate.get("source") == row.get("source")
        ):
            reason = "name_and_source_window"

        if reason:
            results.append(DuplicateCandidate(str(row["id"]), reason, MATCH_WEIGHTS[reason]))

    return sorted(results, key=lambda c: c.confidence, reverse=True)


def duplicate_resolution(candidates: list[DuplicateCandidate]) -> str:
    """`merge` is only automatic for exact identity matches; everything else is reviewed."""
    if not candidates:
        return "create"
    best = candidates[0]
    if best.confidence >= AUTO_MERGE_THRESHOLD:
        return "merge"
    if best.confidence >= REVIEW_THRESHOLD:
        return "review"
    return "create"
