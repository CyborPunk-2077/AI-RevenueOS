"""Assignment rule matching and target selection. Pure policy: no I/O.

Rules are ordered and the first match wins. That is a deliberate choice over
"most specific wins": ordering is visible in the UI and explainable to the person
whose leads stopped arriving, whereas specificity scoring is not.

`round_robin` is stateful - it needs a cursor - so the caller persists the cursor
the selector returns. Keeping the arithmetic here and the persistence outside is
what makes the fairness property testable without a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from shared.exceptions import ValidationError

STRATEGIES: Final[frozenset[str]] = frozenset({"round_robin", "first_available", "load_balanced"})

OPERATORS: Final[frozenset[str]] = frozenset(
    {"equals", "not_equals", "contains", "starts_with", "in", "is_set", "is_not_set"}
)

#: Lead attributes a rule may branch on. Free-form capture data is deliberately
#: excluded: a rule that reads an arbitrary key silently stops matching the day
#: someone renames a form field.
CONDITION_FIELDS: Final[frozenset[str]] = frozenset(
    {"source", "source_channel", "city", "company", "category", "qualification_score", "status"}
)

MAX_CONDITIONS: Final = 10
MAX_TARGETS: Final = 50


@dataclass(frozen=True, slots=True)
class Assignment:
    assignee_id: str
    rule_id: str | None
    rule_name: str | None
    strategy: str | None
    #: The cursor the caller must persist for this rule. `None` when the strategy
    #: is stateless.
    next_cursor: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "assignee_id": self.assignee_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "strategy": self.strategy,
        }


def validate_rule(
    *, strategy: str, conditions: dict[str, Any], targets: list[Any]
) -> tuple[dict[str, Any], list[str]]:
    """Refuse a rule that cannot fire, or that would assign to nobody."""
    problems: list[str] = []

    if strategy not in STRATEGIES:
        problems.append(f"{strategy!r} is not an assignment strategy.")

    clauses = conditions.get("all", []) if isinstance(conditions, dict) else []
    if not isinstance(clauses, list):
        problems.append("Conditions must be a list under `all`.")
        clauses = []
    if len(clauses) > MAX_CONDITIONS:
        problems.append(f"A rule may have at most {MAX_CONDITIONS} conditions.")

    normalised: list[dict[str, Any]] = []
    for index, clause in enumerate(clauses):
        if not isinstance(clause, dict):
            problems.append(f"Condition {index} is not an object.")
            continue
        field_name = str(clause.get("field", ""))
        operator = str(clause.get("operator", "equals"))
        if field_name not in CONDITION_FIELDS:
            problems.append(f"Condition {index}: {field_name!r} is not a field a rule can read.")
            continue
        if operator not in OPERATORS:
            problems.append(f"Condition {index}: {operator!r} is not an operator.")
            continue
        if operator not in ("is_set", "is_not_set") and clause.get("value") in (None, ""):
            problems.append(f"Condition {index}: {operator!r} needs a value.")
            continue
        normalised.append({"field": field_name, "operator": operator, "value": clause.get("value")})

    cleaned_targets = [str(t) for t in targets or [] if str(t).strip()]
    if not cleaned_targets:
        problems.append("A rule needs at least one assignee.")
    if len(cleaned_targets) > MAX_TARGETS:
        problems.append(f"A rule may have at most {MAX_TARGETS} assignees.")
    if len(set(cleaned_targets)) != len(cleaned_targets):
        problems.append("The same assignee is listed more than once.")

    if problems:
        raise ValidationError("This assignment rule is not valid.", details={"problems": problems})

    return {"all": normalised}, cleaned_targets


def _clause_matches(clause: dict[str, Any], lead: dict[str, Any]) -> bool:
    actual = lead.get(clause["field"])
    operator = clause["operator"]
    expected = clause.get("value")

    if operator == "is_set":
        return actual not in (None, "")
    if operator == "is_not_set":
        return actual in (None, "")
    if actual is None:
        return False

    if operator in ("equals", "not_equals"):
        # Numbers compare as numbers; everything else compares case-insensitively,
        # because "Web" and "web" are the same source to a human.
        if isinstance(actual, int | float) and isinstance(expected, int | float):
            equal = actual == expected
        else:
            equal = str(actual).strip().lower() == str(expected).strip().lower()
        return equal if operator == "equals" else not equal
    if operator == "contains":
        return str(expected).strip().lower() in str(actual).lower()
    if operator == "starts_with":
        return str(actual).lower().startswith(str(expected).strip().lower())
    if operator == "in":
        values = expected if isinstance(expected, list) else [expected]
        return str(actual).strip().lower() in {str(v).strip().lower() for v in values}
    return False


def rule_matches(rule: dict[str, Any], lead: dict[str, Any]) -> bool:
    """A rule with no conditions is a catch-all, which is how a default is expressed."""
    clauses = (rule.get("conditions") or {}).get("all", [])
    return all(_clause_matches(clause, lead) for clause in clauses)


def select_assignee(
    rules: list[dict[str, Any]],
    lead: dict[str, Any],
    *,
    workloads: dict[str, int] | None = None,
    eligible: set[str] | None = None,
) -> Assignment | None:
    """First matching active rule wins. Returns `None` when nothing matches.

    `None` means unassigned, which is a legitimate outcome: inventing an assignee
    so that a field is populated is how leads end up owned by someone who never
    agreed to own them.
    """
    for rule in sorted(rules, key=lambda r: (int(r.get("position", 0)), str(r.get("id")))):
        if not rule.get("is_active", True):
            continue
        if not rule_matches(rule, lead):
            continue

        targets = [str(t) for t in rule.get("targets") or []]
        if eligible is not None:
            # A target who has left the organisation must not keep receiving work.
            targets = [t for t in targets if t in eligible]
        if not targets:
            continue

        strategy = str(rule.get("strategy", "round_robin"))
        cursor = int(rule.get("cursor", 0))

        if strategy == "load_balanced" and workloads is not None:
            chosen = min(targets, key=lambda t: (workloads.get(t, 0), targets.index(t)))
            next_cursor = None
        elif strategy == "first_available":
            chosen = targets[0]
            next_cursor = None
        else:
            chosen = targets[cursor % len(targets)]
            next_cursor = (cursor + 1) % len(targets)

        return Assignment(
            assignee_id=chosen,
            rule_id=str(rule.get("id")) if rule.get("id") else None,
            rule_name=str(rule.get("name")) if rule.get("name") else None,
            strategy=strategy,
            next_cursor=next_cursor,
        )
    return None


_SAFE_NAME = re.compile(r"^[\w \-/&().]{1,150}$")


def validate_rule_name(name: str) -> str:
    cleaned = name.strip()
    if not _SAFE_NAME.match(cleaned):
        raise ValidationError("That rule name is not usable.", details={"name": name})
    return cleaned
