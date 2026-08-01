"""Text normalisation used for dedupe keys, slugs and canonical hashing."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from typing import Any

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_WS = re.compile(r"\s+")
RESERVED_SLUGS = frozenset(
    {
        "api",
        "app",
        "www",
        "admin",
        "platform",
        "support",
        "status",
        "sandbox",
        "staging",
        "dev",
        "mail",
        "static",
        "assets",
        "public",
        "internal",
    }
)


def nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def slugify(value: str, *, max_length: int = 63) -> str:
    base = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    slug = _SLUG_STRIP.sub("-", base).strip("-")[:max_length].strip("-")
    if not slug:
        raise ValueError("value produced an empty slug")
    return slug


def is_reserved_slug(slug: str) -> bool:
    return slug in RESERVED_SLUGS


def normalize_email(value: str) -> str:
    email = nfc(value).strip().lower()
    if email.count("@") != 1 or email.startswith("@") or email.endswith("@"):
        raise ValueError("invalid email address")
    return email


def normalize_name_key(value: str) -> str:
    """Aggressive normalisation used only for duplicate candidate matching."""
    base = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return _WS.sub(" ", _SLUG_STRIP.sub(" ", base)).strip()


def canonical_json(value: Any) -> str:
    """Deterministic JSON: sorted keys, no insignificant whitespace, NFC strings."""

    def norm(node: Any) -> Any:
        if isinstance(node, str):
            return nfc(node)
        if isinstance(node, dict):
            return {
                nfc(str(k)): norm(v) for k, v in sorted(node.items(), key=lambda kv: str(kv[0]))
            }
        if isinstance(node, (list, tuple)):
            return [norm(v) for v in node]
        if isinstance(node, float) and node.is_integer():
            return int(node)
        return node

    return json.dumps(norm(value), separators=(",", ":"), ensure_ascii=False, sort_keys=True)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def truncate(value: str, limit: int, suffix: str = "...") -> str:
    return value if len(value) <= limit else value[: max(0, limit - len(suffix))] + suffix
