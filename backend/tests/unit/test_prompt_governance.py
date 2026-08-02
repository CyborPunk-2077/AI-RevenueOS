"""Git prompt definitions and offline gold-set evaluation."""

from __future__ import annotations

from application.ai.prompt_registry import evaluate_prompt_document, load_git_prompts
from infrastructure.ai.models import Task
from scripts.run_ai_evals import run


def test_every_ai_task_has_a_versioned_prompt_and_passing_gold_set() -> None:
    documents = load_git_prompts()
    tasks = {str(document["task"]) for document in documents}
    assert tasks == {task.value for task in Task}
    for document in documents:
        result = evaluate_prompt_document(document)
        assert result["passed"] is True
        assert result["score"] == 1.0
        assert result["provider_called"] is False
        assert len(str(document["content_hash"])) == 64


def test_eval_runner_is_truthful_about_offline_evidence() -> None:
    report = run(fail_under=0.85)
    assert report["passed"] is True
    assert report["aggregate_score"] == 1.0
    assert report["provider_called"] is False
    assert report["model_quality_claimed"] is False
