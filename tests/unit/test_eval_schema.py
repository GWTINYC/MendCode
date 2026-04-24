import pytest
from pydantic import ValidationError

from app.schemas.eval import BatchEvalResult, BatchEvalSummary


def result_payload(**overrides):
    payload = {
        "task_id": "task-1",
        "task_type": "ci_fix",
        "task_file": "tasks/task-1.json",
        "status": "completed",
        "current_step": "summarize",
        "summary": "done",
        "passed_count": 2,
        "failed_count": 1,
        "applied_patch": True,
        "tool_results": [{"tool": "pytest", "status": "passed"}],
        "trace_path": "data/traces/task-1.jsonl",
        "workspace_path": "/tmp/workspace/task-1",
    }
    payload.update(overrides)
    return payload


def summary_payload(**overrides):
    payload = {
        "run_id": "run-1",
        "task_count": 2,
        "completed_count": 1,
        "failed_count": 1,
        "output_dir": "data/evals/run-1",
        "summary_json_path": "data/evals/run-1/summary.json",
        "summary_md_path": "data/evals/run-1/summary.md",
        "results": [
            result_payload(task_id="task-1"),
            result_payload(task_id="task-2", status="failed", summary="failed"),
        ],
    }
    payload.update(overrides)
    return payload


def test_batch_eval_result_accepts_expected_fields() -> None:
    result = BatchEvalResult.model_validate(result_payload())

    assert result.task_id == "task-1"
    assert result.status == "completed"
    assert result.current_step == "summarize"


def test_batch_eval_result_rejects_running_status() -> None:
    with pytest.raises(ValidationError):
        BatchEvalResult.model_validate(result_payload(status="running"))


def test_batch_eval_result_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BatchEvalResult.model_validate(result_payload(unexpected_field="nope"))


def test_batch_eval_summary_accepts_valid_counts_and_results() -> None:
    summary = BatchEvalSummary.model_validate(summary_payload())

    assert summary.task_count == 2
    assert summary.completed_count == 1
    assert summary.failed_count == 1
    assert len(summary.results) == 2


def test_batch_eval_summary_rejects_mismatched_task_counts() -> None:
    with pytest.raises(ValidationError):
        BatchEvalSummary.model_validate(
            summary_payload(
                task_count=3,
            )
        )


def test_batch_eval_summary_rejects_mismatched_status_counts() -> None:
    with pytest.raises(ValidationError):
        BatchEvalSummary.model_validate(
            summary_payload(
                completed_count=2,
                failed_count=0,
            )
        )


def test_batch_eval_summary_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        BatchEvalSummary.model_validate(
            summary_payload(unexpected_field="nope")
        )
