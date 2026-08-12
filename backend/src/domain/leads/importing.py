"""CSV import policy: column mapping, row validation, and what a dry run reports.

Pure domain. No file I/O, no database - the caller hands in already-parsed rows.

An import is the one place a user can create thousands of records in a single
click, so the rules here are deliberately unforgiving:

**Nothing is written until the whole file has been judged.** `plan_import` returns
accepted and rejected rows together, so a run can be previewed. A partial import
that stops halfway through leaves the user reconciling by hand.

**A row that cannot be contacted is rejected, not repaired.** Guessing an email
from a name produces plausible-looking rubbish that nobody notices until a
campaign bounces.

**Duplicate detection inside the file matters as much as against the database.**
The same address twice in one spreadsheet is the most common way a CRM ends up
with twins on day one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Final

from shared.exceptions import ValidationError
from shared.utils.spreadsheet import neutralise_formula

MAX_ROWS: Final = 10_000
MAX_COLUMNS: Final = 80

#: Lead columns an import may target. Anything else has to go through `capture`,
#: which is free-form by design and is never interpreted as a lead attribute.
IMPORTABLE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "first_name",
        "last_name",
        "email",
        "phone",
        "source",
        "source_channel",
        "company",
        "title",
        "city",
        "notes",
        # Added for founder prospecting. A list of businesses to approach is not a
        # list of people: what the business does, where to read about it, and why
        # we think they have a problem worth a call are the columns actually
        # present in the sheets being imported.
        "website",
        "industry",
        "requirement",
    }
)

#: Mapped columns kept as descriptive context rather than lead attributes. They
#: live in `capture`, which is free-form and never interpreted as an identity.
CAPTURE_FIELDS: Final[frozenset[str]] = frozenset(
    {"company", "title", "city", "notes", "website", "industry", "requirement"}
)

REQUIRED_ONE_OF: Final[frozenset[str]] = frozenset({"email", "phone"})

#: Header spellings seen in real exports, normalised to our field names.
HEADER_ALIASES: Final[dict[str, str]] = {
    "first name": "first_name",
    "firstname": "first_name",
    "given name": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "surname": "last_name",
    "full name": "first_name",
    "name": "first_name",
    "email": "email",
    "email address": "email",
    "e-mail": "email",
    "mail": "email",
    "phone": "phone",
    "phone number": "phone",
    "mobile": "phone",
    "mobile number": "phone",
    "contact number": "phone",
    "company": "company",
    "organisation": "company",
    "organization": "company",
    "account": "company",
    "title": "title",
    "designation": "title",
    "job title": "title",
    "city": "city",
    "location": "city",
    "source": "source",
    "lead source": "source",
    "notes": "notes",
    "comments": "notes",
    # Founder prospecting spellings.
    "business": "company",
    "business name": "company",
    "shop name": "company",
    "firm": "company",
    "area": "city",
    "website": "website",
    "site": "website",
    "url": "website",
    "web": "website",
    "industry": "industry",
    "category": "industry",
    "business type": "industry",
    "sector": "industry",
    "requirement": "requirement",
    "pain": "requirement",
    "problem": "requirement",
    "reason": "requirement",
    "why": "requirement",
    "contact person": "first_name",
    "owner name": "first_name",
    "contact": "first_name",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]{2,}$")
_DIGITS = re.compile(r"\D")


@dataclass(frozen=True, slots=True)
class RejectedRow:
    row_number: int
    reasons: list[str]
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AcceptedRow:
    row_number: int
    values: dict[str, Any]
    capture: dict[str, Any]
    dedupe_value: str


@dataclass(slots=True)
class ImportPlan:
    accepted: list[AcceptedRow] = field(default_factory=list)
    rejected: list[RejectedRow] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.accepted) + len(self.rejected)

    def summary(self) -> dict[str, Any]:
        return {
            "total_rows": self.total,
            "accepted": len(self.accepted),
            "rejected": len(self.rejected),
            "rejections": [
                {"row": row.row_number, "reasons": row.reasons} for row in self.rejected[:100]
            ],
        }


def suggest_mapping(headers: list[str]) -> dict[str, str | None]:
    """Best-effort header to field mapping. The user confirms it; we never assume."""
    mapping: dict[str, str | None] = {}
    claimed: set[str] = set()
    for header in headers:
        key = str(header or "").strip().lower().replace("_", " ")
        target = HEADER_ALIASES.get(key)
        if target is None and key.replace(" ", "_") in IMPORTABLE_FIELDS:
            target = key.replace(" ", "_")
        if target in claimed:
            target = None
        if target is not None:
            claimed.add(target)
        mapping[str(header)] = target
    return mapping


def validate_mapping(mapping: dict[str, str | None]) -> dict[str, str]:
    """Reject a mapping before a single row is read."""
    problems: list[str] = []
    resolved: dict[str, str] = {}
    seen: set[str] = set()

    if len(mapping) > MAX_COLUMNS:
        raise ValidationError(
            f"A file may have at most {MAX_COLUMNS} columns.", details={"columns": len(mapping)}
        )

    for header, target in mapping.items():
        if target is None:
            continue
        if target not in IMPORTABLE_FIELDS:
            problems.append(f"{target!r} is not a field an import can set.")
            continue
        if target in seen:
            problems.append(f"Two columns are both mapped to {target!r}.")
            continue
        seen.add(target)
        resolved[header] = target

    if not (seen & REQUIRED_ONE_OF):
        problems.append("Map a column to email or phone; leads must be contactable.")
    # A founder importing businesses to approach often has no named contact yet.
    # Requiring one would make the common case unimportable, so the business name
    # is an acceptable identity instead - see `plan_import`, which falls back to it.
    if not (seen & {"first_name", "company"}):
        problems.append("Map a column to the contact person or the business name.")

    if problems:
        raise ValidationError("This column mapping is not usable.", details={"problems": problems})
    return resolved


def normalise_phone_digits(value: str) -> str:
    """Comparison form only. Storage-level normalisation lives in shared.utils.phone."""
    digits = _DIGITS.sub("", value)
    return digits[-10:] if len(digits) >= 10 else digits


def plan_import(
    rows: list[dict[str, Any]],
    mapping: dict[str, str],
    *,
    default_source: str = "csv_import",
) -> ImportPlan:
    """Judge every row up front. Nothing here writes anything."""
    if not rows:
        raise ValidationError("This file has no data rows.")
    if len(rows) > MAX_ROWS:
        raise ValidationError(
            f"An import may carry at most {MAX_ROWS} rows.", details={"rows": len(rows)}
        )

    plan = ImportPlan()
    seen_in_file: dict[str, int] = {}

    for index, raw in enumerate(rows):
        # Row 1 is the header, so the first data row is row 2 in the user's file.
        row_number = index + 2
        values: dict[str, Any] = {}
        capture: dict[str, Any] = {}
        reasons: list[str] = []

        for header, target in mapping.items():
            cell = str(raw.get(header, "") or "").strip()
            if not cell:
                continue
            if target in CAPTURE_FIELDS:
                capture[target] = neutralise_formula(cell[:500])
            else:
                values[target] = cell

        for header, cell in raw.items():
            if header not in mapping and str(cell or "").strip():
                capture.setdefault("extra", {})[str(header)[:60]] = neutralise_formula(
                    str(cell)[:500]
                )

        if not values.get("first_name") and capture.get("company"):
            # No named contact yet, which is the normal state of a prospecting
            # list. The business becomes the record's name, and the substitution
            # is recorded so nobody later mistakes it for a person.
            values["first_name"] = str(capture["company"])[:120]
            capture["name_is_business"] = True

        if not values.get("first_name"):
            reasons.append("no contact person and no business name")
        else:
            values["first_name"] = neutralise_formula(values["first_name"][:120])

        email = values.get("email", "")
        if email:
            email = email.lower()
            if not _EMAIL.match(email) or len(email) > 320:
                reasons.append(f"{email!r} is not a valid email address")
                email = ""
            else:
                values["email"] = email

        phone_digits = ""
        phone = values.get("phone", "")
        if phone:
            phone_digits = normalise_phone_digits(phone)
            if len(phone_digits) < 10:
                reasons.append(f"{phone!r} is not a usable phone number")
                values.pop("phone", None)
                phone_digits = ""
            else:
                values["phone"] = phone[:20]

        if not email and not phone_digits:
            reasons.append("no usable email or phone; this lead could not be contacted")

        values.setdefault("source", default_source)
        values["source"] = str(values["source"])[:80]

        dedupe_value = email or phone_digits
        if dedupe_value and dedupe_value in seen_in_file:
            reasons.append(f"duplicate of row {seen_in_file[dedupe_value]} in this file")

        if reasons:
            plan.rejected.append(RejectedRow(row_number=row_number, reasons=reasons, raw=raw))
            continue

        seen_in_file[dedupe_value] = row_number
        plan.accepted.append(
            AcceptedRow(
                row_number=row_number,
                values=values,
                capture=capture,
                dedupe_value=dedupe_value,
            )
        )

    return plan
