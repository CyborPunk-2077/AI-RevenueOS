"""Health and version endpoints. Public health never exposes provider detail."""

from __future__ import annotations

import ipaddress
from typing import Any

from fastapi import APIRouter, Depends, Request, Response

from api.app.envelope import success
from api.app.settings import Settings, get_settings
from shared.exceptions import NotFound

router = APIRouter(tags=["health"])


class DependencyProbe:
    """Registry of dependency probes used by the readiness endpoint."""

    def __init__(self) -> None:
        self._probes: dict[str, Any] = {}

    def register(self, name: str, probe: Any, *, critical: bool = True) -> None:
        self._probes[name] = (probe, critical)

    async def run(self) -> tuple[dict[str, Any], bool]:
        results: dict[str, Any] = {}
        ready = True
        for name, (probe, critical) in self._probes.items():
            try:
                await probe()
                results[name] = {"status": "up", "critical": critical}
            except Exception as exc:
                results[name] = {
                    "status": "down",
                    "critical": critical,
                    "reason": type(exc).__name__,
                }
                if critical:
                    ready = False
        return results, ready


probes = DependencyProbe()


@router.get("/health", summary="Aggregate health")
async def health(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return success(
        {"status": "ok", "service": settings.service_name, "environment": settings.environment},
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/health/liveness", summary="Process liveness")
async def liveness(request: Request) -> dict[str, Any]:
    return success({"status": "alive"}, request_id=getattr(request.state, "correlation_id", None))


@router.get("/health/readiness", summary="Dependency readiness")
async def readiness(request: Request, response: Response) -> dict[str, Any]:
    checks, ready = await probes.run()
    degraded = any(c["status"] == "down" for c in checks.values())
    response.status_code = 200 if ready else 503
    return success(
        {
            "status": "ready" if ready else "not_ready",
            "degraded": degraded,
            "dependencies": checks,
        },
        request_id=getattr(request.state, "correlation_id", None),
    )


@router.get("/health/metrics", summary="Prometheus metrics (internal only)")
async def metrics(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    client = request.client.host if request.client else ""
    if not _ip_allowed(client, settings.metrics_allowed_cidrs):
        raise NotFound("Not found.")
    from infrastructure.monitoring.metrics import render_metrics

    body, content_type = render_metrics()
    return Response(content=body, media_type=content_type)


@router.get("/version", summary="Build version")
async def version(request: Request, settings: Settings = Depends(get_settings)) -> dict[str, Any]:
    return success(
        {"version": settings.release, "api_version": settings.api_version},
        request_id=getattr(request.state, "correlation_id", None),
    )


def _ip_allowed(client: str, cidrs: list[str]) -> bool:
    if not client:
        return False
    try:
        addr = ipaddress.ip_address(client)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False
