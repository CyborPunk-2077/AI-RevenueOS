"""Validation for a capture form's field schema. Pure policy: no I/O, no ORM.

A form is the widest unauthenticated write surface the product has - anyone on the
internet can post to a published one - so its shape is validated here rather than
trusted from whatever the builder UI happened to send.

Two rules are worth stating because they are product decisions, not syntax:

**A form must capture a way to reach the person.** Email or phone, at least one,
required. A form that collects a name and a message produces leads nobody can
follow up, which looks like working software right up until the pipeline review.

**Field names are identifiers, not labels.** They become keys in the source event
payload and in dedupe, so they are constrained to snake_case ASCII. A label may
say anything; the name may not.
"""

from __future__ import annotations

import re
from typing import Any, Final

from shared.exceptions import ValidationError

FIELD_TYPES: Final[frozenset[str]] = frozenset(
    {
        "text",
        "textarea",
        "email",
        "phone",
        "number",
        "select",
        "multiselect",
        "checkbox",
        "date",
        "hidden",
    }
)

#: Names the capture pipeline already assigns meaning to.
CONTACT_FIELDS: Final[frozenset[str]] = frozenset({"email", "phone"})

RESERVED_NAMES: Final[frozenset[str]] = frozenset(
    {"id", "tenant_id", "owner_id", "status", "score", "created_at", "updated_at", "version"}
)

MAX_FIELDS: Final = 60
MAX_OPTIONS: Final = 200
_NAME = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def validate_form_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised schema, or raise with every problem found at once.

    Collecting all problems matters: a builder UI that surfaces one error per save
    turns a ten-field form into ten round trips.
    """
    problems: list[str] = []
    raw_fields = schema.get("fields")

    if not isinstance(raw_fields, list) or not raw_fields:
        raise ValidationError("A form needs at least one field.", details={"field": "fields"})
    if len(raw_fields) > MAX_FIELDS:
        raise ValidationError(
            f"A form may have at most {MAX_FIELDS} fields.", details={"count": len(raw_fields)}
        )

    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            problems.append(f"Field {index} is not an object.")
            continue

        name = str(raw.get("name", "")).strip()
        if not _NAME.match(name):
            problems.append(
                f"Field {index}: {name!r} is not a valid name. Use lower case letters, "
                "digits and underscores, starting with a letter."
            )
            continue
        if name in RESERVED_NAMES:
            problems.append(f"Field {index}: {name!r} is reserved by the platform.")
            continue
        if name in seen:
            problems.append(f"Field {index}: {name!r} appears more than once.")
            continue
        seen.add(name)

        field_type = str(raw.get("type", "text")).strip()
        if field_type not in FIELD_TYPES:
            problems.append(f"Field {name!r}: {field_type!r} is not a supported field type.")
            continue

        options = raw.get("options") or []
        if field_type in ("select", "multiselect"):
            if not isinstance(options, list) or not options:
                problems.append(f"Field {name!r}: a {field_type} needs options.")
                continue
            if len(options) > MAX_OPTIONS:
                problems.append(f"Field {name!r}: at most {MAX_OPTIONS} options.")
                continue
            options = [str(option)[:120] for option in options]
        else:
            options = []

        required = bool(raw.get("required", False))
        if field_type == "hidden" and required:
            # A hidden field the visitor cannot see, that blocks submission when
            # absent, is an invisible dead end.
            problems.append(f"Field {name!r}: a hidden field cannot be required.")
            continue

        normalised.append(
            {
                "name": name,
                "type": field_type,
                "label": str(raw.get("label") or name.replace("_", " ").title())[:150],
                "required": required,
                "options": options,
                "placeholder": str(raw.get("placeholder") or "")[:150] or None,
                "help_text": str(raw.get("help_text") or "")[:300] or None,
            }
        )

    if not problems and not (seen & CONTACT_FIELDS):
        problems.append(
            "A form must capture an email or a phone number, or the leads it "
            "creates cannot be contacted."
        )

    if problems:
        raise ValidationError("This form definition is not valid.", details={"problems": problems})

    return {
        "fields": normalised,
        "consent_text": str(schema.get("consent_text") or "")[:1000] or None,
        "submit_label": str(schema.get("submit_label") or "Submit")[:60],
        "success_message": str(schema.get("success_message") or "")[:500] or None,
    }


def validate_origins(origins: list[Any]) -> list[str]:
    """Origins are scheme+host+port, never paths, and never `*`.

    An embedded form posts cross-origin, so this list is the only thing standing
    between a published form and anyone framing it from their own page.
    """
    cleaned: list[str] = []
    problems: list[str] = []
    for raw in origins or []:
        origin = str(raw).strip().rstrip("/")
        if origin == "*":
            problems.append("`*` is not an allowed origin. List the sites explicitly.")
            continue
        if not origin.startswith(("https://", "http://localhost", "http://127.0.0.1")):
            problems.append(f"{origin!r} must be https, or localhost for development.")
            continue
        if origin.count("/") > 2:
            problems.append(f"{origin!r} looks like a URL. An origin has no path.")
            continue
        cleaned.append(origin)

    if problems:
        raise ValidationError("These origins are not valid.", details={"problems": problems})
    return cleaned
