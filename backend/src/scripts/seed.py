"""Seed reference data: plans, permissions and the industry template catalogue.

Idempotent. Safe to run on every deploy.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.dialects.postgresql import insert

from domain.auth.permissions import (
    ALL_PERMISSIONS,
    OWNER_ONLY,
    SENSITIVE_PERMISSIONS,
)
from domain.tenants.entitlements import plan_catalog
from domain.tenants.templates import load_catalog, validate_catalog
from infrastructure.database.models.reference import (
    FeatureFlag,
    IndustryTemplate,
    Permission,
    Plan,
)
from infrastructure.database.session import unscoped_session
from infrastructure.logging.setup import configure_logging, get_logger
from shared.utils.ids import uuid7

logger = get_logger("scripts.seed")

# Flags whose activation depends on an unresolved external decision gate.
GATED_FLAGS = {
    "whatsapp_enabled": "BSP/Cloud API mode, credential ownership and template approval",
    "email_enabled": "Email provider decision, commercial terms and sender domain ownership",
    "sms_enabled": "SMS provider decision and DLT registration",
    "voice_enabled": "Telecom provider, legal disclosure and recording-consent sign-off",
    "payments_enabled": "Razorpay commercial model and collections policy",
    "signatures_enabled": "Signature provider agreement",
    "n8n_authoring_enabled": "n8n hosting/licensing and named operational owner",
    "calendar_sync_enabled": "Google OAuth verification for the requested Calendar scope",
    "sso_enabled": "Identity provider agreement (Phase 3)",
}
SAFE_FLAGS = {
    "ai_enabled": "Provider-neutral; degrades to manual without credentials",
    "workflows_enabled": "Custom engine only; n8n never executes production workflows",
    "webchat_enabled": "First-party channel with origin restrictions",
    "pilot_cohort_enabled": "Controlled pilot cohort",
}


async def seed_plans() -> int:
    async with unscoped_session() as session:
        for entry in plan_catalog():
            await session.execute(
                insert(Plan)
                .values(
                    id=uuid7(),
                    code=entry["code"],
                    name=entry["name"],
                    features=dict.fromkeys(entry["features"], True),
                    limits=entry["limits"],
                    max_users=entry["limits"].get("users", 3),
                    max_leads=entry["limits"].get("leads", 1000),
                    price_inr=entry["price_inr"],
                    sort=entry["sort"],
                    is_active=True,
                )
                .on_conflict_do_update(
                    index_elements=[Plan.code],
                    set_={
                        "features": dict.fromkeys(entry["features"], True),
                        "limits": entry["limits"],
                        "price_inr": entry["price_inr"],
                    },
                )
            )
        return len(plan_catalog())


async def seed_permissions() -> int:
    async with unscoped_session() as session:
        for code in sorted(ALL_PERMISSIONS):
            resource, action = code.split(":", 1)
            await session.execute(
                insert(Permission)
                .values(
                    id=uuid7(),
                    code=code,
                    resource=resource,
                    action=action,
                    is_owner_only=code in OWNER_ONLY,
                    is_sensitive=code in SENSITIVE_PERMISSIONS,
                )
                .on_conflict_do_nothing(index_elements=[Permission.code])
            )
        return len(ALL_PERMISSIONS)


async def seed_feature_flags() -> int:
    async with unscoped_session() as session:
        for code, prerequisite in {**GATED_FLAGS, **SAFE_FLAGS}.items():
            gated = code in GATED_FLAGS
            await session.execute(
                insert(FeatureFlag)
                .values(
                    id=uuid7(),
                    code=code,
                    description=prerequisite,
                    default_enabled=not gated,
                    requires_external_gate=gated,
                    activation_prerequisite=prerequisite if gated else None,
                )
                .on_conflict_do_update(
                    index_elements=[FeatureFlag.code],
                    set_={
                        "requires_external_gate": gated,
                        "activation_prerequisite": prerequisite if gated else None,
                    },
                )
            )
        return len(GATED_FLAGS) + len(SAFE_FLAGS)


async def seed_industry_templates() -> int:
    problems = validate_catalog()
    if problems:
        raise SystemExit(f"industry template catalogue is invalid: {problems}")

    catalog = load_catalog()
    async with unscoped_session() as session:
        for code, template in catalog.items():
            await session.execute(
                insert(IndustryTemplate)
                .values(
                    id=uuid7(),
                    code=code,
                    version=template["version"],
                    name=template["name"],
                    terminology=template["terminology"],
                    lead_schema=template["lead_schema"],
                    qualification_rubric=template["qualification_rubric"],
                    pipeline_stages=template["pipeline_stages"],
                    message_templates=template["message_templates"],
                    document_templates=template["document_templates"],
                    workflow_recipes=template["workflow_recipes"],
                    business_hours=template["business_hours"],
                    dashboard_presets=template["dashboard_presets"],
                    prohibited_ai_rules=template["prohibited_ai_rules"],
                    consent_copy=template["consent_copy"],
                    active=True,
                )
                .on_conflict_do_update(
                    index_elements=[IndustryTemplate.code, IndustryTemplate.version],
                    set_={
                        "prohibited_ai_rules": template["prohibited_ai_rules"],
                        "pipeline_stages": template["pipeline_stages"],
                    },
                )
            )
        return len(catalog)


async def main() -> None:
    configure_logging(json_output=False)
    plans = await seed_plans()
    permissions = await seed_permissions()
    flags = await seed_feature_flags()
    templates = await seed_industry_templates()
    logger.info(
        "seed_complete",
        plans=plans,
        permissions=permissions,
        feature_flags=flags,
        industry_templates=templates,
    )


if __name__ == "__main__":
    asyncio.run(main())
