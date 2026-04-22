import pytest
from pydantic import ValidationError

from app.schemas import RunState, TaskSpec, TraceEvent
from app.schemas.task import TaskType
from app.schemas.verification import VerificationResult


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

    dump = state.model_dump()

    assert dump["run_id"] == "preview-123456789abc"
    assert dump["task_id"] == "demo-ci-001"
    assert dump["task_type"] == "ci_fix"
    assert dump["status"] == "completed"
    assert dump["current_step"] == "summarize"
    assert dump["summary"] == "Task preview completed"
    assert dump["trace_path"] == "/tmp/demo.jsonl"
    assert dump["workspace_path"] is None
    assert dump["selected_files"] == []
    assert dump["applied_patch"] is False
    assert dump["tool_results"] == []
    assert dump["verification"] is None


def test_run_state_accepts_fixed_flow_fields():
    state = RunState(
        run_id="preview-123",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="running",
        current_step="locate",
        summary="Locating target file",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/workspace",
        selected_files=["target.txt"],
        applied_patch=False,
        tool_results=[{"tool_name": "search_code", "status": "passed"}],
        verification=None,
    )

    assert state.current_step == "locate"
    assert state.selected_files == ["target.txt"]
    assert state.applied_patch is False
    assert state.tool_results == [{"tool_name": "search_code", "status": "passed"}]


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
            status="passed",
            passed_count=0,
            failed_count=0,
            command_results=[],
        ),
    )

    assert state.verification is not None
    assert state.verification.status == "passed"


def test_run_state_accepts_verify_current_step():
    state = RunState(
        run_id="preview-123456789abc",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="running",
        current_step="verify",
        summary="Verification in progress",
        trace_path="/tmp/demo.jsonl",
    )

    assert state.current_step == "verify"


def test_run_state_rejects_unknown_step_name():
    with pytest.raises(ValidationError) as excinfo:
        RunState(
            run_id="preview-123",
            task_id="demo-ci-001",
            task_type="ci_fix",
            status="running",
            current_step="plan",
            summary="Bad step",
            trace_path="/tmp/trace.jsonl",
        )

    assert "current_step" in str(excinfo.value)


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


def test_run_state_accepts_workspace_path():
    state = RunState(
        run_id="preview-123456789abc",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="completed",
        current_step="summarize",
        summary="Verification passed",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/worktree",
        verification=None,
    )

    assert state.workspace_path == "/tmp/worktree"
