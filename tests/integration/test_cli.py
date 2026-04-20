import json
from pathlib import Path

from typer.testing import CliRunner

from app.cli.main import app


runner = CliRunner()


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
                "verification_commands": ["pytest -q"],
                "allowed_tools": ["read_file", "search_code"],
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


def test_task_validate_command_accepts_valid_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "validate", str(task_file)])

    assert result.exit_code == 0
    assert "Task file is valid" in result.stdout
    assert "demo-ci-001" in result.stdout


def test_task_show_writes_trace_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "show", str(task_file)])

    trace_dir = tmp_path / "data" / "traces"
    trace_files = list(trace_dir.glob("*.jsonl"))

    assert result.exit_code == 0
    assert "Fix failing unit test" in result.stdout
    assert len(trace_files) == 1
