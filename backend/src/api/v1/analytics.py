"""Tenant-scoped analytics and private export-intent endpoints."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request, status

from api.app.envelope import success
from api.app.settings import Settings
from api.deps.principal import (
    CurrentPrincipal,
    get_app_settings,
    require_step_up,
)
from shared.utils.timeutil import utcnow

router = APIRouter(prefix="/analytics", tags=["analytics"])


def _request_id(request: Request) -> str | None:
    return getattr(request.state, "correlation_id", None)


def _days(start: date | None, end: date | None, settings: Settings) -> tuple[date, date]:
    resolved_end = end or utcnow().astimezone(ZoneInfo(settings.default_timezone)).date()
    return start or (resolved_end - timedelta(days=29)), resolved_end


@router.get("/dashboard", summary="Read scoped funnel and revenue analytics")
async def dashboard(
    request: Request,
    principal: CurrentPrincipal,
    settings: Annotated[Settings, Depends(get_app_settings)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    principal.require("analytics", "read")
    from application.analytics.service import AnalyticsService

    start_day, end_day = _days(start, end, settings)
    data = await AnalyticsService.for_principal(principal).dashboard(
        start_day, end_day, timezone=settings.default_timezone
    )
    return success(data, request_id=_request_id(request))


@router.post(
    "/exports",
    status_code=status.HTTP_201_CREATED,
    summary="Record an analytics export intent",
)
async def request_export(
    request: Request,
    principal: Annotated[Any, Depends(require_step_up("export.create"))],
    settings: Annotated[Settings, Depends(get_app_settings)],
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
) -> dict[str, Any]:
    principal.require("analytics", "export")
    from application.analytics.service import AnalyticsService

    start_day, end_day = _days(start, end, settings)
    storage_ready = bool(
        settings.features.storage_enabled and not settings.storage_configuration_issues()
    )
    export = await AnalyticsService.for_principal(principal).request_export(
        start_day, end_day, storage_ready=storage_ready
    )
    return success(export, request_id=_request_id(request))


@router.get("/exports/{export_id}", summary="Read a requested analytics export")
async def read_export(
    export_id: UUID, request: Request, principal: CurrentPrincipal
) -> dict[str, Any]:
    principal.require("export", "read")
    from application.analytics.service import AnalyticsService

    export = await AnalyticsService.for_principal(principal).get_export(export_id)
    return success(export, request_id=_request_id(request))
