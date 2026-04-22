import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.orchestrator.fixed_flow import load_fixed_flow_artifacts
from app.orchestrator.runner import run_task_preview
from app.schemas.task import TaskSpec
from app.schemas.verification import VerificationCommandResult
from app.workspace.worktree import WorkspaceCleanupResult

PYTHON = shlex.quote(sys.executable)


def init_git_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_path / "repo_only.txt").write_text("repo-relative", encoding="utf-8")
    subprocess.run(
        ["git", "add", "repo_only.txt"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


def build_settings(tmp_path: Path, cleanup_success_workspace: bool = False) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.1.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        tasks_dir=tmp_path / "data" / "tasks",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=cleanup_success_workspace,
    )


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
    result = run_task_preview(build_task(str(init_git_repo(tmp_path))), build_settings(tmp_path))

    assert result.task_id == "demo-ci-001"
    assert result.task_type == "ci_fix"
    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.verification is not None
    assert result.verification.status == "passed"
    assert result.summary == "Verification passed: 1/1 commands succeeded"


def test_run_task_preview_writes_started_and_completed_events(tmp_path):
    task = build_task(str(init_git_repo(tmp_path)))
    result = run_task_preview(task, build_settings(tmp_path))
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
        "run.workspace.cleanup",
        "run.completed",
    ]
    assert events[0]["payload"]["task_id"] == "demo-ci-001"
    assert events[1]["payload"]["status"] == "running"
    assert events[1]["payload"]["command_count"] == 1
    assert events[2]["payload"]["command"] == task.verification_commands[0]
    assert events[2]["payload"]["stdout_excerpt"] == "ok\n"
    assert events[2]["payload"]["stderr_excerpt"] == ""
    assert events[3]["payload"]["cleanup_attempted"] is False
    assert events[4]["payload"]["status"] == "completed"


def test_run_task_preview_uses_trace_recorder_return_path(tmp_path, monkeypatch):
    custom_trace_path = tmp_path / "nested" / "preview-custom.jsonl"

    def fake_record(self, event):
        custom_trace_path.parent.mkdir(parents=True, exist_ok=True)
        with custom_trace_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.model_dump(mode="json")))
            handle.write("\n")
        return custom_trace_path

    monkeypatch.setattr("app.orchestrator.runner.TraceRecorder.record", fake_record)

    result = run_task_preview(build_task(str(init_git_repo(tmp_path))), build_settings(tmp_path))

    assert result.trace_path == str(custom_trace_path)
    assert Path(result.trace_path).exists()


def test_run_task_preview_marks_run_passed_when_all_commands_succeed(tmp_path):
    repo_path = init_git_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Verify success path",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.verification is not None
    assert result.verification.status == "passed"
    assert result.verification.passed_count == 1
    assert result.verification.failed_count == 0
    assert result.summary == "Verification passed: 1/1 commands succeeded"


def test_load_fixed_flow_artifacts_rejects_blank_read_target_path():
    with pytest.raises(ValidationError) as excinfo:
        load_fixed_flow_artifacts(
            {
                "read_target_path": "   ",
                "old_text": "demo",
                "new_text": "fixed",
            }
        )

    assert "read_target_path" in str(excinfo.value)


@pytest.mark.parametrize(
    "payload, expected_fragment",
    [
        (
            {
                "read_target_path": "target.txt",
                "read_start_line": 0,
                "old_text": "demo",
                "new_text": "fixed",
            },
            "read_start_line",
        ),
        (
            {
                "read_target_path": "target.txt",
                "read_end_line": 0,
                "old_text": "demo",
                "new_text": "fixed",
            },
            "read_end_line",
        ),
        (
            {
                "read_target_path": "target.txt",
                "read_start_line": 5,
                "read_end_line": 4,
                "old_text": "demo",
                "new_text": "fixed",
            },
            "read_end_line",
        ),
    ],
)
def test_load_fixed_flow_artifacts_rejects_invalid_read_line_bounds(payload, expected_fragment):
    with pytest.raises(ValidationError) as excinfo:
        load_fixed_flow_artifacts(payload)

    assert expected_fragment in str(excinfo.value)


@pytest.mark.xfail(reason="runner wiring pending for fixed-flow inputs", strict=False)
def test_run_task_preview_fails_when_fixed_flow_inputs_are_missing(tmp_path):
    repo_path = init_git_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Missing fixed-flow inputs",
        repo_path=str(repo_path),
        entry_artifacts={
            "old_text": "demo",
            "new_text": "fixed",
        },
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "failed"
    assert result.current_step == "summarize"
    assert (
        result.summary
        == "Fixed-flow input invalid: either read_target_path or search_query is required"
    )


@pytest.mark.xfail(reason="runner wiring pending for fixed-flow inputs", strict=False)
def test_run_task_preview_accepts_direct_target_path_without_search_query(tmp_path):
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "target.txt"
    target.write_text("wrong\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add target"], cwd=repo_path, check=True, capture_output=True, text=True)

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Direct path fixed flow",
        repo_path=str(repo_path),
        entry_artifacts={
            "read_target_path": "target.txt",
            "old_text": "wrong",
            "new_text": "fixed",
        },
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "completed"
    assert result.selected_files == ["target.txt"]


def test_run_task_preview_marks_run_failed_when_a_command_fails(tmp_path):
    repo_path = init_git_repo(tmp_path)
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

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.status == "failed"
    assert result.verification.passed_count == 1
    assert result.verification.failed_count == 1
    assert "Verification failed" in result.summary


def test_run_task_preview_fails_when_no_verification_commands_are_defined(tmp_path):
    repo_path = init_git_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="No verification commands",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.failed_count == 1
    assert result.summary == "Verification failed: no verification commands provided"


def test_run_task_preview_records_exact_oserror_text_without_trimming(tmp_path, monkeypatch):
    exact_error = "x" * 2501
    repo_path = init_git_repo(tmp_path)

    def fake_execute_verification_command(command, cwd, policy):
        return {
            "command": command,
            "exit_code": -1,
            "status": "failed",
            "duration_ms": 0,
            "stdout_excerpt": "",
            "stderr_excerpt": exact_error,
            "timed_out": False,
            "rejected": False,
            "cwd": str(cwd),
        }

    monkeypatch.setattr(
        "app.orchestrator.runner.execute_verification_command",
        lambda command, cwd, policy: VerificationCommandResult(
            **fake_execute_verification_command(command, cwd, policy)
        ),
    )

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="OSError path",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))
    trace_file = Path(result.trace_path)
    trace_lines = trace_file.read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in trace_lines]

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.failed_count == 1
    assert result.verification.command_results[0].stderr_excerpt == exact_error
    assert events[2]["payload"]["stderr_excerpt"] == exact_error


def test_run_task_preview_executes_in_worktree_and_records_cleanup(tmp_path):
    repo_path = init_git_repo(tmp_path)
    settings = build_settings(tmp_path)
    command = (
        f"{PYTHON} -c "
        "\"from pathlib import Path; print(Path('repo_only.txt').read_text(encoding='utf-8'))\""
    )
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Repo-relative verification",
        repo_path=str(repo_path),
        base_ref=None,
        entry_artifacts={},
        verification_commands=[command],
    )

    result = run_task_preview(task, settings)
    trace_lines = Path(result.trace_path).read_text(encoding="utf-8").strip().splitlines()
    events = [json.loads(line) for line in trace_lines]

    assert result.status == "completed"
    assert result.workspace_path is not None
    assert Path(result.workspace_path) != repo_path
    assert events[-2]["event_type"] == "run.workspace.cleanup"
    assert events[-2]["payload"]["cleanup_attempted"] is False
    assert result.verification is not None
    assert result.verification.command_results[0].status == "passed"
    assert result.verification.command_results[0].stdout_excerpt == "repo-relative\n"
    assert result.verification.command_results[0].cwd == result.workspace_path


def test_run_task_preview_cleans_success_workspace_when_enabled(tmp_path):
    repo_path = init_git_repo(tmp_path)
    settings = build_settings(tmp_path, cleanup_success_workspace=True)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Cleanup success workspace",
        repo_path=str(repo_path),
        base_ref=None,
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, settings)

    assert result.status == "completed"
    assert result.workspace_path is not None
    assert not Path(result.workspace_path).exists()


def test_run_task_preview_reports_workspace_setup_failure_detail(tmp_path, monkeypatch):
    repo_path = init_git_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Workspace setup failure",
        repo_path=str(repo_path),
        base_ref="missing-ref",
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    monkeypatch.setattr(
        "app.orchestrator.runner.prepare_worktree",
        lambda **kwargs: (_ for _ in ()).throw(
            subprocess.CalledProcessError(
                returncode=128,
                cmd=["git", "worktree", "add"],
                stderr="fatal: invalid reference: missing-ref\n",
            )
        ),
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "failed"
    assert result.workspace_path is None
    assert result.verification is None
    assert "Workspace setup failed:" in result.summary
    assert "fatal: invalid reference: missing-ref" in result.summary


def test_run_task_preview_reports_cleanup_failure_when_enabled(tmp_path, monkeypatch):
    repo_path = init_git_repo(tmp_path)
    settings = build_settings(tmp_path, cleanup_success_workspace=True)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Cleanup failure",
        repo_path=str(repo_path),
        base_ref=None,
        entry_artifacts={},
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    monkeypatch.setattr(
        "app.orchestrator.runner.cleanup_worktree",
        lambda **kwargs: WorkspaceCleanupResult(
            workspace_path=str(tmp_path / ".worktrees" / "preview-demo"),
            cleanup_attempted=True,
            cleanup_succeeded=False,
            cleanup_reason="git worktree remove failed",
        ),
    )

    result = run_task_preview(task, settings)

    assert result.status == "completed"
    assert result.workspace_path is not None
    assert "Verification passed: 1/1 commands succeeded" in result.summary
    assert "workspace cleanup failed: git worktree remove failed" in result.summary


def test_run_task_preview_trims_completed_command_output_to_excerpt_limit(tmp_path):
    large_stdout = "x" * 2501
    command = f"{PYTHON} -c \"print('{large_stdout}')\""
    repo_path = init_git_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Trim large verification output",
        repo_path=str(repo_path),
        entry_artifacts={},
        verification_commands=[command],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "completed"
    assert result.verification is not None
    assert len(result.verification.command_results[0].stdout_excerpt) == 2000
    assert result.verification.command_results[0].stdout_excerpt == large_stdout[:2000]
