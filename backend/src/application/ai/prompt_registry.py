"""Git-backed prompt registry, evaluation evidence, promotion and rollback."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

import yaml
from sqlalchemy import select

from application.idempotency import hash_payload, reserve_idempotency
from domain.auth.permissions import Scope
from domain.base import DomainEvent
from domain.events.catalog import (
    PROMPT_EVALUATED,
    PROMPT_PROMOTED,
    PROMPT_ROLLED_BACK,
    PROMPT_SYNCED,
)
from infrastructure.ai.models import Task
from shared.exceptions import Conflict, Forbidden, NotFound, ValidationError
from shared.utils.ids import uuid7
from shared.utils.text import canonical_json
from shared.utils.timeutil import utcnow

def _default_prompt_root() -> Path:
    """Where the versioned prompt files live.

    Counting four directories up finds `<repo>/prompts` from a source checkout.
    That is the wrong answer inside the API container, which mounts `backend/` at
    `/app` and leaves the rest of the repository outside - the count lands on `/`
    and the registry then reports that no prompts exist at all. `PROMPT_ROOT`
    exists so the deployment can state the location instead of the layout being
    inferred, which is what compose now does.
    """
    override = os.environ.get("PROMPT_ROOT")
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[4] / "prompts"


PROMPT_ROOT = _default_prompt_root()


def _require_platform(principal: Any, action: str) -> None:
    principal.require("prompt", action)
    if principal.actor_type != "platform" or principal.scope is not Scope.GLOBAL:
        raise Forbidden("Prompt mutations require a global platform service principal.")


def _load_yaml(path: Path) -> dict[str, Any]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValidationError(f"Prompt file must contain an object: {path}")
    return dict(raw)


def load_git_prompts(root: Path | None = None) -> list[dict[str, Any]]:
    """Load and validate immutable `prompts/<task>/v<n>.yaml` definitions."""
    base = root or PROMPT_ROOT
    documents: list[dict[str, Any]] = []
    valid_tasks = {task.value for task in Task}
    for path in sorted(base.glob("*/v*.yaml")):
        if not path.stem.startswith("v") or not path.stem[1:].isdigit():
            continue
        document = _load_yaml(path)
        task = str(document.get("task", ""))
        version = int(document.get("version", 0))
        if task != path.parent.name or task not in valid_tasks:
            raise ValidationError(f"Prompt task does not match its directory: {path}")
        if version != int(path.stem[1:]) or version < 1:
            raise ValidationError(f"Prompt version does not match its filename: {path}")
        template = document.get("template")
        if not isinstance(template, str) or len(template.strip()) < 20:
            raise ValidationError(f"Prompt template is missing or too short: {path}")
        for field_name, expected in (
            ("variables", list),
            ("response_schema", dict),
            ("examples", list),
            ("model_config", dict),
            ("evaluation", dict),
        ):
            if not isinstance(document.get(field_name), expected):
                raise ValidationError(f"Prompt {field_name} has the wrong type: {path}")
        evaluation = document["evaluation"]
        if not isinstance(evaluation.get("cases"), list) or not evaluation["cases"]:
            raise ValidationError(f"Prompt evaluation needs at least one gold case: {path}")
        immutable = {
            "task": task,
            "version": version,
            "template": template.strip(),
            "variables": document["variables"],
            "response_schema": document["response_schema"],
            "examples": document["examples"],
            "model_config": document["model_config"],
            "changelog": str(document.get("changelog", "")),
            "evaluation": evaluation,
            "source": path.relative_to(base.parent).as_posix(),
        }
        immutable["content_hash"] = hash_payload(immutable)
        documents.append(immutable)
    if not documents:
        raise ValidationError(f"No versioned prompt files were found under {base}.")
    return documents


def evaluate_prompt_document(document: dict[str, Any]) -> dict[str, Any]:
    """Run deterministic prompt-contract and guard gold cases without a provider call."""
    from domain.ai.guards import scan_input

    results: list[dict[str, Any]] = []
    template = str(document["template"])
    for index, case in enumerate(document["evaluation"]["cases"]):
        if not isinstance(case, dict):
            raise ValidationError("Evaluation cases must be objects.")
        case_id = str(case.get("id") or f"case-{index + 1}")
        kind = str(case.get("kind", "prompt_contract"))
        passed = False
        detail = ""
        if kind == "prompt_contract":
            expected = [str(item) for item in case.get("expected_fragments", [])]
            forbidden = [str(item) for item in case.get("forbidden_fragments", [])]
            passed = (
                bool(expected)
                and all(item in template for item in expected)
                and not any(item in template for item in forbidden)
            )
            detail = "template contract satisfied" if passed else "template contract failed"
        elif kind == "input_guard":
            guard = scan_input(str(case.get("input", "")))
            expected_action = str(case.get("expected_action", "allow"))
            actual = "block" if guard.blocked else "allow"
            passed = actual == expected_action
            detail = f"expected {expected_action}; observed {actual}"
        else:
            raise ValidationError(f"Unsupported evaluation case kind: {kind}")
        results.append({"case_id": case_id, "passed": passed, "detail": detail})
    score = sum(1 for item in results if item["passed"]) / len(results)
    threshold = float(document["evaluation"].get("threshold", 0.85))
    return {
        "task": document["task"],
        "version": document["version"],
        "content_hash": document["content_hash"],
        "evaluation_set": str(document["evaluation"].get("name", "baseline")),
        "evaluation_version": int(document["evaluation"].get("version", 1)),
        "metric": str(document["evaluation"].get("metric", "contract_pass_rate")),
        "threshold": threshold,
        "score": score,
        "passed": score >= threshold,
        "results": results,
        "provider_called": False,
    }


def _serialize_prompt(row: Any) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "task": row.task,
        "version": row.version,
        "status": row.status,
        "variables": list(row.variables or []),
        "response_schema": dict(row.response_schema or {}),
        "model_config": dict(row.model_config_json or {}),
        "changelog": row.changelog,
        "content_hash": row.content_hash,
        "promoted_at": row.promoted_at.isoformat() if row.promoted_at else None,
        "evaluation_run_id": str(row.evaluation_run_id) if row.evaluation_run_id else None,
        "template_returned": False,
    }


async def list_prompts(principal: Any, *, task: str | None = None) -> list[dict[str, Any]]:
    principal.require("prompt", "read")
    from infrastructure.database.models.ai import Prompt
    from infrastructure.database.session import tenant_session

    async with tenant_session(principal.tenant_id) as session:
        statement = select(Prompt).order_by(Prompt.task, Prompt.version.desc())
        if task:
            statement = statement.where(Prompt.task == task)
        rows = (await session.execute(statement)).scalars().all()
        return [_serialize_prompt(row) for row in rows]


async def sync_git_prompts(principal: Any, *, idempotency_key: str | None) -> dict[str, Any]:
    _require_platform(principal, "create")
    documents = load_git_prompts()
    manifest_hash = hash_payload(
        [
            {"task": item["task"], "version": item["version"], "hash": item["content_hash"]}
            for item in documents
        ]
    )
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.ai import AiEvaluationSet, Prompt
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    created: list[str] = []
    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope="prompt.registry.sync",
            key=idempotency_key,
            request_hash=manifest_hash,
        )
        if reservation.replay is not None:
            return reservation.replay
        for document in documents:
            prompt = await uow.session.scalar(
                select(Prompt).where(
                    Prompt.task == document["task"], Prompt.version == document["version"]
                )
            )
            if prompt is not None and prompt.content_hash != document["content_hash"]:
                raise Conflict(
                    "A committed prompt version is immutable; author a new version.",
                    details={"task": document["task"], "version": document["version"]},
                )
            if prompt is None:
                prompt = Prompt(
                    id=uuid7(),
                    task=document["task"],
                    version=document["version"],
                    status="draft",
                    template=document["template"],
                    variables=document["variables"],
                    response_schema=document["response_schema"],
                    examples=document["examples"],
                    model_config_json=document["model_config"],
                    changelog=document["changelog"],
                    content_hash=document["content_hash"],
                    created_by=principal.user_id,
                )
                uow.session.add(prompt)
                created.append(f"{prompt.task}:v{prompt.version}")
                AuditRecorder(uow.session).record(
                    action="prompt.synced",
                    resource_type="prompt",
                    resource_id=prompt.id,
                    tenant_id=principal.tenant_id,
                    actor_id=principal.user_id,
                    actor_type="platform",
                    new_values={
                        "task": prompt.task,
                        "version": prompt.version,
                        "content_hash": prompt.content_hash,
                    },
                )
                uow.collect(
                    DomainEvent(
                        event_type=PROMPT_SYNCED,
                        tenant_id=principal.tenant_id,
                        resource_type="prompt",
                        resource_id=prompt.id,
                        actor_id=principal.user_id,
                        actor_type="platform",
                        payload={"task": prompt.task, "version": prompt.version},
                    )
                )
            evaluation = document["evaluation"]
            evaluation_set = await uow.session.scalar(
                select(AiEvaluationSet).where(
                    AiEvaluationSet.task == document["task"],
                    AiEvaluationSet.name == str(evaluation.get("name", "baseline")),
                    AiEvaluationSet.version == int(evaluation.get("version", 1)),
                )
            )
            cases = list(evaluation["cases"])
            if evaluation_set is not None and canonical_json(
                evaluation_set.cases
            ) != canonical_json(cases):
                raise Conflict("A committed evaluation set version is immutable.")
            if evaluation_set is None:
                uow.session.add(
                    AiEvaluationSet(
                        id=uuid7(),
                        task=document["task"],
                        name=str(evaluation.get("name", "baseline")),
                        version=int(evaluation.get("version", 1)),
                        cases=cases,
                        metric=str(evaluation.get("metric", "contract_pass_rate")),
                        threshold=float(evaluation.get("threshold", 0.85)),
                    )
                )
        result = {
            "manifest_hash": manifest_hash,
            "discovered": len(documents),
            "created": created,
            "unchanged_count": len(documents) - len(created),
        }
        reservation.complete(status=200, body=result)
    return result


async def record_evaluation(
    principal: Any,
    *,
    task: str,
    version: int,
    evaluation_set: str,
    evaluation_version: int,
    content_hash: str,
    results: list[dict[str, Any]],
    idempotency_key: str | None,
) -> dict[str, Any]:
    _require_platform(principal, "update")
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.ai import AiEvaluationRun, AiEvaluationSet, Prompt
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    request = {
        "task": task,
        "version": version,
        "evaluation_set": evaluation_set,
        "evaluation_version": evaluation_version,
        "content_hash": content_hash,
        "results": results,
    }
    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope=f"prompt.evaluate:{task}:v{version}",
            key=idempotency_key,
            request_hash=hash_payload(request),
        )
        if reservation.replay is not None:
            return reservation.replay
        prompt = await uow.session.scalar(
            select(Prompt).where(Prompt.task == task, Prompt.version == version)
        )
        if prompt is None:
            raise NotFound("Prompt version not found; sync the Git registry first.")
        if prompt.content_hash != content_hash:
            raise Conflict("Evaluation content hash does not match the immutable prompt.")
        gold = await uow.session.scalar(
            select(AiEvaluationSet).where(
                AiEvaluationSet.task == task,
                AiEvaluationSet.name == evaluation_set,
                AiEvaluationSet.version == evaluation_version,
            )
        )
        if gold is None:
            raise NotFound("Evaluation set not found; sync the Git registry first.")
        expected_ids = {
            str(case.get("id")) for case in gold.cases if isinstance(case, dict) and case.get("id")
        }
        result_ids = {str(item.get("case_id")) for item in results}
        if not expected_ids or result_ids != expected_ids or len(results) != len(result_ids):
            raise ValidationError("Evaluation results must cover every gold case exactly once.")
        compact_results = [
            {
                "case_id": str(item["case_id"]),
                "passed": bool(item["passed"]),
                "detail": str(item.get("detail", ""))[:500],
            }
            for item in results
        ]
        score = sum(1 for item in compact_results if item["passed"]) / len(compact_results)
        run_id = uuid7()
        run = AiEvaluationRun(
            id=run_id,
            evaluation_set_id=gold.id,
            prompt_id=prompt.id,
            model="offline-contract-evaluator-v1",
            score=score,
            baseline_score=gold.threshold,
            passed=score >= gold.threshold,
            results=compact_results,
            notes="Deterministic prompt and guard contracts; no provider called.",
        )
        uow.session.add(run)
        AuditRecorder(uow.session).record(
            action="prompt.evaluated",
            resource_type="ai_evaluation_run",
            resource_id=run_id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type="platform",
            new_values={"task": task, "version": version, "score": score, "passed": run.passed},
        )
        uow.collect(
            DomainEvent(
                event_type=PROMPT_EVALUATED,
                tenant_id=principal.tenant_id,
                resource_type="ai_evaluation_run",
                resource_id=run_id,
                actor_id=principal.user_id,
                actor_type="platform",
                payload={"task": task, "version": version, "score": score, "passed": run.passed},
            )
        )
        response = {"evaluation_run_id": str(run_id), "score": score, "passed": run.passed}
        reservation.complete(status=201, body=response)
    return response


async def promote_prompt(
    principal: Any,
    *,
    task: str,
    version: int,
    evaluation_run_id: UUID,
    idempotency_key: str | None,
) -> dict[str, Any]:
    _require_platform(principal, "update")
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.ai import AiEvaluationRun, Prompt
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    request = {"task": task, "version": version, "evaluation_run_id": str(evaluation_run_id)}
    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope=f"prompt.promote:{task}",
            key=idempotency_key,
            request_hash=hash_payload(request),
        )
        if reservation.replay is not None:
            return reservation.replay
        target = await uow.session.scalar(
            select(Prompt).where(Prompt.task == task, Prompt.version == version).with_for_update()
        )
        run = await uow.session.scalar(
            select(AiEvaluationRun).where(AiEvaluationRun.id == evaluation_run_id)
        )
        if target is None:
            raise NotFound("Prompt version not found.")
        if run is None or run.prompt_id != target.id or not run.passed:
            raise Conflict("Promotion requires a passing evaluation for this exact prompt version.")
        previous = await uow.session.scalar(
            select(Prompt)
            .where(Prompt.task == task, Prompt.status == "production")
            .with_for_update()
        )
        previous_version = previous.version if previous else None
        if previous is not None and previous.id != target.id:
            previous.status = "deprecated"
            previous.updated_by = principal.user_id
            await uow.flush()
        target.status = "production"
        target.promoted_at = utcnow()
        target.promoted_by = principal.user_id
        target.evaluation_run_id = run.id
        target.updated_by = principal.user_id
        AuditRecorder(uow.session).record(
            action="prompt.promoted",
            resource_type="prompt",
            resource_id=target.id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type="platform",
            old_values={"production_version": previous_version},
            new_values={"production_version": target.version, "evaluation_run_id": str(run.id)},
        )
        uow.collect(
            DomainEvent(
                event_type=PROMPT_PROMOTED,
                tenant_id=principal.tenant_id,
                resource_type="prompt",
                resource_id=target.id,
                actor_id=principal.user_id,
                actor_type="platform",
                payload={"task": task, "version": target.version},
            )
        )
        response = _serialize_prompt(target)
        reservation.complete(status=200, body=response)
    return response


async def rollback_prompt(
    principal: Any,
    *,
    task: str,
    target_version: int,
    idempotency_key: str | None,
) -> dict[str, Any]:
    _require_platform(principal, "update")
    from application.audit.recorder import AuditRecorder
    from infrastructure.database.models.ai import AiEvaluationRun, Prompt
    from infrastructure.uow.sqlalchemy_uow import SqlAlchemyUnitOfWork

    request = {"task": task, "target_version": target_version}
    async with SqlAlchemyUnitOfWork(principal.tenant_id) as uow:
        reservation = await reserve_idempotency(
            uow.session,
            tenant_id=principal.tenant_id,
            scope=f"prompt.rollback:{task}",
            key=idempotency_key,
            request_hash=hash_payload(request),
        )
        if reservation.replay is not None:
            return reservation.replay
        current = await uow.session.scalar(
            select(Prompt)
            .where(Prompt.task == task, Prompt.status == "production")
            .with_for_update()
        )
        target = await uow.session.scalar(
            select(Prompt)
            .where(Prompt.task == task, Prompt.version == target_version)
            .with_for_update()
        )
        if current is None or target is None or current.id == target.id:
            raise Conflict("Rollback requires a different existing production predecessor.")
        run = (
            await uow.session.scalar(
                select(AiEvaluationRun).where(AiEvaluationRun.id == target.evaluation_run_id)
            )
            if target.evaluation_run_id
            else None
        )
        if run is None or not run.passed or run.prompt_id != target.id:
            raise Conflict("Rollback target lacks passing evaluation evidence.")
        from_version = current.version
        current.status = "deprecated"
        current.rollback_target_version = target_version
        current.updated_by = principal.user_id
        await uow.flush()
        target.status = "production"
        target.promoted_at = utcnow()
        target.promoted_by = principal.user_id
        target.updated_by = principal.user_id
        AuditRecorder(uow.session).record(
            action="prompt.rolled_back",
            resource_type="prompt",
            resource_id=target.id,
            tenant_id=principal.tenant_id,
            actor_id=principal.user_id,
            actor_type="platform",
            old_values={"production_version": from_version},
            new_values={"production_version": target_version},
        )
        uow.collect(
            DomainEvent(
                event_type=PROMPT_ROLLED_BACK,
                tenant_id=principal.tenant_id,
                resource_type="prompt",
                resource_id=target.id,
                actor_id=principal.user_id,
                actor_type="platform",
                payload={"task": task, "from_version": from_version, "version": target_version},
            )
        )
        response = _serialize_prompt(target)
        reservation.complete(status=200, body=response)
    return response


async def resolve_production_prompt(tenant_id: UUID, task: Task | str) -> dict[str, Any] | None:
    """Return governed runtime material; no production row means AI must degrade."""
    from infrastructure.database.models.ai import Prompt
    from infrastructure.database.session import tenant_session
    from infrastructure.logging.setup import get_logger

    try:
        async with tenant_session(tenant_id) as session:
            row = await session.scalar(
                select(Prompt).where(Prompt.task == str(task), Prompt.status == "production")
            )
            if row is None:
                return None
            return {
                "system_prompt": row.template,
                "prompt_id": str(row.id),
                "prompt_version": row.version,
                "prompt_hash": row.content_hash,
                "response_schema": dict(row.response_schema or {}),
                "model_config": dict(row.model_config_json or {}),
            }
    except Exception as exc:
        get_logger("application.ai.prompts").warning(
            "prompt_registry_unavailable", task=str(task), error=type(exc).__name__
        )
        return None
