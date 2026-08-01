"""Industry template application.

Templates are versioned configuration only. Applying or upgrading one records the
version and the tenant's divergence; it never overwrites tenant customisation and
never introduces hidden behaviour or an industry code path.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "database"
    / "seeds"
    / ("industry_templates.json")
)

MANDATORY_TEMPLATE_CODES: tuple[str, ...] = (
    "real_estate",
    "clinics",
    "coaching_institutes",
    "recruitment",
    "marketing_agencies",
    "ca_firms",
    "gyms",
    "automobile_dealerships",
)
GENERIC_TEMPLATE_CODE = "other_sme"

# Configuration keys a tenant may customise. Anything else is template-owned.
CUSTOMISABLE_KEYS = frozenset(
    {
        "terminology",
        "lead_schema",
        "qualification_rubric",
        "pipeline_stages",
        "message_templates",
        "document_templates",
        "business_hours",
        "dashboard_presets",
        "consent_copy",
    }
)
# Guardrails are never customisable downward by a tenant.
IMMUTABLE_KEYS = frozenset({"prohibited_ai_rules", "emergency_routing", "minor_policy"})


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    return catalog


def get_template(code: str, version: int | None = None) -> dict[str, Any]:
    catalog = load_catalog()
    if code not in catalog:
        raise KeyError(f"unknown industry template '{code}'")
    template = catalog[code]
    if version is not None and template["version"] != version:
        raise KeyError(f"template '{code}' version {version} is not available")
    return template


def available_codes() -> list[str]:
    return sorted(load_catalog())


@dataclass(slots=True)
class AppliedTemplate:
    code: str
    version: int
    configuration: dict[str, Any]
    divergence: dict[str, Any] = field(default_factory=dict)
    preserved_customisations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "template_code": self.code,
            "template_version": self.version,
            "configuration": self.configuration,
            "divergence": self.divergence,
            "preserved_customisations": self.preserved_customisations,
        }


def apply_template(
    code: str,
    *,
    existing_customisations: dict[str, Any] | None = None,
    version: int | None = None,
) -> AppliedTemplate:
    """Merge template defaults under tenant customisation, never over it."""
    template = get_template(code, version)
    customisations = existing_customisations or {}

    configuration: dict[str, Any] = {}
    divergence: dict[str, Any] = {}
    preserved: list[str] = []

    for key, template_value in template.items():
        if key in ("code", "version", "name", "active"):
            continue
        if key in IMMUTABLE_KEYS:
            # Guardrails always come from the template version, whatever the tenant set.
            configuration[key] = template_value
            if key in customisations:
                divergence[key] = {
                    "status": "override_rejected",
                    "reason": "guardrail configuration is not tenant customisable",
                }
            continue
        if key in customisations and key in CUSTOMISABLE_KEYS:
            configuration[key] = customisations[key]
            preserved.append(key)
            divergence[key] = {"status": "customised", "template_version": template["version"]}
        else:
            configuration[key] = template_value

    return AppliedTemplate(
        code=code,
        version=int(template["version"]),
        configuration=configuration,
        divergence=divergence,
        preserved_customisations=sorted(preserved),
    )


def upgrade_template(
    code: str,
    *,
    from_version: int,
    to_version: int,
    existing_customisations: dict[str, Any] | None = None,
) -> AppliedTemplate:
    """An upgrade is an apply that additionally records the version delta."""
    applied = apply_template(
        code, existing_customisations=existing_customisations, version=to_version
    )
    applied.divergence["_upgrade"] = {
        "from_version": from_version,
        "to_version": to_version,
        "customisations_preserved": applied.preserved_customisations,
    }
    return applied


def prohibited_rules(code: str) -> list[dict[str, Any]]:
    return list(get_template(code).get("prohibited_ai_rules", []))


def qualification_criteria(code: str) -> list[dict[str, Any]]:
    return list(get_template(code)["qualification_rubric"]["criteria"])


def pipeline_stages(code: str) -> list[dict[str, Any]]:
    return list(get_template(code)["pipeline_stages"])


def terminology(code: str) -> dict[str, Any]:
    return dict(get_template(code)["terminology"])


def validate_catalog() -> list[str]:
    """Structural checks run as a release gate, not only at runtime."""
    problems: list[str] = []
    catalog = load_catalog()
    for required in MANDATORY_TEMPLATE_CODES:
        if required not in catalog:
            problems.append(f"mandatory template '{required}' is missing")
    for code, template in catalog.items():
        for key in (
            "terminology",
            "lead_schema",
            "qualification_rubric",
            "pipeline_stages",
            "message_templates",
            "business_hours",
            "prohibited_ai_rules",
            "consent_copy",
        ):
            if key not in template:
                problems.append(f"{code}: missing '{key}'")
        stages = template.get("pipeline_stages", [])
        if not any(s.get("is_won") for s in stages):
            problems.append(f"{code}: pipeline has no won stage")
        if not any(s.get("is_lost") for s in stages):
            problems.append(f"{code}: pipeline has no lost stage")
        positions = [s.get("position") for s in stages]
        if positions != sorted(positions) or len(set(positions)) != len(positions):
            problems.append(f"{code}: pipeline stage positions must be unique and ordered")
        criteria = template.get("qualification_rubric", {}).get("criteria", [])
        if sum(c.get("weight", 0) for c in criteria) != 100:
            problems.append(f"{code}: qualification rubric weights must total 100")
        if code in MANDATORY_TEMPLATE_CODES and not template.get("prohibited_ai_rules"):
            problems.append(f"{code}: at least one prohibited AI rule is required")
    return problems
