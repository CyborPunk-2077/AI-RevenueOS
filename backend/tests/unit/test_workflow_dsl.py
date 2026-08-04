"""The restricted DSL is the boundary that keeps n8n out of production execution."""

from __future__ import annotations

from typing import Any

import pytest

from domain.workflows.dsl import (
    ACTION_CATALOG,
    MAX_LOOP_HARD,
    DslValidationError,
    canonical_hash,
    compile_workflow,
    validate_workflow,
)


def wf(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "name": "Welcome new leads",
        "description": "Tag and notify on capture",
        "category": "lead_nurture",
        "trigger": {"type": "entity.created", "entity": "lead"},
        "nodes": [
            {"id": "n1", "type": "action", "action": "tag.add", "inputs": {"tag": "new"}},
            {
                "id": "n2",
                "type": "action",
                "action": "task.create",
                "inputs": {"title": "Call {{entity.first_name}}"},
            },
        ],
        "edges": [{"source": "n1", "target": "n2"}],
        "global_policy": {"concurrency": 10, "timeout_seconds": 3600, "retry_attempts": 3},
    }
    doc.update(overrides)
    return doc


class TestStructuralValidation:
    def test_valid_document(self) -> None:
        report = validate_workflow(wf())
        assert report.valid is True
        assert report.node_count == 2

    def test_name_bounds(self) -> None:
        assert validate_workflow(wf(name="")).valid is False
        assert validate_workflow(wf(name="x" * 201)).valid is False

    def test_unknown_category_and_trigger(self) -> None:
        assert "unknown category 'space'" in validate_workflow(wf(category="space")).problems[0]
        assert validate_workflow(wf(trigger={"type": "telepathy"})).valid is False

    def test_empty_node_list_rejected(self) -> None:
        assert validate_workflow(wf(nodes=[], edges=[])).valid is False

    def test_duplicate_node_ids_rejected(self) -> None:
        doc = wf(
            nodes=[
                {"id": "n1", "type": "action", "action": "tag.add"},
                {"id": "n1", "type": "action", "action": "tag.remove"},
            ],
            edges=[],
        )
        assert any("duplicate node id" in p for p in validate_workflow(doc).problems)

    def test_edge_to_unknown_node_rejected(self) -> None:
        doc = wf(edges=[{"source": "n1", "target": "ghost"}])
        assert any("unknown target node" in p for p in validate_workflow(doc).problems)

    def test_cycle_rejected(self) -> None:
        doc = wf(edges=[{"source": "n1", "target": "n2"}, {"source": "n2", "target": "n1"}])
        assert any("acyclic" in p for p in validate_workflow(doc).problems)

    def test_unreachable_node_is_a_warning_not_an_error(self) -> None:
        doc = wf(
            nodes=[
                {"id": "n1", "type": "action", "action": "tag.add"},
                {"id": "n2", "type": "action", "action": "tag.remove"},
                {"id": "orphan", "type": "action", "action": "note.create"},
            ],
            edges=[{"source": "n1", "target": "n2"}],
        )
        report = validate_workflow(doc)
        assert report.valid is True
        assert any("unreachable" in w for w in report.warnings)


class TestExpressionSandbox:
    @pytest.mark.parametrize(
        "expr",
        [
            "{{ __import__('os').system('rm -rf /') }}",
            "{{ eval('1+1') }}",
            "{{ process.env.SECRET }}",
            "{{ require('fs') }}",
            "{{ globals() }}",
            "{{ fetch('https://evil.example.com') }}",
        ],
    )
    def test_forbidden_tokens_rejected(self, expr: str) -> None:
        doc = wf(
            nodes=[
                {"id": "n1", "type": "action", "action": "note.create", "inputs": {"body": expr}}
            ],
            edges=[],
        )
        assert any("forbidden token" in p for p in validate_workflow(doc).problems)

    def test_unavailable_root_rejected(self) -> None:
        doc = wf(
            nodes=[
                {
                    "id": "n1",
                    "type": "action",
                    "action": "note.create",
                    "inputs": {"body": "{{ secrets.razorpay_key }}"},
                }
            ],
            edges=[],
        )
        assert any("unavailable root" in p for p in validate_workflow(doc).problems)

    def test_allowed_roots_and_functions_pass(self) -> None:
        doc = wf(
            nodes=[
                {
                    "id": "n1",
                    "type": "action",
                    "action": "note.create",
                    "inputs": {"body": "{{ lower(entity.first_name) }} at {{ now() }}"},
                }
            ],
            edges=[],
        )
        assert validate_workflow(doc).valid is True


class TestActionSafety:
    def test_unknown_action_rejected(self) -> None:
        doc = wf(nodes=[{"id": "n1", "type": "action", "action": "database.drop"}], edges=[])
        assert any("unknown action" in p for p in validate_workflow(doc).problems)

    def test_irreversible_action_requires_upstream_approval(self) -> None:
        doc = wf(nodes=[{"id": "n1", "type": "action", "action": "payment.refund"}], edges=[])
        report = validate_workflow(doc)
        assert report.valid is False
        assert any("requires an upstream approval" in p for p in report.problems)

    def test_approval_node_upstream_satisfies_the_rule(self) -> None:
        doc = wf(
            nodes=[
                {"id": "a1", "type": "approval", "assignees": ["role:manager"]},
                {"id": "n1", "type": "action", "action": "payment.refund"},
            ],
            edges=[{"source": "a1", "target": "n1"}],
        )
        assert validate_workflow(doc).valid is True

    def test_transitive_upstream_approval_is_detected(self) -> None:
        doc = wf(
            nodes=[
                {"id": "a1", "type": "approval", "assignees": ["role:owner"]},
                {"id": "mid", "type": "action", "action": "note.create"},
                {"id": "n1", "type": "action", "action": "document.send"},
            ],
            edges=[{"source": "a1", "target": "mid"}, {"source": "mid", "target": "n1"}],
        )
        assert validate_workflow(doc).valid is True

    def test_external_effect_nodes_are_reported(self) -> None:
        doc = wf(
            nodes=[
                {"id": "a1", "type": "approval", "assignees": ["u1"]},
                {"id": "n1", "type": "action", "action": "message.send_whatsapp"},
            ],
            edges=[{"source": "a1", "target": "n1"}],
        )
        assert validate_workflow(doc).external_effect_nodes == ["n1"]

    def test_every_action_declares_permission_and_retry_class(self) -> None:
        for spec in ACTION_CATALOG.values():
            assert ":" in spec.permission
            assert spec.retry_class in ("transient", "none", "provider")
            assert spec.timeout_seconds > 0


class TestNodeTypeRules:
    def test_delay_bounds(self) -> None:
        doc = wf(nodes=[{"id": "n1", "type": "delay", "delay_seconds": 0}], edges=[])
        assert validate_workflow(doc).valid is False

    def test_loop_hard_maximum(self) -> None:
        doc = wf(
            nodes=[{"id": "n1", "type": "loop", "max_iterations": MAX_LOOP_HARD + 1}], edges=[]
        )
        assert validate_workflow(doc).valid is False

    def test_parallel_join_strategies(self) -> None:
        for join in ("all", "any", "majority", "count"):
            doc = wf(nodes=[{"id": "n1", "type": "parallel", "join": join}], edges=[])
            assert validate_workflow(doc).valid is True
        bad = wf(nodes=[{"id": "n1", "type": "parallel", "join": "whoever"}], edges=[])
        assert validate_workflow(bad).valid is False

    def test_approval_requires_assignees(self) -> None:
        doc = wf(nodes=[{"id": "n1", "type": "approval"}], edges=[])
        assert validate_workflow(doc).valid is False

    @pytest.mark.parametrize(
        "node",
        [
            {"id": "n1", "type": "approval", "assignees": ["role:owner"], "strategy": "veto"},
            {
                "id": "n1",
                "type": "approval",
                "assignees": ["role:owner"],
                "strategy": "quorum",
                "quorum": 2,
            },
            {
                "id": "n1",
                "type": "approval",
                "assignees": ["role:owner"],
                "strategy": "quorum",
                "quorum": 0,
            },
        ],
    )
    def test_approval_strategy_and_quorum_are_validated(self, node: dict[str, object]) -> None:
        assert validate_workflow(wf(nodes=[node], edges=[])).valid is False

    def test_condition_operator_validation(self) -> None:
        good = wf(
            nodes=[
                {
                    "id": "n1",
                    "type": "condition",
                    "condition": {"operator": "gte", "left": "{{entity.score}}", "right": 80},
                }
            ],
            edges=[],
        )
        assert validate_workflow(good).valid is True
        bad = wf(
            nodes=[
                {
                    "id": "n1",
                    "type": "condition",
                    "condition": {"operator": "telepathy", "left": "x"},
                }
            ],
            edges=[],
        )
        assert validate_workflow(bad).valid is False


class TestPolicyBounds:
    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("concurrency", 0),
            ("concurrency", 101),
            ("timeout_seconds", 59),
            ("timeout_seconds", 86_401),
            ("retry_attempts", 11),
            ("retry_max_seconds", 59),
        ],
    )
    def test_out_of_range_policy_rejected(self, key: str, value: int) -> None:
        assert validate_workflow(wf(global_policy={key: value})).valid is False

    def test_unknown_retry_strategy_rejected(self) -> None:
        assert validate_workflow(wf(global_policy={"retry_strategy": "psychic"})).valid is False


class TestCanonicalHashAndCompile:
    def test_hash_is_key_order_and_whitespace_stable(self) -> None:
        a = wf()
        b = {k: a[k] for k in reversed(list(a))}
        assert canonical_hash(a) == canonical_hash(b)

    def test_hash_ignores_version_metadata(self) -> None:
        assert canonical_hash(wf(version=1)) == canonical_hash(wf(version=7))

    def test_hash_changes_when_behaviour_changes(self) -> None:
        changed = wf()
        changed["nodes"][0]["inputs"] = {"tag": "different"}
        assert canonical_hash(wf()) != canonical_hash(changed)

    def test_compile_produces_a_pinned_plan(self) -> None:
        plan = compile_workflow(wf())
        assert plan["entry_nodes"] == ["n1"]
        assert plan["adjacency"]["n1"][0]["target"] == "n2"
        assert plan["content_hash"] == canonical_hash(wf())
        assert plan["global_policy"]["error_policy"] == "stop"

    def test_compile_orders_edges_by_priority(self) -> None:
        doc = wf(
            nodes=[
                {"id": "n1", "type": "action", "action": "tag.add"},
                {"id": "n2", "type": "action", "action": "tag.remove"},
                {"id": "n3", "type": "action", "action": "note.create"},
            ],
            edges=[
                {"source": "n1", "target": "n2", "priority": 1},
                {"source": "n1", "target": "n3", "priority": 9},
            ],
        )
        plan = compile_workflow(doc)
        assert [e["target"] for e in plan["adjacency"]["n1"]] == ["n3", "n2"]

    def test_compile_refuses_an_invalid_document(self) -> None:
        with pytest.raises(DslValidationError):
            compile_workflow(
                wf(nodes=[{"id": "n1", "type": "action", "action": "rm.rf"}], edges=[])
            )
