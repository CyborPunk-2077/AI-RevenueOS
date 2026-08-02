"""Versioned public API surface. All external routes are versioned; none are implicit."""

from __future__ import annotations

from fastapi import APIRouter

from api.app.settings import Settings
from api.v1 import (
    ai,
    analytics,
    auth,
    consents,
    crm,
    integrations,
    leads,
    meta,
    public,
    support,
    tenant,
    webhooks,
    workflows,
)


def build_v1_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    router.include_router(auth.router)
    router.include_router(crm.contacts_router)
    router.include_router(crm.accounts_router)
    router.include_router(crm.notes_router)
    router.include_router(crm.deals_router)
    router.include_router(crm.tasks_router)
    router.include_router(crm.conversations_router)
    router.include_router(crm.appointments_router)
    router.include_router(crm.files_router)
    router.include_router(crm.documents_router)
    router.include_router(analytics.router)
    router.include_router(meta.router)
    router.include_router(tenant.router)
    router.include_router(leads.router)
    router.include_router(ai.router)
    router.include_router(workflows.router)
    router.include_router(consents.router)
    router.include_router(integrations.router)
    router.include_router(support.router)
    router.include_router(public.router)
    router.include_router(webhooks.router)
    return router
