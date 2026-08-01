"""Redis client and tenant-namespaced cache. Redis is never the sole durable state."""

from __future__ import annotations

import json
from typing import Any

import redis.asyncio as aioredis

from infrastructure.logging.setup import get_logger
from shared.settings import Settings, get_settings

logger = get_logger("infra.cache")

_client: aioredis.Redis | None = None

TTL_TENANT_CONFIG = 300
TTL_PERMISSIONS = 600
TTL_DASHBOARD = 60
TTL_FEATURE_FLAGS = 120
TTL_PROMPT = 900
TTL_IDEMPOTENCY = 86_400


def get_redis(cfg: Settings | None = None) -> aioredis.Redis:
    global _client
    if _client is None:
        c = cfg or get_settings()
        _client = aioredis.from_url(
            c.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
            health_check_interval=30,
        )
    return _client


def set_redis(client: aioredis.Redis | None) -> None:
    """Test hook to inject fakeredis."""
    global _client
    _client = client


def tenant_key(tenant_id: str, *parts: str) -> str:
    """Every cache key is namespaced by tenant. Cross-tenant reads are impossible."""
    return "t:" + tenant_id + ":" + ":".join(parts)


def global_key(*parts: str) -> str:
    return "g:" + ":".join(parts)


class Cache:
    """Fail-open cache: a Redis outage bypasses cache but never changes correctness."""

    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client or get_redis()

    async def get_json(self, key: str) -> Any | None:
        try:
            raw = await self._client.get(key)
        except Exception as exc:
            logger.warning("cache_unavailable", operation="get", reason=type(exc).__name__)
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def set_json(self, key: str, value: Any, ttl: int) -> None:
        try:
            await self._client.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            logger.warning("cache_unavailable", operation="set", reason=type(exc).__name__)

    async def delete(self, *keys: str) -> None:
        if not keys:
            return
        try:
            await self._client.delete(*keys)
        except Exception as exc:
            logger.warning("cache_unavailable", operation="delete", reason=type(exc).__name__)

    async def invalidate_tenant(self, tenant_id: str) -> int:
        """Drop every cached entry for a tenant (used on switch, revoke and deletion)."""
        removed = 0
        try:
            async for key in self._client.scan_iter(match=f"t:{tenant_id}:*", count=500):
                await self._client.delete(key)
                removed += 1
        except Exception as exc:
            logger.warning("cache_unavailable", operation="invalidate", reason=type(exc).__name__)
        return removed


async def ping(cfg: Settings | None = None) -> None:
    """Readiness probe for the cache tier."""
    await get_redis(cfg).ping()
