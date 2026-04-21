import pytest
from pydantic import ValidationError

from app.schemas import RunState, TaskSpec, TraceEvent
from app.schemas.task import TaskType
from app.schemas.verification import VerificationCommandResult, VerificationResult


def test_schema_exports_support_package_imports():
    assert RunState is not None
    assert TaskSpec is not None
    assert TraceEvent is not None


def test_run_state_uses_shared_task_type_alias():
    assert RunState.model_fields["task_type"].annotation is TaskType


def test_run_state_serializes_expected_fields():
    state = RunState(
        run_id="preview-123456789abc",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="completed",
        current_step="summarize",
        summary="Task preview completed",
        trace_path="/tmp/demo.jsonl",
    )

    assert state.model_dump() == {
        "run_id": "preview-123456789abc",
        "task_id": "demo-ci-001",
        "task_type": "ci_fix",
        "status": "completed",
        "current_step": "summarize",
        "summary": "Task preview completed",
        "trace_path": "/tmp/demo.jsonl",
        "verification": None,
    }


def test_run_state_includes_verification_result():
    state = RunState(
        run_id="preview-123456789abc",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="failed",
        current_step="summarize",
        summary="Verification failed",
        trace_path="/tmp/demo.jsonl",
        verification=VerificationResult(
            status="failed",
            passed_count=0,
            failed_count=1,
            command_results=[
                VerificationCommandResult(
                    command="pytest tests/unit/test_run_state.py -v",
                    exit_code=1,
                    status="failed",
                    duration_ms=1200,
                )
            ],
        ),
    )

    assert state.verification is not None
    assert state.verification.status == "failed"


def test_run_state_rejects_unknown_fields():
    with pytest.raises(ValidationError) as excinfo:
        RunState(
            run_id="preview-123456789abc",
            task_id="demo-ci-001",
            task_type="ci_fix",
            status="running",
            current_step="bootstrap",
            summary="Starting task run",
            trace_path="/tmp/demo.jsonl",
            extra_field="unexpected",
        )

    assert "extra_field" in str(excinfo.value)


@pytest.mark.parametrize(
    "field,value",
    [
        ("task_type", "not-a-task"),
        ("status", "paused"),
        ("current_step", "done"),
    ],
)
def test_run_state_rejects_invalid_enum_values(field, value):
    kwargs = {
        "run_id": "preview-123456789abc",
        "task_id": "demo-ci-001",
        "task_type": "ci_fix",
        "status": "running",
        "current_step": "bootstrap",
        "summary": "Starting task run",
        "trace_path": "/tmp/demo.jsonl",
    }
    kwargs[field] = value

    with pytest.raises(ValidationError) as excinfo:
        RunState(**kwargs)

    assert field in str(excinfo.value)
