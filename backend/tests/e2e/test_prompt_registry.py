"""Prompt sync, evaluation, promotion and rollback with real PostgreSQL."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select

from api.deps.principal import Principal
from application.ai.prompt_registry import (
    evaluate_prompt_document,
    list_prompts,
    load_git_prompts,
    promote_prompt,
    record_evaluation,
    resolve_production_prompt,
    rollback_prompt,
    sync_git_prompts,
)
from domain.auth.permissions import Role, Scope, permissions_for
from infrastructure.caching.redis import get_redis
from infrastructure.database.models.ai import AiEvaluationRun, Prompt
from infrastructure.database.models.audit import AuditLog, EventOutbox
from infrastructure.database.session import tenant_session
from shared.exceptions import Forbidden

pytestmark = pytest.mark.postgres


def _platform(tenant_id: UUID) -> Principal:
    return Principal(
        user_id=uuid4(),
        tenant_id=tenant_id,
        tenant_slug="platform-ops",
        email="prompt-bot@example.invalid",
        name="Prompt CI",
        roles=("platform",),
        permissions=frozenset({"prompt:create", "prompt:read", "prompt:update"}),
        scope=Scope.GLOBAL,
        actor_type="platform",
        mfa_verified=True,
    )


def _document(task: str, version: int) -> dict[str, Any]:
    return next(
        item for item in load_git_prompts() if item["task"] == task and item["version"] == version
    )


async def _record(principal: Principal, task: str, version: int) -> dict[str, Any]:
    evidence = evaluate_prompt_document(_document(task, version))
    return await record_evaluation(
        principal,
        task=task,
        version=version,
        evaluation_set=str(evidence["evaluation_set"]),
        evaluation_version=int(evidence["evaluation_version"]),
        content_hash=str(evidence["content_hash"]),
        results=list(evidence["results"]),
        idempotency_key=f"eval-{task}-v{version}-{uuid4().hex}",
    )


async def test_prompt_lifecycle_is_evaluated_idempotent_and_audited(
    wired_engine: Any, seeded_tenants: Any
) -> None:
    tenant_a, _ = seeded_tenants
    principal = _platform(tenant_a)
    key = f"sync-{uuid4().hex}"
    synced = await sync_git_prompts(principal, idempotency_key=key)
    await get_redis().flushall()
    assert await sync_git_prompts(principal, idempotency_key=key) == synced
    assert synced["discovered"] == len(load_git_prompts())

    evaluation_v1 = await _record(principal, "chat", 1)
    production_v1 = await promote_prompt(
        principal,
        task="chat",
        version=1,
        evaluation_run_id=UUID(evaluation_v1["evaluation_run_id"]),
        idempotency_key=f"promote-v1-{uuid4().hex}",
    )
    assert production_v1["status"] == "production"
    runtime = await resolve_production_prompt(tenant_a, "chat")
    assert runtime is not None and runtime["prompt_version"] == 1

    evaluation_v2 = await _record(principal, "chat", 2)
    production_v2 = await promote_prompt(
        principal,
        task="chat",
        version=2,
        evaluation_run_id=UUID(evaluation_v2["evaluation_run_id"]),
        idempotency_key=f"promote-v2-{uuid4().hex}",
    )
    assert production_v2["status"] == "production"
    rolled_back = await rollback_prompt(
        principal,
        task="chat",
        target_version=1,
        idempotency_key=f"rollback-{uuid4().hex}",
    )
    assert rolled_back["status"] == "production" and rolled_back["version"] == 1

    metadata = await list_prompts(principal, task="chat")
    assert metadata and all(row["template_returned"] is False for row in metadata)
    assert "You are the AI RevenueOS copilot" not in repr(metadata)

    async with tenant_session(tenant_a) as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Prompt)
                .where(Prompt.task == "chat", Prompt.status == "production")
            )
            == 1
        )
        run_ids = {
            UUID(evaluation_v1["evaluation_run_id"]),
            UUID(evaluation_v2["evaluation_run_id"]),
        }
        assert (
            await session.scalar(
                select(func.count())
                .select_from(AiEvaluationRun)
                .where(AiEvaluationRun.id.in_(run_ids))
            )
            == 2
        )
        audited = await session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action.in_(("prompt.promoted", "prompt.rolled_back")),
                AuditLog.tenant_id == tenant_a,
            )
        )
        assert audited is not None and audited >= 3
        published = await session.scalar(
            select(func.count())
            .select_from(EventOutbox)
            .where(
                EventOutbox.event_type.in_(("prompt.promoted", "prompt.rolled_back")),
                EventOutbox.tenant_id == tenant_a,
            )
        )
        assert published is not None and published >= 3


async def test_prompt_mutations_reject_tenant_owners(
    wired_engine: Any, seeded_tenants: Any, principal_factory: Any
) -> None:
    tenant_a, _ = seeded_tenants
    owner = principal_factory(tenant_a, Role.OWNER)
    assert "prompt:create" in permissions_for([Role.OWNER])
    with pytest.raises(Forbidden, match="platform service principal"):
        await sync_git_prompts(owner, idempotency_key=f"owner-{uuid4().hex}")


async def test_prompt_promotion_rolls_back_when_audit_fails(
    wired_engine: Any,
    seeded_tenants: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_a, _ = seeded_tenants
    principal = _platform(tenant_a)
    await sync_git_prompts(principal, idempotency_key=f"sync-{uuid4().hex}")
    evaluation = await _record(principal, "classify", 1)

    def fail_audit(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr("application.audit.recorder.AuditRecorder.record", fail_audit)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await promote_prompt(
            principal,
            task="classify",
            version=1,
            evaluation_run_id=UUID(evaluation["evaluation_run_id"]),
            idempotency_key=f"promote-fail-{uuid4().hex}",
        )
    async with tenant_session(tenant_a) as session:
        row = await session.scalar(
            select(Prompt).where(Prompt.task == "classify", Prompt.version == 1)
        )
        assert row is not None and row.status == "draft"
