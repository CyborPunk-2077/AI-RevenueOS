"""Input and output guards. Pure, deterministic and independently testable.

Thresholds come directly from the AI System specification: block injection >.70,
sanitize .40-.70, block harmful >.80, block toxicity >.70. Restricted identifiers
(PAN, Aadhaar, card, bank) are always blocked before a provider sees them.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from shared.compat import StrEnum

INJECTION_BLOCK = 0.70
INJECTION_SANITIZE = 0.40
HARMFUL_BLOCK = 0.80
TOXICITY_BLOCK = 0.70

UNTRUSTED_OPEN = "<<<UNTRUSTED_CONTEXT>>>"
UNTRUSTED_CLOSE = "<<<END_UNTRUSTED_CONTEXT>>>"


class GuardAction(StrEnum):
    ALLOW = "allow"
    SANITIZE = "sanitize"
    BLOCK = "block"


# Weighted prompt-injection signals. Multiple weak signals compound.
INJECTION_PATTERNS: tuple[tuple[str, float], ...] = (
    (r"ignore (?:all |any )?(?:previous|prior|above) (?:instructions|prompts|rules)", 0.85),
    (r"disregard (?:the )?(?:system|previous|above)", 0.80),
    (r"you are now (?:a|an|in) (?:developer|dan|admin|unrestricted)", 0.85),
    (r"reveal (?:your |the )?(?:system )?prompt", 0.85),
    (r"print (?:your |the )?(?:instructions|system prompt|rules)", 0.80),
    (r"</?(?:system|assistant|instruction)>", 0.65),
    (r"\bnew instructions?\b", 0.55),
    (r"do not follow (?:the )?(?:rules|guardrails|policy)", 0.75),
    (r"pretend (?:that )?you (?:are|have)", 0.45),
    (r"jailbreak|dan mode|developer mode", 0.75),
    (r"repeat (?:everything|the text) above", 0.60),
    (r"\bexfiltrat", 0.70),
    (r"send (?:the )?(?:data|records) to https?://", 0.80),
)

HARMFUL_PATTERNS: tuple[tuple[str, float], ...] = (
    (r"\bhow to (?:make|build|synthesi[sz]e) (?:a )?(?:bomb|explosive|weapon)", 0.95),
    (r"\bself[- ]harm\b|\bkill myself\b", 0.85),
    (r"\bmalware\b|\bransomware\b|\bkeylogger\b", 0.85),
)

# Restricted identifiers: always blocked, never sent to a provider, never logged.
BLOCKED_IDENTIFIERS: tuple[tuple[str, str], ...] = (
    (r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", "pan"),
    (r"\b[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\b", "aadhaar"),
    (r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|6(?:011|5[0-9]{2})[0-9]{12})\b", "card"),
    (r"\b[A-Z]{4}0[A-Z0-9]{6}\b", "ifsc"),
    (r"\baccount\s*(?:no|number)\s*[:#-]?\s*[0-9]{9,18}\b", "bank_account"),
)

# Minimum-policy PII: masked rather than blocked.
MINIMISE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b", "email"),
    # Indian numbers appear grouped ("+91 98765 43210"), hyphenated or bare.
    (r"(?:\+?91[\s-]?)?[6-9](?:[\s-]?[0-9]){9}\b", "phone"),
    (r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]{3}\b", "gstin"),
)


@dataclass(frozen=True, slots=True)
class GuardResult:
    action: GuardAction
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    text: str = ""
    detected: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.action is GuardAction.BLOCK

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action.value,
            "score": round(self.score, 3),
            "reasons": self.reasons,
            "detected": self.detected,
        }


def _score(text: str, patterns: tuple[tuple[str, float], ...]) -> tuple[float, list[str]]:
    """Compound independent probabilities rather than taking a naive maximum."""
    hits: list[str] = []
    inverse = 1.0
    for pattern, weight in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            hits.append(pattern)
            inverse *= 1.0 - weight
    return (1.0 - inverse), hits


def scan_input(text: str, *, is_untrusted_context: bool = False) -> GuardResult:
    """Guard applied to every user message and every retrieved context block."""
    if not text:
        return GuardResult(GuardAction.ALLOW, text="")

    reasons: list[str] = []
    detected: list[str] = []

    for pattern, label in BLOCKED_IDENTIFIERS:
        if re.search(pattern, text):
            detected.append(label)
    if detected:
        return GuardResult(
            GuardAction.BLOCK,
            1.0,
            [f"restricted identifier detected: {', '.join(sorted(set(detected)))}"],
            "",
            sorted(set(detected)),
        )

    harmful, harmful_hits = _score(text, HARMFUL_PATTERNS)
    if harmful > HARMFUL_BLOCK:
        return GuardResult(
            GuardAction.BLOCK, harmful, ["harmful content detected"], "", harmful_hits
        )

    injection, injection_hits = _score(text, INJECTION_PATTERNS)
    if injection > INJECTION_BLOCK:
        return GuardResult(
            GuardAction.BLOCK, injection, ["prompt injection detected"], "", injection_hits
        )

    sanitized = text
    if injection > INJECTION_SANITIZE:
        reasons.append("suspicious instruction-like content neutralised")
        sanitized = re.sub(
            r"(?i)(ignore|disregard|override)\s+(all\s+|any\s+)?(previous|prior|above)",
            "[neutralised]",
            sanitized,
        )

    minimised, mask_labels = minimise_pii(sanitized)
    if mask_labels:
        reasons.append(f"minimised identifiers: {', '.join(sorted(set(mask_labels)))}")

    if is_untrusted_context:
        minimised = f"{UNTRUSTED_OPEN}\n{minimised}\n{UNTRUSTED_CLOSE}"
        reasons.append("context delimited as untrusted; tools must not follow its instructions")

    action = GuardAction.SANITIZE if reasons else GuardAction.ALLOW
    return GuardResult(action, injection, reasons, minimised, sorted(set(mask_labels)))


def minimise_pii(text: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    out = text
    for pattern, label in MINIMISE_PATTERNS:
        if re.search(pattern, out):
            labels.append(label)
            out = re.sub(pattern, f"[{label.upper()}]", out)
    return out, labels


PROMPT_LEAK_MARKERS = (
    "you are an ai assistant for ai revenueos",
    "system prompt:",
    "<<<untrusted_context>>>",
    "your instructions are",
)

TOXICITY_PATTERNS: tuple[tuple[str, float], ...] = (
    (r"\b(?:idiot|moron|stupid)\b", 0.45),
    (r"\b(?:hate|despise) (?:you|them|him|her)\b", 0.55),
    (r"\bkill (?:you|him|her|them)\b", 0.90),
)

# Claims the product may never make, per the industry template guardrails.
PROHIBITED_CLAIM_PATTERNS: dict[str, tuple[str, ...]] = {
    "medical": (
        r"\byou (?:have|are suffering from)\b.{0,40}\b(?:cancer|diabetes|covid|infection)\b",
        r"\b(?:diagnos(?:is|e|ed))\b",
        r"\bprescrib(?:e|ed|ing)\b",
        r"\btake \d+\s*mg\b",
    ),
    "legal_tax": (
        r"\byou (?:should|must) claim\b",
        r"\btax (?:opinion|advice)\b",
        r"\blegally (?:you are|you're) (?:entitled|required)\b",
    ),
    "guarantee": (
        r"\bguarantee[ds]?\b",
        r"\bassured (?:returns|placement|rank|results)\b",
        r"\b100% (?:success|placement|selection)\b",
        r"\bwill definitely\b",
    ),
    "binding_commercial": (
        r"\bfinal price is\b",
        r"\bwe confirm (?:availability|inventory|delivery)\b",
        r"\bbooking is confirmed\b",
        r"\binterest rate (?:is|will be) \d",
    ),
    "employment": (
        r"\bcandidate (?:is )?rejected\b",
        r"\bnot suitable because (?:of )?(?:his|her|their) "
        r"(?:age|gender|religion|caste|marital)\b",
    ),
}

# Which prohibition families each industry template must enforce.
TEMPLATE_PROHIBITIONS: dict[str, tuple[str, ...]] = {
    "real_estate": ("binding_commercial", "guarantee"),
    "clinics": ("medical", "guarantee"),
    "coaching_institutes": ("guarantee",),
    "recruitment": ("employment", "guarantee"),
    "marketing_agencies": ("guarantee",),
    "ca_firms": ("legal_tax", "guarantee"),
    "gyms": ("medical", "guarantee"),
    "automobile_dealerships": ("binding_commercial", "guarantee"),
    "other_sme": ("guarantee",),
}


def scan_output(
    text: str,
    *,
    industry_code: str | None = None,
    schema: dict[str, Any] | None = None,
    require_citations: bool = False,
    citations: list[Any] | None = None,
) -> GuardResult:
    """Guard applied to every model output before it reaches a user or a tool."""
    reasons: list[str] = []
    detected: list[str] = []
    lowered = text.lower()

    for marker in PROMPT_LEAK_MARKERS:
        if marker in lowered:
            return GuardResult(
                GuardAction.BLOCK, 1.0, ["output leaks system prompt content"], "", ["prompt_leak"]
            )

    toxicity, tox_hits = _score(text, TOXICITY_PATTERNS)
    if toxicity > TOXICITY_BLOCK:
        return GuardResult(GuardAction.BLOCK, toxicity, ["toxic output"], "", tox_hits)

    families = TEMPLATE_PROHIBITIONS.get(industry_code or "other_sme", ("guarantee",))
    for family in families:
        for pattern in PROHIBITED_CLAIM_PATTERNS[family]:
            if re.search(pattern, text, re.IGNORECASE):
                detected.append(family)
                break
    if detected:
        return GuardResult(
            GuardAction.BLOCK,
            1.0,
            [f"prohibited claim for this industry: {', '.join(sorted(set(detected)))}"],
            "",
            sorted(set(detected)),
        )

    redacted, labels = redact_output_pii(text)
    if labels:
        reasons.append(f"redacted restricted identifiers: {', '.join(sorted(set(labels)))}")

    if require_citations and not citations:
        return GuardResult(
            GuardAction.BLOCK,
            1.0,
            ["a grounded answer was requested but no source citation was produced"],
            "",
            ["missing_citation"],
        )

    if schema is not None:
        ok, problem = validate_against_schema(redacted, schema)
        if not ok:
            return GuardResult(
                GuardAction.BLOCK,
                1.0,
                [f"output failed schema validation: {problem}"],
                "",
                ["schema_invalid"],
            )

    return GuardResult(
        GuardAction.SANITIZE if reasons else GuardAction.ALLOW,
        toxicity,
        reasons,
        redacted,
        sorted(set(labels)),
    )


def redact_output_pii(text: str) -> tuple[str, list[str]]:
    labels: list[str] = []
    out = text
    for pattern, label in BLOCKED_IDENTIFIERS:
        if re.search(pattern, out):
            labels.append(label)
            out = re.sub(pattern, f"[{label.upper()}_REDACTED]", out)
    return out, labels


def validate_against_schema(text: str, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Minimal structural validation of a JSON response against a declared schema."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON ({exc.msg})"
    if schema.get("type") == "object" and not isinstance(payload, dict):
        return False, "expected a JSON object"
    for key in schema.get("required", []):
        if key not in payload:
            return False, f"missing required field '{key}'"
    for key, spec in (schema.get("properties") or {}).items():
        if key not in payload:
            continue
        expected = spec.get("type")
        value = payload[key]
        type_map: dict[str, type | tuple[type, ...]] = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        if expected in type_map and not isinstance(value, type_map[expected]):
            return False, f"field '{key}' must be of type {expected}"
        if expected == "integer" and isinstance(value, bool):
            return False, f"field '{key}' must be of type integer"
        if "minimum" in spec and isinstance(value, (int, float)) and value < spec["minimum"]:
            return False, f"field '{key}' is below the minimum"
        if "maximum" in spec and isinstance(value, (int, float)) and value > spec["maximum"]:
            return False, f"field '{key}' is above the maximum"
        if "enum" in spec and value not in spec["enum"]:
            return False, f"field '{key}' is not one of the permitted values"
    return True, None


# Actions AI may never take autonomously, whatever the prompt asks for.
FORBIDDEN_AUTONOMOUS_ACTIONS = frozenset(
    {
        "payment.refund",
        "payment.capture",
        "contact.delete",
        "lead.delete",
        "deal.delete",
        "tenant.delete",
        "user.deactivate",
        "document.send",
        "message.send_whatsapp",
        "message.send_email",
        "message.send_sms",
        "appointment.cancel",
        "workflow.publish",
        "candidate.reject",
        "role.update",
        "api_key.create",
        "export.create",
        # Copilot tool names: every mutating tool is confirmation-gated by the same rule.
        "send_message",
        "create_task",
        "schedule_appointment",
        "update_lead_stage",
        "generate_document",
    }
)


def requires_human_confirmation(action: str) -> bool:
    return action in FORBIDDEN_AUTONOMOUS_ACTIONS
