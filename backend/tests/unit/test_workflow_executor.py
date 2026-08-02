"""Execution semantics: idempotency, retry, approval, kill, replay and dry run."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

from application.workflows.executor import (
    QUEUES,
    ExecutionContext,
    ExecutionState,
    NodeState,
    TerminalActionError,
    WorkflowEngine,
    action_idempotency_key,
    build_plan,
    evaluate_condition,
    execution_idempotency_key,
    inbound_idempotency_key,
    replay_context,
    resolve_path,
)

TENANT = uuid4()


def doc(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], **policy: Any) -> dict[str, Any]:
    return {
        "name": "Test workflow",
        "category": "custom",
        "trigger": {"type": "entity.created", "entity": "lead"},
        "nodes": nodes,
        "edges": edges,
        "global_policy": {"error_policy": "stop", "retry_attempts": 2, **policy},
    }


def context(plan_hash: str, **over: Any) -> ExecutionContext:
    base = {
        "execution_id": uuid4(),
        "tenant_id": TENANT,
        "workflow_id": uuid4(),
        "version_id": uuid4(),
        "content_hash": plan_hash,
        "entity": {"first_name": "Asha", "qualification_score": 85, "status": "new"},
        "trigger_payload": {"source": "web_form"},
    }
    base.update(over)
    return ExecutionContext(**base)  # type: ignore[arg-type]


class Recorder:
    def __init__(self, *, fail_times: int = 0, terminal: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_times = fail_times
        self._terminal = terminal

    async def __call__(
        self, action: str, inputs: dict[str, Any], ctx: ExecutionContext, key: str
    ) -> dict[str, Any]:
        self.calls.append((action, key))
        if self._terminal:
            raise TerminalActionError("the recipient has opted out")
        if len(self.calls) <= self._fail_times:
            raise ConnectionError("provider unreachable")
        return {"ok": True}


class TestIdempotencyKeys:
    def test_execution_key_derives_from_the_original_event(self) -> None:
        wf, ver, event = uuid4(), uuid4(), uuid4()
        first = execution_idempotency_key(workflow_id=wf, version_id=ver, trigger_event_id=event)
        second = execution_idempotency_key(workflow_id=wf, version_id=ver, trigger_event_id=event)
        assert first == second

    def test_a_different_version_produces_a_different_key(self) -> None:
        wf, event = uuid4(), uuid4()
        assert execution_idempotency_key(
            workflow_id=wf, version_id=uuid4(), trigger_event_id=event
        ) != execution_idempotency_key(workflow_id=wf, version_id=uuid4(), trigger_event_id=event)

    def test_action_key_is_execution_node_attempt(self) -> None:
        exec_id = uuid4()
        assert action_idempotency_key(execution_id=exec_id, node_id="n1", attempt=2) == (
            f"{exec_id}:n1:2"
        )

    def test_inbound_key_is_provider_scoped(self) -> None:
        assert inbound_idempotency_key(provider="razorpay", event_id="evt_1") == (
            "inbound:razorpay:evt_1"
        )


class TestExpressionScope:
    SCOPE = {
        "entity": {"first_name": "Asha", "address": {"city": "Pune"}},
        "event": {"source": "web_form"},
        "workflow": {"id": "w1"},
    }

    def test_dotted_lookup(self) -> None:
        assert resolve_path(self.SCOPE, "entity.address.city") == "Pune"

    def test_unknown_path_is_none_not_an_error(self) -> None:
        assert resolve_path(self.SCOPE, "entity.nope.deeper") is None

    def test_secrets_are_not_reachable(self) -> None:
        assert resolve_path(self.SCOPE, "secrets.razorpay") is None
        assert resolve_path(self.SCOPE, "__class__") is None

    @pytest.mark.parametrize(
        ("operator", "left", "right", "expected"),
        [
            ("eq", "{{entity.first_name}}", "Asha", True),
            ("ne", "{{entity.first_name}}", "Ravi", True),
            ("contains", "{{entity.first_name}}", "sh", True),
            ("starts_with", "{{entity.first_name}}", "As", True),
            ("is_empty", "{{entity.missing}}", None, True),
            ("is_not_empty", "{{entity.first_name}}", None, True),
            ("in", "{{event.source}}", ["web_form", "api"], True),
            ("not_in", "{{event.source}}", ["api"], True),
        ],
    )
    def test_operators(self, operator: str, left: Any, right: Any, expected: bool) -> None:
        assert (
            evaluate_condition({"operator": operator, "left": left, "right": right}, self.SCOPE)
            is expected
        )

    def test_numeric_comparison_with_incompatible_types_is_false_not_an_error(self) -> None:
        assert (
            evaluate_condition(
                {"operator": "gt", "left": "{{entity.first_name}}", "right": 5}, self.SCOPE
            )
            is False
        )

    def test_logical_composition(self) -> None:
        condition = {
            "operator": "and",
            "conditions": [
                {"operator": "eq", "left": "{{entity.first_name}}", "right": "Asha"},
                {"operator": "eq", "left": "{{event.source}}", "right": "web_form"},
            ],
        }
        assert evaluate_condition(condition, self.SCOPE) is True

    def test_not_inverts(self) -> None:
        condition = {
            "operator": "not",
            "conditions": [{"operator": "eq", "left": "{{event.source}}", "right": "api"}],
        }
        assert evaluate_condition(condition, self.SCOPE) is True


class TestExecution:
    async def test_linear_run_completes(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "n1", "type": "action", "action": "tag.add"},
                    {"id": "n2", "type": "action", "action": "task.create"},
                ],
                [{"source": "n1", "target": "n2"}],
            )
        )
        runner = Recorder()
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.COMPLETED
        assert [c[0] for c in runner.calls] == ["tag.add", "task.create"]

    async def test_hash_mismatch_refuses_to_execute(self) -> None:
        plan, _ = build_plan(doc([{"id": "n1", "type": "action", "action": "tag.add"}], []))
        with pytest.raises(ValueError, match="content hash"):
            await WorkflowEngine(action_runner=Recorder()).execute(
                plan, context("a-different-hash")
            )

    async def test_condition_branches_on_the_true_edge(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {
                        "id": "c1",
                        "type": "condition",
                        "condition": {
                            "operator": "gte",
                            "left": "{{entity.qualification_score}}",
                            "right": 80,
                        },
                    },
                    {"id": "hot", "type": "action", "action": "lead.assign"},
                    {"id": "cold", "type": "action", "action": "tag.add"},
                ],
                [
                    {"source": "c1", "target": "hot", "label": "true"},
                    {"source": "c1", "target": "cold", "label": "false"},
                ],
            )
        )
        runner = Recorder()
        await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert [c[0] for c in runner.calls] == ["lead.assign"]

    async def test_delay_suspends_durably_rather_than_sleeping(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "d1", "type": "delay", "delay_seconds": 3600},
                    {"id": "n1", "type": "action", "action": "tag.add"},
                ],
                [{"source": "d1", "target": "n1"}],
            )
        )
        runner = Recorder()
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.WAITING
        assert result.resume_at is not None
        assert result.resume_nodes == ["n1"]
        assert runner.calls == []

    async def test_approval_node_suspends_before_the_gated_action(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "a1", "type": "approval", "assignees": ["role:manager"]},
                    {"id": "n1", "type": "action", "action": "document.send"},
                ],
                [{"source": "a1", "target": "n1"}],
            )
        )
        runner = Recorder()
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.WAITING
        assert result.waiting_on == "a1"
        assert runner.calls == []

    async def test_resuming_after_approval_runs_the_gated_action(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "a1", "type": "approval", "assignees": ["role:manager"]},
                    {"id": "n1", "type": "action", "action": "document.send"},
                ],
                [{"source": "a1", "target": "n1"}],
            )
        )
        runner = Recorder()
        result = await WorkflowEngine(action_runner=runner).execute(
            plan, context(digest), resume_from="n1"
        )
        assert result.state is ExecutionState.COMPLETED
        assert [c[0] for c in runner.calls] == ["document.send"]


class TestRetryAndFailure:
    async def test_transient_failure_is_retried_with_a_new_attempt_key(self) -> None:
        plan, digest = build_plan(doc([{"id": "n1", "type": "action", "action": "tag.add"}], []))
        runner = Recorder(fail_times=2)
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.COMPLETED
        assert len(runner.calls) == 3
        assert len({key for _, key in runner.calls}) == 3

    async def test_retries_are_bounded_by_the_policy(self) -> None:
        plan, digest = build_plan(
            doc([{"id": "n1", "type": "action", "action": "tag.add"}], [], retry_attempts=1)
        )
        runner = Recorder(fail_times=99)
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.FAILED
        assert len(runner.calls) == 2

    async def test_terminal_failure_is_never_retried(self) -> None:
        plan, digest = build_plan(doc([{"id": "n1", "type": "action", "action": "tag.add"}], []))
        runner = Recorder(terminal=True)
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.FAILED
        assert len(runner.calls) == 1
        assert result.nodes[0].error["retried"] is False

    async def test_validation_failure_is_classified_terminal(self) -> None:
        from shared.exceptions import ValidationError

        plan, digest = build_plan(doc([{"id": "n1", "type": "action", "action": "tag.add"}], []))

        class Invalid(Recorder):
            async def __call__(
                self, action: str, inputs: dict[str, Any], ctx: ExecutionContext, key: str
            ) -> dict[str, Any]:
                self.calls.append((action, key))
                raise ValidationError("invalid action input")

        runner = Invalid()
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.FAILED
        assert len(runner.calls) == 1

    async def test_continue_policy_carries_on_past_a_failed_node(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "n1", "type": "action", "action": "tag.add"},
                    {"id": "n2", "type": "action", "action": "note.create"},
                ],
                [{"source": "n1", "target": "n2"}],
                error_policy="continue",
                retry_attempts=0,
            )
        )

        class FailFirst(Recorder):
            async def __call__(self, action: str, inputs: dict, ctx: Any, key: str) -> dict:
                self.calls.append((action, key))
                if action == "tag.add":
                    raise TerminalActionError("nope")
                return {"ok": True}

        runner = FailFirst()
        result = await WorkflowEngine(action_runner=runner).execute(plan, context(digest))
        assert result.state is ExecutionState.COMPLETED
        assert [c[0] for c in runner.calls] == ["tag.add", "note.create"]


class TestKillAndDryRun:
    async def test_kill_switch_stops_the_execution(self) -> None:
        plan, digest = build_plan(doc([{"id": "n1", "type": "action", "action": "tag.add"}], []))

        async def killed(ctx: ExecutionContext) -> bool:
            return True

        runner = Recorder()
        result = await WorkflowEngine(action_runner=runner, kill_check=killed).execute(
            plan, context(digest)
        )
        assert result.state is ExecutionState.CANCELLED
        assert runner.calls == []

    async def test_dry_run_performs_no_external_effect(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "a1", "type": "approval", "assignees": ["u1"]},
                    {"id": "n1", "type": "action", "action": "message.send_whatsapp"},
                ],
                [{"source": "a1", "target": "n1"}],
            )
        )
        runner = Recorder()
        result = await WorkflowEngine(action_runner=runner).execute(
            plan, context(digest, dry_run=True), resume_from="n1"
        )
        assert runner.calls == []
        assert result.nodes[0].state is NodeState.SKIPPED
        assert result.nodes[0].output["would_call"] == "message.send_whatsapp"
        assert result.nodes[0].output["external_effect"] is True
        assert result.external_effects == []

    async def test_external_effects_are_reported_for_audit(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "a1", "type": "approval", "assignees": ["u1"]},
                    {"id": "n1", "type": "action", "action": "message.send_whatsapp"},
                ],
                [{"source": "a1", "target": "n1"}],
            )
        )
        result = await WorkflowEngine(action_runner=Recorder()).execute(
            plan, context(digest), resume_from="n1"
        )
        assert result.external_effects == ["n1"]

    def test_a_cyclic_document_is_rejected_at_compile_time(self) -> None:
        """The loop node bounds iteration; a back edge in the DAG is a defect."""
        from domain.workflows.dsl import DslValidationError

        with pytest.raises(DslValidationError, match="acyclic"):
            build_plan(
                doc(
                    [
                        {"id": "l1", "type": "loop", "max_iterations": 3},
                        {"id": "n1", "type": "action", "action": "tag.add"},
                    ],
                    [{"source": "l1", "target": "n1"}, {"source": "n1", "target": "l1"}],
                )
            )

    async def test_loop_node_bounds_its_iterations(self) -> None:
        plan, digest = build_plan(
            doc(
                [
                    {"id": "l1", "type": "loop", "max_iterations": 3},
                    {"id": "n1", "type": "action", "action": "tag.add"},
                ],
                [{"source": "l1", "target": "n1"}],
            )
        )
        result = await WorkflowEngine(action_runner=Recorder()).execute(plan, context(digest))
        assert result.state is ExecutionState.COMPLETED

    def test_replay_records_provenance_and_a_new_execution_id(self) -> None:
        original = context("hash")
        replay = replay_context(original, uuid4())
        assert replay.execution_id != original.execution_id
        assert replay.variables["_replay_of"] == str(original.execution_id)
        assert replay.content_hash == original.content_hash


def test_queue_configuration_matches_the_specification() -> None:
    assert QUEUES["workflow-critical"]["concurrency"] == 20
    assert QUEUES["workflow-critical"]["timeout"] == 30
    assert QUEUES["workflow-standard"]["concurrency"] == 50
    assert QUEUES["workflow-bulk"]["timeout"] == 900
    assert QUEUES["workflow-ai"]["timeout"] == 120
    assert len(QUEUES) == 8
    assert all(1 <= q["priority"] <= 10 for q in QUEUES.values())
