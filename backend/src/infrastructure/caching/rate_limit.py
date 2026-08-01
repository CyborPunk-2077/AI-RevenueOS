"""Redis sliding-window rate limiting. Fails open on Redis outage but records it."""

from __future__ import annotations

import time
from dataclasses import dataclass

import redis.asyncio as aioredis

from infrastructure.caching.redis import get_redis
from infrastructure.logging.setup import get_logger

logger = get_logger("infra.ratelimit")

_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
local count = redis.call('ZCARD', key)
if count < limit then
  redis.call('ZADD', key, now, ARGV[4])
  redis.call('PEXPIRE', key, window)
  return {1, limit - count - 1, 0}
end
local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
local retry = window - (now - tonumber(oldest[2]))
return {0, 0, retry}
"""


@dataclass(frozen=True, slots=True)
class LimitPolicy:
    name: str
    limit: int
    window_seconds: int


@dataclass(frozen=True, slots=True)
class LimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int
    policy: str


# Canonical policy table from Authentication & Security.
POLICIES: dict[str, LimitPolicy] = {
    "login_ip": LimitPolicy("login_ip", 5, 900),
    "login_account": LimitPolicy("login_account", 20, 3600),
    "refresh_user": LimitPolicy("refresh_user", 10, 60),
    "google_ip": LimitPolicy("google_ip", 5, 60),
    "mfa_user": LimitPolicy("mfa_user", 5, 300),
    "password_reset_email": LimitPolicy("password_reset_email", 3, 3600),
    "api_user_second": LimitPolicy("api_user_second", 60, 1),
    "api_user_minute": LimitPolicy("api_user_minute", 600, 60),
    "api_user_hour": LimitPolicy("api_user_hour", 10_000, 3600),
    "inbox_read": LimitPolicy("inbox_read", 30, 1),
    "inbox_send": LimitPolicy("inbox_send", 10, 1),
    "socket_connect": LimitPolicy("socket_connect", 5, 60),
    "lead_bulk_tenant": LimitPolicy("lead_bulk_tenant", 10, 60),
    "contact_import_tenant": LimitPolicy("contact_import_tenant", 5, 3600),
    "export_user": LimitPolicy("export_user", 5, 60),
    "file_user": LimitPolicy("file_user", 30, 60),
    "developer_key": LimitPolicy("developer_key", 300, 60),
    "developer_key_paid": LimitPolicy("developer_key_paid", 3_000, 60),
    "ai_copilot_user": LimitPolicy("ai_copilot_user", 20, 60),
    "ai_qualify_tenant": LimitPolicy("ai_qualify_tenant", 30, 60),
    "ai_generate_user": LimitPolicy("ai_generate_user", 30, 60),
    "ai_summarize_user": LimitPolicy("ai_summarize_user", 20, 60),
    "public_form_ip": LimitPolicy("public_form_ip", 10, 60),
    "webchat_session_ip": LimitPolicy("webchat_session_ip", 5, 60),
}


class RateLimiter:
    def __init__(self, client: aioredis.Redis | None = None) -> None:
        self._client = client or get_redis()
        self._sha: str | None = None

    async def _eval(self, key: str, policy: LimitPolicy) -> LimitDecision:
        now_ms = int(time.time() * 1000)
        window_ms = policy.window_seconds * 1000
        member = f"{now_ms}-{time.perf_counter_ns()}"
        try:
            if self._sha is None:
                self._sha = await self._client.script_load(_SCRIPT)
            result = await self._client.evalsha(
                self._sha, 1, key, now_ms, window_ms, policy.limit, member
            )
        except Exception as exc:
            logger.warning("ratelimit_unavailable", policy=policy.name, reason=type(exc).__name__)
            return LimitDecision(True, policy.limit, 0, policy.name)
        allowed = bool(int(result[0]))
        return LimitDecision(
            allowed=allowed,
            remaining=int(result[1]),
            retry_after_seconds=max(1, int(int(result[2]) / 1000)) if not allowed else 0,
            policy=policy.name,
        )

    async def check(self, policy_name: str, subject: str) -> LimitDecision:
        policy = POLICIES[policy_name]
        return await self._eval(f"rl:{policy.name}:{subject}", policy)

    async def check_custom(self, policy: LimitPolicy, subject: str) -> LimitDecision:
        return await self._eval(f"rl:{policy.name}:{subject}", policy)
