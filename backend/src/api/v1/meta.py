"""Plans, permissions, feature flags and template catalogue."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.app.envelope import success
from api.deps.principal import CurrentPrincipal
from domain.auth.permissions import ALL_PERMISSIONS, OWNER_ONLY, SENSITIVE_PERMISSIONS
from domain.tenants.entitlements import plan_catalog
from domain.tenants.templates import available_codes, get_template

router = APIRouter(tags=["meta"])


@router.get("/plans", summary="List available plans")
async def list_plans(request: Request) -> dict[str, Any]:
    return success(
        {"plans": plan_catalog()},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/permissions", summary="List permission catalogue")
async def list_permissions(request: Request, principal: CurrentPrincipal) -> dict[str, Any]:
    principal.require("role", "read")
    return success(
        {
            "permissions": [
                {
                    "code": code,
                    "resource": code.split(":")[0],
                    "action": code.split(":")[1],
                    "owner_only": code in OWNER_ONLY,
                    "sensitive": code in SENSITIVE_PERMISSIONS,
                }
                for code in sorted(ALL_PERMISSIONS)
            ]
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/industry-templates", summary="List industry templates")
async def list_templates(request: Request) -> dict[str, Any]:
    catalog = []
    for code in available_codes():
        template = get_template(code)
        catalog.append(
            {
                "code": code,
                "name": template["name"],
                "version": template["version"],
                "terminology": template["terminology"],
                "pipeline_stages": [s["name"] for s in template["pipeline_stages"]],
                "prohibited_ai_rules": template["prohibited_ai_rules"],
            }
        )
    return success(
        {"templates": catalog}, request_id=getattr(request.state, "correlation_id", None)
    )


@router.get("/industry-templates/{code}", summary="Read one industry template")
async def read_template(code: str, request: Request) -> dict[str, Any]:
    from shared.exceptions import NotFound

    try:
        template = get_template(code)
    except KeyError as exc:
        raise NotFound("Industry template not found.") from exc
    return success(template, request_id=getattr(request.state, "correlation_id", None))
