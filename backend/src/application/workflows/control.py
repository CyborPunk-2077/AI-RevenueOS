"""Kill switches take effect in under five seconds at tenant, workflow and global scope."""

from __future__ import annotations

from typing import Any
from uuid import UUID

KILL_TTL_SECONDS = 86_400


async def engage_kill_switch(
    *, tenant_id: UUID, workflow_id: UUID | None = None, actor_id: UUID | None = None
) -> dict[str, Any]:
    from infrastructure.caching.redis import Cache, tenant_key

    scope = "workflow" if workflow_id else "tenant"
    key = tenant_key(str(tenant_id), "kill", scope, str(workflow_id or "all"))
    await Cache().set_json(key, {"engaged": True, "by": str(actor_id)}, KILL_TTL_SECONDS)
    return {"scope": scope, "engaged": True, "effective_within_seconds": 5}


async def is_killed(*, tenant_id: UUID, workflow_id: UUID | None = None) -> bool:
    """Global, tenant and workflow scopes are checked cheapest-first and short-circuit."""
    from infrastructure.caching.redis import Cache, global_key, tenant_key

    cache = Cache()
    scopes = [
        global_key("kill", "all"),
        tenant_key(str(tenant_id), "kill", "tenant", "all"),
    ]
    if workflow_id:
        scopes.append(tenant_key(str(tenant_id), "kill", "workflow", str(workflow_id)))

    for scope in scopes:
        if await cache.get_json(scope) is not None:
            return True
    return False


async def release_kill_switch(*, tenant_id: UUID, workflow_id: UUID | None = None) -> None:
    from infrastructure.caching.redis import Cache, tenant_key

    scope = "workflow" if workflow_id else "tenant"
    await Cache().delete(tenant_key(str(tenant_id), "kill", scope, str(workflow_id or "all")))
