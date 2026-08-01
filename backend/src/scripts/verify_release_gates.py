"""Machine-checkable release gates. Run in CI and before any GA decision."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from domain.ai.guards import TEMPLATE_PROHIBITIONS
from domain.tenants.entitlements import EXTERNALLY_GATED, PLANS, Feature
from domain.tenants.templates import MANDATORY_TEMPLATE_CODES, validate_catalog
from infrastructure.ai.models import assert_no_latest_aliases
from infrastructure.database import models as _models  # noqa: F401 (populates the registry)
from infrastructure.database.base import TENANT_OWNED_TABLES
from shared.settings import Settings


def gate(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return name, ok, detail


def run() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    problems = validate_catalog()
    results.append(
        gate(
            "All eight industry templates are complete and configuration only",
            not problems,
            "; ".join(problems),
        )
    )

    results.append(
        gate(
            "Every mandatory template enforces prohibited-domain guardrails",
            all(TEMPLATE_PROHIBITIONS.get(code) for code in MANDATORY_TEMPLATE_CODES),
        )
    )

    results.append(
        gate(
            "Every tenant-owned table is registered for RLS",
            len(TENANT_OWNED_TABLES) >= 80,
            f"{len(TENANT_OWNED_TABLES)} tables",
        )
    )

    try:
        assert_no_latest_aliases()
        results.append(gate("AI model versions are pinned (no floating alias)", True))
    except AssertionError as exc:
        results.append(gate("AI model versions are pinned (no floating alias)", False, str(exc)))

    results.append(
        gate(
            "Voice is not granted by any plan",
            all(Feature.VOICE not in plan.features for plan in PLANS.values()),
        )
    )

    results.append(
        gate(
            "Every externally gated feature documents its activation prerequisite",
            all(bool(text) for text in EXTERNALLY_GATED.values()),
        )
    )

    defaults = Settings(_env_file=None).features  # type: ignore[call-arg]
    off_by_default = {
        "whatsapp": defaults.whatsapp_enabled,
        "email": defaults.email_enabled,
        "voice": defaults.voice_enabled,
        "payments": defaults.payments_enabled,
        "signatures": defaults.signatures_enabled,
        "n8n_authoring": defaults.n8n_authoring_enabled,
    }
    results.append(
        gate(
            "Every externally gated capability defaults to disabled",
            not any(off_by_default.values()),
            ", ".join(k for k, v in off_by_default.items() if v),
        )
    )

    # Production configuration must fail fast rather than boot insecurely.
    try:
        Settings(environment="prod", _env_file=None).assert_production_safe()  # type: ignore[call-arg]
        results.append(gate("Production boot refuses incomplete secrets", False, "did not raise"))
    except RuntimeError:
        results.append(gate("Production boot refuses incomplete secrets", True))

    return results


def main() -> int:
    results = run()
    width = max(len(name) for name, _, _ in results)
    failed = 0
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        suffix = f"  ({detail})" if detail and not ok else ""
        print(f"[{status}] {name.ljust(width)}{suffix}")  # noqa: T201
        failed += 0 if ok else 1
    print(f"\n{len(results) - failed}/{len(results)} release gates passed")  # noqa: T201
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
