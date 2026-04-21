import json

from app.orchestrator.runner import run_task_preview
from app.schemas.task import TaskSpec


def build_task() -> TaskSpec:
    return TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Fix failing unit test",
        repo_path="/repo/demo",
        entry_artifacts={"failure_summary": "Unit test failure"},
        verification_commands=["pytest -q"],
    )


def test_run_task_preview_returns_completed_state(tmp_path):
    result = run_task_preview(build_task(), tmp_path)

    assert result.task_id == "demo-ci-001"
    assert result.task_type == "ci_fix"
    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.summary == "Task preview completed"


def test_run_task_preview_writes_started_and_completed_events(tmp_path):
    result = run_task_preview(build_task(), tmp_path)
    trace_file = tmp_path / f"{result.run_id}.jsonl"

    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert trace_file.exists()
    assert result.trace_path == str(trace_file)
    assert [event["event_type"] for event in events] == [
        "run.started",
        "run.completed",
    ]
    assert events[0]["payload"]["task_id"] == "demo-ci-001"
    assert events[1]["payload"]["status"] == "completed"
