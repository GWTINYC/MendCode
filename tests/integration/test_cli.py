import json
import shlex
import sys
from pathlib import Path

from typer.testing import CliRunner

from app.cli.main import app

runner = CliRunner()
PYTHON = shlex.quote(sys.executable)


def write_task_file(path: Path) -> Path:
    task_file = path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-001",
                "task_type": "ci_fix",
                "title": "Fix failing unit test",
                "repo_path": str(path),
                "entry_artifacts": {"log": "pytest failed"},
                "verification_commands": [f"{PYTHON} -c \"print('ok')\""],
                "allowed_tools": ["read_file", "search_code"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def write_failing_task_file(path: Path) -> Path:
    task_file = path / "task-fail.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-002",
                "task_type": "ci_fix",
                "title": "Fail verification",
                "repo_path": str(path),
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
    assert "Fix failing unit test" in result.stdout
    assert len(trace_files) == 1

    trace_payload = json.loads(trace_files[0].read_text(encoding="utf-8").strip())
    assert trace_payload["event_type"] == "task.show"
    assert trace_payload["payload"]["task_id"] == "demo-ci-001"
    assert trace_payload["payload"]["title"] == "Fix failing unit test"


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
    assert len(trace_files) == 1

    trace_path = str(trace_files[0])
    assert trace_path in result.stdout

    trace_lines = trace_files[0].read_text(encoding="utf-8").strip().splitlines()
    trace_events = [json.loads(line) for line in trace_lines]

    assert [event["event_type"] for event in trace_events] == [
        "run.started",
        "run.verification.started",
        "run.verification.command.completed",
        "run.completed",
    ]
    assert trace_events[0]["payload"]["task_id"] == "demo-ci-001"
    assert trace_events[0]["payload"]["task_type"] == "ci_fix"
    assert trace_events[0]["payload"]["summary"] == "Task preview started"
    assert trace_events[1]["payload"]["command_count"] == 1
    assert trace_events[2]["payload"]["status"] == "passed"
    assert trace_events[3]["payload"]["status"] == "completed"
    assert trace_events[3]["payload"]["task_type"] == "ci_fix"
    assert trace_events[3]["payload"]["summary"] == "Verification passed: 1/1 commands succeeded"


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
    assert "First failed command:" in result.stdout
    assert f'{PYTHON} -c "import sys; sys.exit(3)"' in result.stdout
