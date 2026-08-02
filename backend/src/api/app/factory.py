"""FastAPI application factory. Composition root for middleware, routers and DI."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from api.app.settings import Settings, get_settings
from api.health.router import router as health_router
from api.middleware.correlation import CorrelationMiddleware
from api.middleware.errors import register_exception_handlers
from api.middleware.security import (
    BodyLimitMiddleware,
    OriginEnforcementMiddleware,
    SecurityHeadersMiddleware,
)
from infrastructure.logging.setup import configure_logging, get_logger

logger = get_logger("api.app")

WEBHOOK_PREFIXES = ("/v1/webhooks/inbound", "/v1/public")


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or get_settings()
    configure_logging(level=cfg.log_level, json_output=cfg.log_json, service=cfg.service_name)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("api_startup", environment=cfg.environment, release=cfg.release)
        await _startup(app, cfg)
        try:
            yield
        finally:
            await _shutdown(app)
            logger.info("api_shutdown")

    app = FastAPI(
        title="AI RevenueOS API",
        version=cfg.release,
        description="Multi-tenant RevenueOS for Indian SMEs.",
        openapi_url="/v1/openapi.json",
        docs_url="/v1/docs" if not cfg.is_production else None,
        redoc_url=None,
        root_path=cfg.root_path,
        lifespan=lifespan,
    )
    app.state.settings = cfg
    from application.audit.denials import audit_authorization_denial

    app.state.authorization_denial_auditor = audit_authorization_denial

    app.add_middleware(SecurityHeadersMiddleware, hsts=cfg.environment in ("staging", "prod"))
    app.add_middleware(BodyLimitMiddleware, max_bytes=cfg.json_body_limit_bytes)
    app.add_middleware(
        OriginEnforcementMiddleware,
        allowed_origins=cfg.cors_allowed_origins,
        exempt_prefixes=WEBHOOK_PREFIXES,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "If-Match",
            "X-Request-ID",
            "X-CSRF-Token",
        ],
        expose_headers=["X-Request-ID", "ETag", "Retry-After", "RateLimit-Reset"],
        max_age=600,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=[*cfg.trusted_hosts, "*.airevenueos.io"]
    )
    app.add_middleware(CorrelationMiddleware)

    register_exception_handlers(app)
    app.include_router(health_router)
    _include_v1(app, cfg)
    return app


def _include_v1(app: FastAPI, cfg: Settings) -> None:
    """Mount the versioned API surface. Imported lazily to keep the shell importable."""
    from api.v1 import build_v1_router

    app.include_router(build_v1_router(cfg), prefix="/v1")


async def _startup(app: FastAPI, cfg: Settings) -> None:
    from api.health.router import probes
    from infrastructure.caching.redis import ping as redis_ping
    from infrastructure.database.session import get_engine
    from infrastructure.database.session import ping as database_ping

    app.state.engine = get_engine(cfg)

    async def db_probe() -> None:
        await database_ping(cfg)

    async def redis_probe() -> None:
        await redis_ping(cfg)

    probes.register("postgres", db_probe, critical=True)
    probes.register("redis", redis_probe, critical=False)


async def _shutdown(app: FastAPI) -> None:
    engine: Any = getattr(app.state, "engine", None)
    if engine is not None:
        await engine.dispose()
