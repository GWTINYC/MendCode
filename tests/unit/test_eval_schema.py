import pytest
from pydantic import ValidationError

from app.schemas.eval import BatchEvalResult, BatchEvalSummary


def test_batch_eval_result_accepts_expected_fields() -> None:
    result = BatchEvalResult.model_validate(
        {
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
    )

    assert result.task_id == "task-1"
    assert result.status == "completed"
    assert result.current_step == "summarize"


def test_batch_eval_summary_rejects_mismatched_task_counts() -> None:
    with pytest.raises(ValidationError):
        BatchEvalSummary.model_validate(
            {
                "run_id": "run-1",
                "task_count": 2,
                "completed_count": 1,
                "failed_count": 0,
                "output_dir": "data/evals/run-1",
                "summary_json_path": "data/evals/run-1/summary.json",
                "summary_md_path": "data/evals/run-1/summary.md",
                "results": [
                    {
                        "task_id": "task-1",
                        "task_type": "ci_fix",
                        "task_file": "tasks/task-1.json",
                        "status": "completed",
                        "current_step": "summarize",
                        "summary": "done",
                        "passed_count": 1,
                        "failed_count": 0,
                        "applied_patch": True,
                        "tool_results": [],
                        "trace_path": "data/traces/task-1.jsonl",
                        "workspace_path": "/tmp/workspace/task-1",
                    }
                ],
            }
        )
