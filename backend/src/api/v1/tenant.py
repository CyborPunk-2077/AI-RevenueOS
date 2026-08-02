"""Tenant read/update, usage, feature flags and onboarding state."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from api.app.envelope import success
from api.app.settings import Settings
from api.deps.idempotency import IdempotencyContext, idempotency
from api.deps.principal import CurrentPrincipal, get_app_settings, require_step_up
from api.v1.schemas import OnboardingPatch
from domain.tenants.entitlements import Feature, PlanCode, check_feature, get_plan
from domain.tenants.templates import apply_template

router = APIRouter(tags=["tenant"])


def _flag_state(settings: Settings) -> dict[str, bool]:
    flags = settings.features
    return {
        Feature.WHATSAPP.value: flags.whatsapp_enabled,
        Feature.EMAIL.value: flags.email_enabled,
        Feature.SMS.value: flags.sms_enabled,
        Feature.VOICE.value: flags.voice_enabled,
        Feature.PAYMENTS.value: flags.payments_enabled,
        Feature.AI_QUALIFICATION.value: flags.ai_enabled,
        Feature.AI_COPILOT.value: flags.ai_enabled,
        Feature.WORKFLOWS.value: flags.workflows_enabled,
        Feature.WEBCHAT.value: flags.webchat_enabled,
        Feature.SIGNATURES.value: flags.signatures_enabled,
    }


@router.get("/tenant", summary="Read the current tenant")
async def read_tenant(
    request: Request,
    principal: CurrentPrincipal,
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, Any]:
    principal.require("tenant", "read")
    return success(
        {
            "id": str(principal.tenant_id),
            "slug": principal.tenant_slug,
            "timezone": settings.default_timezone,
            "currency": settings.default_currency,
            "locale": settings.default_locale,
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/tenant/feature-flags", summary="Effective feature entitlement")
async def feature_flags(
    request: Request,
    principal: CurrentPrincipal,
    settings: Annotated[Settings, Depends(get_app_settings)],
    plan: str = "starter",
) -> dict[str, Any]:
    principal.require("tenant", "read")
    flags = _flag_state(settings)
    resolved: dict[str, Any] = {}
    for feature in Feature:
        decision = check_feature(
            PlanCode(plan) if plan in {p.value for p in PlanCode} else PlanCode.STARTER,
            feature,
            flag_enabled=flags.get(feature.value, True),
        )
        resolved[feature.value] = {
            "enabled": decision.allowed,
            "reason": decision.detail.get("reason") if not decision.allowed else None,
            "activation_prerequisite": decision.detail.get("activation_prerequisite"),
        }
    return success(
        {"plan": plan, "features": resolved},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/tenant/usage", summary="Usage against plan quotas")
async def tenant_usage(
    request: Request, principal: CurrentPrincipal, plan: str = "starter"
) -> dict[str, Any]:
    principal.require("tenant", "read")
    resolved = get_plan(plan if plan in {p.value for p in PlanCode} else "starter")
    return success(
        {
            "plan": resolved.code.value,
            "limits": {m.value: v for m, v in resolved.limits.items()},
            "api_rate_per_minute": resolved.api_rate_per_minute,
            "audit_retention_days": resolved.audit_retention_days,
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/tenant/export", summary="Request a tenant data export")
async def request_export(
    request: Request,
    principal: Annotated[Any, Depends(require_step_up("export.create"))],
) -> dict[str, Any]:
    principal.require("export", "create")
    from application.tenants.requests import request_tenant_export

    result = await request_tenant_export(tenant_id=principal.tenant_id, actor_id=principal.user_id)
    return success(
        result,
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/tenant/delete-request", summary="Owner-only delayed tenant deletion")
async def request_deletion(
    request: Request,
    principal: Annotated[Any, Depends(require_step_up("tenant.delete"))],
) -> dict[str, Any]:
    principal.require("tenant", "delete")
    from application.tenants.requests import request_tenant_deletion

    result = await request_tenant_deletion(
        tenant_id=principal.tenant_id, actor_id=principal.user_id
    )
    return success(
        result,
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/onboarding/apply-template", summary="Apply an industry template")
async def apply_industry_template(
    request: Request,
    principal: CurrentPrincipal,
    code: str,
) -> dict[str, Any]:
    from shared.exceptions import NotFound

    principal.require("tenant", "configure")
    try:
        applied = apply_template(code)
    except KeyError as exc:
        raise NotFound("Industry template not found.") from exc
    return success(applied.to_dict(), request_id=getattr(request.state, "correlation_id", None))


@router.get("/onboarding/state", summary="Read tenant onboarding progress")
async def read_onboarding(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    from application.tenants.onboarding import read_onboarding_state

    return success(
        await read_onboarding_state(principal),
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.patch("/onboarding/state", summary="Advance one onboarding step")
async def patch_onboarding(
    payload: OnboardingPatch,
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.tenants.onboarding import update_onboarding_step

    return success(
        await update_onboarding_step(
            principal,
            step=payload.step,
            status=payload.status,
            idempotency_key=idem.key,
        ),
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.post("/onboarding/complete", summary="Complete required onboarding")
async def complete_onboarding(
    request: Request,
    principal: CurrentPrincipal,
    idem: Annotated[IdempotencyContext, Depends(idempotency)],
) -> dict[str, Any]:
    from application.tenants.onboarding import finish_onboarding

    return success(
        await finish_onboarding(principal, idempotency_key=idem.key),
        request_id=getattr(request.state, "correlation_id", None),
    )
