"""Plan entitlements, quotas and feature gating.

Enforcement must be identical in the UI, the API, workers and billing/metering, so
every surface calls this one module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

UNLIMITED = -1


class PlanCode(StrEnum):
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


class Feature(StrEnum):
    WHATSAPP = "whatsapp"
    EMAIL = "email"
    SMS = "sms"
    VOICE = "voice"
    WEBCHAT = "webchat"
    AI_QUALIFICATION = "ai_qualification"
    AI_COPILOT = "ai_copilot"
    AI_RAG = "ai_rag"
    WORKFLOWS = "workflows"
    WORKFLOW_APPROVALS = "workflow_approvals"
    APPOINTMENTS = "appointments"
    DOCUMENTS = "documents"
    SIGNATURES = "signatures"
    PAYMENTS = "payments"
    CUSTOM_FIELDS = "custom_fields"
    CUSTOM_ROLES = "custom_roles"
    ANALYTICS_CUSTOM = "analytics_custom"
    DEVELOPER_API = "developer_api"
    OUTBOUND_WEBHOOKS = "outbound_webhooks"
    SSO = "sso"
    AUDIT_EXPORT = "audit_export"
    MULTI_BRANCH = "multi_branch"


class Meter(StrEnum):
    CONTACTS = "contacts"
    LEADS = "leads"
    USERS = "users"
    STORAGE_BYTES = "storage_bytes"
    AI_CALLS_MONTHLY = "ai_calls_monthly"
    AI_TOKENS_MONTHLY = "ai_tokens_monthly"
    ACTIVE_WORKFLOWS = "active_workflows"
    EMAIL_DAILY = "email_daily"
    SMS_DAILY = "sms_daily"
    WEBHOOK_DESTINATIONS = "webhook_destinations"
    API_KEYS = "api_keys"
    EXPORTS_DAILY = "exports_daily"


GB = 1024**3


@dataclass(frozen=True, slots=True)
class Plan:
    code: PlanCode
    name: str
    price_inr: int
    features: frozenset[Feature]
    limits: dict[Meter, int]
    api_rate_per_minute: int
    upload_limit_bytes: int
    import_batch_limit: int
    audit_retention_days: int
    ai_token_budget_monthly: int
    sort: int = 0


_COMMON = frozenset(
    {
        Feature.WEBCHAT,
        Feature.AI_QUALIFICATION,
        Feature.WORKFLOWS,
        Feature.APPOINTMENTS,
        Feature.DOCUMENTS,
    }
)

PLANS: dict[PlanCode, Plan] = {
    PlanCode.STARTER: Plan(
        code=PlanCode.STARTER,
        name="Starter",
        price_inr=1_499,
        features=_COMMON | {Feature.WHATSAPP},
        limits={
            Meter.CONTACTS: 1_000,
            Meter.LEADS: 1_000,
            Meter.USERS: 3,
            Meter.STORAGE_BYTES: 5 * GB,
            Meter.AI_CALLS_MONTHLY: 100,
            Meter.AI_TOKENS_MONTHLY: 1_000_000,
            Meter.ACTIVE_WORKFLOWS: 5,
            Meter.EMAIL_DAILY: 200,
            Meter.SMS_DAILY: 50,
            Meter.WEBHOOK_DESTINATIONS: 3,
            Meter.API_KEYS: 2,
            Meter.EXPORTS_DAILY: 5,
        },
        api_rate_per_minute=300,
        upload_limit_bytes=25 * 1024 * 1024,
        import_batch_limit=1_000,
        audit_retention_days=90,
        ai_token_budget_monthly=1_000_000,
        sort=1,
    ),
    PlanCode.GROWTH: Plan(
        code=PlanCode.GROWTH,
        name="Growth",
        price_inr=4_999,
        features=_COMMON
        | {
            Feature.WHATSAPP,
            Feature.EMAIL,
            Feature.SMS,
            Feature.AI_COPILOT,
            Feature.AI_RAG,
            Feature.WORKFLOW_APPROVALS,
            Feature.SIGNATURES,
            Feature.PAYMENTS,
            Feature.CUSTOM_FIELDS,
            Feature.CUSTOM_ROLES,
            Feature.DEVELOPER_API,
            Feature.OUTBOUND_WEBHOOKS,
            Feature.MULTI_BRANCH,
        },
        limits={
            Meter.CONTACTS: 10_000,
            Meter.LEADS: 10_000,
            Meter.USERS: 15,
            Meter.STORAGE_BYTES: 50 * GB,
            Meter.AI_CALLS_MONTHLY: 1_000,
            Meter.AI_TOKENS_MONTHLY: 5_000_000,
            Meter.ACTIVE_WORKFLOWS: 25,
            Meter.EMAIL_DAILY: 2_000,
            Meter.SMS_DAILY: 500,
            Meter.WEBHOOK_DESTINATIONS: 15,
            Meter.API_KEYS: 10,
            Meter.EXPORTS_DAILY: 25,
        },
        api_rate_per_minute=1_000,
        upload_limit_bytes=100 * 1024 * 1024,
        import_batch_limit=5_000,
        audit_retention_days=365,
        ai_token_budget_monthly=5_000_000,
        sort=2,
    ),
    PlanCode.ENTERPRISE: Plan(
        code=PlanCode.ENTERPRISE,
        name="Enterprise",
        price_inr=14_999,
        features=frozenset(Feature) - {Feature.VOICE},  # voice stays externally gated
        limits={
            Meter.CONTACTS: UNLIMITED,
            Meter.LEADS: UNLIMITED,
            Meter.USERS: UNLIMITED,
            Meter.STORAGE_BYTES: 500 * GB,
            Meter.AI_CALLS_MONTHLY: 10_000,
            Meter.AI_TOKENS_MONTHLY: 20_000_000,
            Meter.ACTIVE_WORKFLOWS: 100,
            Meter.EMAIL_DAILY: 20_000,
            Meter.SMS_DAILY: 5_000,
            Meter.WEBHOOK_DESTINATIONS: 50,
            Meter.API_KEYS: 50,
            Meter.EXPORTS_DAILY: 100,
        },
        api_rate_per_minute=5_000,
        upload_limit_bytes=500 * 1024 * 1024,
        import_batch_limit=50_000,
        audit_retention_days=2_555,
        ai_token_budget_monthly=20_000_000,
        sort=3,
    ),
}

# Features that additionally require an unresolved external gate to be cleared.
EXTERNALLY_GATED: dict[Feature, str] = {
    Feature.WHATSAPP: "BSP or Cloud API account, credential ownership and template approval",
    Feature.EMAIL: "email provider selection, commercial terms and sender domain ownership",
    Feature.SMS: "SMS provider selection and DLT registration",
    Feature.VOICE: "telecom provider, recording/consent disclosure and legal sign-off",
    Feature.PAYMENTS: "Razorpay commercial model and collections policy",
    Feature.SIGNATURES: "signature provider agreement",
    Feature.SSO: "identity provider agreement (Phase 3)",
}


@dataclass(frozen=True, slots=True)
class EntitlementDecision:
    allowed: bool
    code: str | None = None
    message: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


def get_plan(code: PlanCode | str) -> Plan:
    return PLANS[PlanCode(code)]


def check_feature(
    plan_code: PlanCode | str,
    feature: Feature | str,
    *,
    flag_enabled: bool = True,
    tenant_override: bool | None = None,
) -> EntitlementDecision:
    """Plan grant AND runtime flag must both hold. Failure is explicit, never silent."""
    plan = get_plan(plan_code)
    feat = Feature(feature)

    if tenant_override is False:
        return EntitlementDecision(
            False,
            "FEATURE_NOT_AVAILABLE",
            "This feature is disabled for your organisation.",
            {"feature": feat.value, "reason": "tenant_override"},
        )
    if feat not in plan.features and tenant_override is not True:
        gate = EXTERNALLY_GATED.get(feat)
        return EntitlementDecision(
            False,
            "FEATURE_NOT_AVAILABLE",
            f"{feat.value.replace('_', ' ').title()} is not included in the {plan.name} plan.",
            {
                "feature": feat.value,
                "plan": plan.code.value,
                # An externally gated capability cannot be unlocked by an upgrade alone.
                "upgrade_available": gate is None,
                "reason": "external_activation_pending" if gate else "plan_excluded",
                "activation_prerequisite": gate,
            },
        )
    if not flag_enabled:
        gate = EXTERNALLY_GATED.get(feat)
        return EntitlementDecision(
            False,
            "FEATURE_NOT_AVAILABLE",
            f"{feat.value.replace('_', ' ').title()} is not yet activated for this environment.",
            {
                "feature": feat.value,
                "reason": "external_activation_pending",
                "activation_prerequisite": gate,
            },
        )
    return EntitlementDecision(True)


def check_quota(
    plan_code: PlanCode | str,
    meter: Meter | str,
    *,
    current: int,
    requested: int = 1,
    override_limit: int | None = None,
) -> EntitlementDecision:
    plan = get_plan(plan_code)
    key = Meter(meter)
    limit = override_limit if override_limit is not None else plan.limits.get(key, UNLIMITED)
    if limit == UNLIMITED:
        return EntitlementDecision(True, detail={"limit": "unlimited"})
    projected = current + requested
    if projected > limit:
        return EntitlementDecision(
            False,
            "QUOTA_EXCEEDED",
            f"The {plan.name} plan allows {limit:,} {key.value.replace('_', ' ')}.",
            {"meter": key.value, "limit": limit, "current": current, "requested": requested},
        )
    return EntitlementDecision(
        True,
        detail={"limit": limit, "remaining": limit - projected, "warn": projected >= limit * 0.8},
    )


def quota_warning_threshold(current: int, limit: int) -> bool:
    """Emit a `system.quota_warning` event at 80% consumption."""
    return limit != UNLIMITED and limit > 0 and current >= limit * 0.8


def plan_catalog() -> list[dict[str, Any]]:
    return [
        {
            "code": plan.code.value,
            "name": plan.name,
            "price_inr": plan.price_inr,
            "sort": plan.sort,
            "features": sorted(f.value for f in plan.features),
            "limits": {m.value: v for m, v in plan.limits.items()},
            "api_rate_per_minute": plan.api_rate_per_minute,
            "upload_limit_bytes": plan.upload_limit_bytes,
            "import_batch_limit": plan.import_batch_limit,
            "audit_retention_days": plan.audit_retention_days,
        }
        for plan in sorted(PLANS.values(), key=lambda p: p.sort)
    ]
