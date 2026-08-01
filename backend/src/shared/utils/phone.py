"""Indian-first phone normalisation. Internationalisation must not require redesign."""

from __future__ import annotations

import re

_NON_DIGIT = re.compile(r"[^0-9+]")
INDIA_CC = "91"
INDIA_MOBILE = re.compile(r"^[6-9][0-9]{9}$")


class InvalidPhone(ValueError):
    """Raised when a phone number cannot be normalised to E.164."""


def normalize_phone(raw: str, default_country: str = INDIA_CC) -> str:
    """Normalise to E.164. Accepts +91XXXXXXXXXX or a 10 digit number starting 6-9."""
    if raw is None:
        raise InvalidPhone("phone is required")
    cleaned = _NON_DIGIT.sub("", raw.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.startswith("+"):
        digits = cleaned[1:]
        if digits.startswith(INDIA_CC):
            national = digits[len(INDIA_CC) :]
            if not INDIA_MOBILE.match(national):
                raise InvalidPhone("Indian mobile numbers must be 10 digits starting 6-9")
            return f"+{INDIA_CC}{national}"
        if not (8 <= len(digits) <= 15) or not digits.isdigit():
            raise InvalidPhone("international numbers must be 8-15 digits")
        return f"+{digits}"
    if default_country == INDIA_CC:
        if cleaned.startswith("0"):
            cleaned = cleaned[1:]
        if cleaned.startswith(INDIA_CC) and len(cleaned) == 12:
            cleaned = cleaned[2:]
        if not INDIA_MOBILE.match(cleaned):
            raise InvalidPhone("Indian mobile numbers must be 10 digits starting 6-9")
        return f"+{INDIA_CC}{cleaned}"
    raise InvalidPhone("cannot normalise number without a country code")


def try_normalize_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        return normalize_phone(raw)
    except InvalidPhone:
        return None


def phone_last4(e164: str) -> str:
    return e164[-4:]


def mask_phone(e164: str) -> str:
    """Mask for P3 redaction: +91XXXXXX1234."""
    if len(e164) <= 5:
        return "*" * len(e164)
    return e164[:3] + "X" * (len(e164) - 7) + e164[-4:]
