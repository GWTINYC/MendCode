import json
import shlex
import sys
from pathlib import Path

from app.orchestrator.runner import run_task_preview
from app.schemas.task import TaskSpec


PYTHON = shlex.quote(sys.executable)


def make_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    return repo_path


def build_task(repo_path: str = "/repo/demo") -> TaskSpec:
    return TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Fix failing unit test",
        repo_path=repo_path,
        entry_artifacts={"failure_summary": "Unit test failure"},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )


def test_run_task_preview_returns_completed_state(tmp_path):
    result = run_task_preview(build_task(str(make_repo(tmp_path))), tmp_path)

    assert result.task_id == "demo-ci-001"
    assert result.task_type == "ci_fix"
    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.verification is not None
    assert result.verification.status == "passed"
    assert result.summary == "Verification passed: 1/1 commands succeeded"


def test_run_task_preview_writes_started_and_completed_events(tmp_path):
    task = build_task(str(make_repo(tmp_path)))
    result = run_task_preview(task, tmp_path)
    trace_file = Path(result.trace_path)

    assert trace_file.exists()
    lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in lines]

    assert result.trace_path == str(trace_file)
    assert all(event["run_id"] == result.run_id for event in events)
    event_types = [event["event_type"] for event in events]

    assert event_types == [
        "run.started",
        "run.verification.started",
        "run.verification.command.completed",
        "run.completed",
    ]
    assert events[0]["payload"]["task_id"] == "demo-ci-001"
    assert events[1]["payload"]["status"] == "running"
    assert events[1]["payload"]["command_count"] == 1
    assert events[2]["payload"]["command"] == task.verification_commands[0]
    assert events[2]["payload"]["stdout_excerpt"] == "ok\n"
    assert events[2]["payload"]["stderr_excerpt"] == ""
    assert events[3]["payload"]["status"] == "completed"


def test_run_task_preview_uses_trace_recorder_return_path(tmp_path, monkeypatch):
    custom_trace_path = tmp_path / "nested" / "preview-custom.jsonl"

    def fake_record(self, event):
        custom_trace_path.parent.mkdir(parents=True, exist_ok=True)
        with custom_trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json")))
            handle.write("\n")
        return custom_trace_path

    monkeypatch.setattr("app.orchestrator.runner.TraceRecorder.record", fake_record)

    result = run_task_preview(build_task(str(make_repo(tmp_path))), tmp_path)

    assert result.trace_path == str(custom_trace_path)
    assert Path(result.trace_path).exists()


def test_run_task_preview_marks_run_passed_when_all_commands_succeed(tmp_path):
    repo_path = make_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Verify success path",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.verification is not None
    assert result.verification.status == "passed"
    assert result.verification.passed_count == 1
    assert result.verification.failed_count == 0
    assert result.summary == "Verification passed: 1/1 commands succeeded"


def test_run_task_preview_marks_run_failed_when_a_command_fails(tmp_path):
    repo_path = make_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Verify fail path",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[
            f"{PYTHON} -c \"print('ok')\"",
            f"{PYTHON} -c \"import sys; sys.exit(2)\"",
        ],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.status == "failed"
    assert result.verification.passed_count == 1
    assert result.verification.failed_count == 1
    assert "Verification failed" in result.summary


def test_run_task_preview_fails_when_no_verification_commands_are_defined(tmp_path):
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="No verification commands",
        repo_path="/repo/demo",
        entry_artifacts={},
        verification_commands=[],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.failed_count == 1
    assert result.summary == "Verification failed: no verification commands provided"


def test_run_task_preview_records_exact_oserror_text_without_trimming(tmp_path, monkeypatch):
    exact_error = "x" * 2501

    def raise_oserror(*args, **kwargs):
        raise OSError(exact_error)

    monkeypatch.setattr("app.orchestrator.runner.subprocess.run", raise_oserror)

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="OSError path",
        repo_path=str(make_repo(tmp_path)),
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, tmp_path)
    trace_file = Path(result.trace_path)
    events = [json.loads(line) for line in trace_file.read_text(encoding="utf-8").strip().splitlines()]

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.failed_count == 1
    assert result.verification.command_results[0].stderr_excerpt == exact_error
    assert events[2]["payload"]["stderr_excerpt"] == exact_error


def test_run_task_preview_executes_verification_commands_from_repo_path(tmp_path):
    repo_path = make_repo(tmp_path)
    (repo_path / "repo_only.txt").write_text("repo-relative", encoding="utf-8")
    command = (
        f"{PYTHON} -c "
        "\"from pathlib import Path; print(Path('repo_only.txt').read_text(encoding='utf-8'))\""
    )
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Repo-relative verification",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[command],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "completed"
    assert result.verification is not None
    assert result.verification.command_results[0].status == "passed"
    assert result.verification.command_results[0].stdout_excerpt == "repo-relative\n"


def test_run_task_preview_trims_completed_command_output_to_excerpt_limit(tmp_path):
    large_stdout = "x" * 2501
    command = f"{PYTHON} -c \"print('{large_stdout}')\""
    repo_path = make_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Trim large verification output",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[command],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "completed"
    assert result.verification is not None
    assert len(result.verification.command_results[0].stdout_excerpt) == 2000
    assert result.verification.command_results[0].stdout_excerpt == large_stdout[:2000]
