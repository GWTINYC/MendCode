import json
import shlex
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

repo_root = Path(__file__).resolve().parents[2]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from app.cli.main import app  # noqa: E402

runner = CliRunner()
PYTHON = shlex.quote(sys.executable)
demo_fixture_root = repo_root / "data" / "tasks" / "demos"


def init_git_repo(path: Path) -> Path:
    repo_path = path / "repo"
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
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
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


def write_task_file(path: Path) -> Path:
    repo_path = init_git_repo(path)
    (repo_path / "target.txt").write_text("wrong\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "target.txt"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add target"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )

    task_file = path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-001",
                "task_type": "ci_fix",
                "title": "Fixed-flow demo repair",
                "repo_path": str(repo_path),
                "entry_artifacts": {
                    "search_query": "wrong",
                    "target_path_glob": "*.txt",
                    "old_text": "wrong",
                    "new_text": "fixed",
                },
                "verification_commands": [
                    f"{PYTHON} -c "
                    "\"from pathlib import Path; import sys; "
                    "sys.exit(0 if Path('target.txt').read_text(encoding='utf-8') == "
                    "'fixed\\n' else 1)\""
                ],
                "allowed_tools": ["read_file", "search_code", "apply_patch"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def write_unauthorized_tool_task_file(path: Path) -> Path:
    repo_path = init_git_repo(path)
    (repo_path / "target.txt").write_text("wrong\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "target.txt"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add target"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )

    task_file = path / "task-unauthorized.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-unauthorized",
                "task_type": "ci_fix",
                "title": "Unauthorized fixed-flow demo",
                "repo_path": str(repo_path),
                "entry_artifacts": {
                    "search_query": "wrong",
                    "target_path_glob": "*.txt",
                    "old_text": "wrong",
                    "new_text": "fixed",
                },
                "verification_commands": [f"{PYTHON} -c \"print('ok')\""],
                "allowed_tools": ["read_file", "apply_patch"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def configure_repo_native_demo_env(monkeypatch) -> Path:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(repo_root))
    monkeypatch.chdir(repo_root)
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    return demo_fixture_root


def extract_table_value(stdout: str, field: str) -> str:
    needle = f"│ {field}"
    for line in stdout.splitlines():
        if needle in line:
            parts = [part.strip() for part in line.split("│")]
            if len(parts) >= 4 and parts[1] == field:
                return parts[2]
    raise AssertionError(f"Could not find field {field!r} in stdout:\n{stdout}")


def write_failing_task_file(path: Path) -> Path:
    repo_path = init_git_repo(path)
    task_file = path / "task-fail.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-002",
                "task_type": "ci_fix",
                "title": "Fail verification",
                "repo_path": str(repo_path),
                "entry_artifacts": {},
                "verification_commands": [f"{PYTHON} -c \"import sys; sys.exit(3)\""],
                "allowed_tools": ["read_file"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def test_health_command_reports_status(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert "MendCode" in result.stdout
    assert "status" in result.stdout
    assert "traces" in result.stdout


def test_task_validate_command_accepts_valid_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "validate", str(task_file)])

    assert result.exit_code == 0
    assert "Task file is valid" in result.stdout
    assert "demo-ci-001" in result.stdout


def test_task_validate_accepts_each_demo_fixture(monkeypatch):
    demo_dir = configure_repo_native_demo_env(monkeypatch)
    fixture_cases = [
        (demo_dir / "success.json", "demo-ci-success"),
        (demo_dir / "unauthorized-tool.json", "demo-ci-unauthorized-tool"),
        (demo_dir / "ambiguous-search.json", "demo-ci-ambiguous-search"),
        (demo_dir / "verification-fail.json", "demo-ci-verification-fail"),
    ]

    for fixture_path, task_id in fixture_cases:
        result = runner.invoke(app, ["task", "validate", str(fixture_path)])

        assert result.exit_code == 0
        assert "Task file is valid" in result.stdout
        assert task_id in result.stdout


def test_task_show_accepts_success_demo_fixture(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "success.json"

    result = runner.invoke(app, ["task", "show", str(fixture_path)])

    assert result.exit_code == 0
    assert "demo-ci-success" in result.stdout
    assert "Successful fixed-flow README repair" in result.stdout
    trace_path = Path(extract_table_value(result.stdout, "trace_path"))
    assert trace_path.is_relative_to(repo_root / "data" / "traces")
    assert trace_path.exists()


def test_task_validate_missing_file_returns_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    missing_file = tmp_path / "missing.json"

    result = runner.invoke(app, ["task", "validate", str(missing_file)])

    assert result.exit_code != 0
    assert f"Task file not found: {missing_file}" in result.stdout


def test_task_validate_directory_returns_read_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    result = runner.invoke(app, ["task", "validate", str(tmp_path)])

    assert result.exit_code != 0
    assert "Task file could not be read" in result.stdout


def test_task_show_writes_trace_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "show", str(task_file)])

    trace_dir = tmp_path / "data" / "traces"
    trace_files = list(trace_dir.glob("*.jsonl"))

    assert result.exit_code == 0
    assert "Fixed-flow demo repair" in result.stdout
    assert len(trace_files) == 1

    trace_payload = json.loads(trace_files[0].read_text(encoding="utf-8").strip())
    assert trace_payload["event_type"] == "task.show"
    assert trace_payload["payload"]["task_id"] == "demo-ci-001"
    assert trace_payload["payload"]["title"] == "Fixed-flow demo repair"


def test_task_run_writes_trace_and_prints_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    trace_files = sorted((tmp_path / "data" / "traces").glob("preview-*.jsonl"))

    assert result.exit_code == 0
    assert "Task Run" in result.stdout
    assert "demo-ci-001" in result.stdout
    assert "summarize" in result.stdout
    assert "completed" in result.stdout
    assert "passed_count" in result.stdout
    assert "failed_count" in result.stdout
    assert "selected_files" in result.stdout
    assert "applied_patch" in result.stdout
    assert "workspace_path" in result.stdout
    assert "target.txt" in result.stdout
    assert "yes" in result.stdout
    assert len(trace_files) == 1

    trace_path = str(trace_files[0])
    assert trace_path in result.stdout

    trace_lines = trace_files[0].read_text(encoding="utf-8").strip().splitlines()
    trace_events = [json.loads(line) for line in trace_lines]

    assert "run.workspace.cleanup" in [event["event_type"] for event in trace_events]
    assert trace_events[0]["payload"]["task_id"] == "demo-ci-001"
    assert trace_events[0]["payload"]["task_type"] == "ci_fix"
    assert trace_events[0]["payload"]["summary"] == "Task preview started"
    assert trace_events[0]["payload"]["workspace_path"].startswith(
        str(tmp_path / ".worktrees" / "preview-")
    )
    assert trace_events[1]["event_type"] == "run.tool.started"
    assert trace_events[1]["payload"]["tool_name"] == "search_code"
    assert trace_events[2]["event_type"] == "run.tool.completed"
    assert trace_events[2]["payload"]["tool_name"] == "search_code"
    assert trace_events[7]["payload"]["command_count"] == 1
    assert trace_events[8]["payload"]["status"] == "passed"
    assert trace_events[-1]["payload"]["status"] == "completed"
    assert trace_events[-1]["payload"]["task_type"] == "ci_fix"
    assert trace_events[-1]["payload"]["summary"] == "Verification passed: 1/1 commands succeeded"


def test_task_run_prints_fixed_flow_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    assert result.exit_code == 0
    assert "selected_files" in result.stdout
    assert "applied_patch" in result.stdout
    assert "target.txt" in result.stdout
    assert "yes" in result.stdout


def test_task_run_reports_passed_verification(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    assert result.exit_code == 0
    assert "passed_count" in result.stdout
    assert "failed_count" in result.stdout
    assert "1" in result.stdout
    assert "Verification passed: 1/1 commands succeeded" in result.stdout


def test_task_run_reports_failed_verification_without_cli_crash(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    task_file = write_failing_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    assert result.exit_code == 0
    assert "failed" in result.stdout
    assert "passed_count" in result.stdout
    assert "failed_count" in result.stdout
    assert "First non-passed command: failed" in result.stdout
    assert f'{PYTHON} -c "import sys; sys.exit(3)"' in result.stdout


def test_task_run_reports_unauthorized_tool_stage(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    task_file = write_unauthorized_tool_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    assert result.exit_code == 0
    assert "failed" in result.stdout
    assert "locate" in result.stdout
    assert "Unable to run search_code" in result.stdout


def test_success_demo_completes(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "success.json"

    result = runner.invoke(app, ["task", "run", str(fixture_path)], terminal_width=200)

    assert result.exit_code == 0
    assert "demo-ci-success" in result.stdout
    assert "completed" in result.stdout
    assert "summarize" in result.stdout
    assert "Verification passed: 1/1 commands succeeded" in result.stdout

    trace_path = Path(extract_table_value(result.stdout, "trace_path"))
    workspace_path = Path(extract_table_value(result.stdout, "workspace_path"))
    assert trace_path.is_relative_to(repo_root / "data" / "traces")
    assert workspace_path.is_relative_to(repo_root / ".worktrees")
    assert trace_path.exists()
    trace_events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert trace_events[0]["payload"]["task_id"] == "demo-ci-success"
    assert trace_events[0]["payload"]["workspace_path"].startswith(
        str(repo_root / ".worktrees" / "preview-")
    )


def test_ambiguous_search_demo(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "ambiguous-search.json"

    result = runner.invoke(app, ["task", "run", str(fixture_path)], terminal_width=200)

    assert result.exit_code == 0
    assert "demo-ci-ambiguous-search" in result.stdout
    assert "failed" in result.stdout
    assert "search_code returned 2 candidate files" in result.stdout

    trace_path = Path(extract_table_value(result.stdout, "trace_path"))
    workspace_path = Path(extract_table_value(result.stdout, "workspace_path"))
    assert trace_path.is_relative_to(repo_root / "data" / "traces")
    assert workspace_path.is_relative_to(repo_root / ".worktrees")
    assert trace_path.exists()
    trace_events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert trace_events[0]["payload"]["task_id"] == "demo-ci-ambiguous-search"
    assert trace_events[0]["payload"]["workspace_path"].startswith(
        str(repo_root / ".worktrees" / "preview-")
    )


def test_unauthorized_tool_stage(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "unauthorized-tool.json"

    result = runner.invoke(app, ["task", "run", str(fixture_path)], terminal_width=200)

    assert result.exit_code == 0
    assert "demo-ci-unauthorized-tool" in result.stdout
    assert "failed" in result.stdout
    assert "Unable to run search_code" in result.stdout

    trace_path = Path(extract_table_value(result.stdout, "trace_path"))
    workspace_path = Path(extract_table_value(result.stdout, "workspace_path"))
    assert trace_path.is_relative_to(repo_root / "data" / "traces")
    assert workspace_path.is_relative_to(repo_root / ".worktrees")
    assert trace_path.exists()
    trace_events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert trace_events[0]["payload"]["task_id"] == "demo-ci-unauthorized-tool"
    assert trace_events[0]["payload"]["workspace_path"].startswith(
        str(repo_root / ".worktrees" / "preview-")
    )


def test_verification_fail(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "verification-fail.json"

    result = runner.invoke(app, ["task", "run", str(fixture_path)], terminal_width=200)

    assert result.exit_code == 0
    assert "demo-ci-verification-fail" in result.stdout
    assert "failed" in result.stdout
    assert "Verification failed" in result.stdout

    trace_path = Path(extract_table_value(result.stdout, "trace_path"))
    workspace_path = Path(extract_table_value(result.stdout, "workspace_path"))
    assert trace_path.is_relative_to(repo_root / "data" / "traces")
    assert workspace_path.is_relative_to(repo_root / ".worktrees")
    assert trace_path.exists()
    trace_events = [
        json.loads(line)
        for line in trace_path.read_text(encoding="utf-8").splitlines()
    ]
    assert trace_events[0]["payload"]["task_id"] == "demo-ci-verification-fail"
    assert trace_events[0]["payload"]["workspace_path"].startswith(
        str(repo_root / ".worktrees" / "preview-")
    )


def test_readme_references_demo_task_suite_paths():
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    expected_paths = [
        "data/tasks/demos/success.json",
        "data/tasks/demos/unauthorized-tool.json",
        "data/tasks/demos/ambiguous-search.json",
        "data/tasks/demos/verification-fail.json",
    ]

    for path in expected_paths:
        assert path in readme

    assert "data/tasks/demo.json" not in readme
