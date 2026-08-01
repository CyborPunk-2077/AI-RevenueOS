"""Classification-aware redaction. P3/P4 never reach logs, traces or AI providers."""

from __future__ import annotations

import re
from typing import Any

SECRET_KEYS = frozenset(
    {
        "password",
        "current_password",
        "new_password",
        "password_hash",
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "api_key",
        "secret",
        "client_secret",
        "webhook_secret",
        "signature",
        "private_key",
        "encryption_key",
        "otp",
        "totp_seed",
        "recovery_code",
        "card",
        "card_number",
        "cvv",
        "pan",
        "aadhaar",
        "account_number",
        "ifsc",
        "razorpay_key_secret",
        "cookie",
        "set-cookie",
        "session",
    }
)

PII_KEYS = frozenset({"email", "phone", "mobile", "address", "dob", "date_of_birth", "gstin"})

REDACTED = "[REDACTED]"
MAX_DEPTH = 8

_PAN = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
_AADHAAR = re.compile(r"\b[2-9][0-9]{3}[ -]?[0-9]{4}[ -]?[0-9]{4}\b")
_CARD = re.compile(r"\b(?:[0-9][ -]?){13,19}\b")
_EMAIL = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+")


def scrub_text(value: str) -> str:
    value = _BEARER.sub("Bearer " + REDACTED, value)
    value = _PAN.sub("[PAN]", value)
    value = _AADHAAR.sub("[AADHAAR]", value)
    value = _CARD.sub("[CARD]", value)
    return value


def mask_email(value: str) -> str:
    if "@" not in value:
        return REDACTED
    local, _, domain = value.partition("@")
    head = local[0] if local else "*"
    return f"{head}{'*' * max(1, len(local) - 1)}@{domain}"


def redact(value: Any, *, depth: int = 0, mask_pii: bool = True) -> Any:
    """Recursively redact secrets and (optionally) restricted PII from a payload."""
    if depth > MAX_DEPTH:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered in SECRET_KEYS or any(s in lowered for s in ("secret", "password", "token")):
                out[key] = REDACTED
            elif mask_pii and lowered in PII_KEYS:
                out[key] = (
                    mask_email(item) if lowered == "email" and isinstance(item, str) else REDACTED
                )
            else:
                out[key] = redact(item, depth=depth + 1, mask_pii=mask_pii)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(v, depth=depth + 1, mask_pii=mask_pii) for v in value][:200]
    if isinstance(value, str):
        text = scrub_text(value)
        return _EMAIL.sub(lambda m: mask_email(m.group()), text) if mask_pii else text
    return value
