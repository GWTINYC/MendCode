import shlex
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from app.cli.main import app

runner = CliRunner()
PYTHON = shlex.quote(sys.executable)


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


def test_health_command_reports_agent_directories(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert "MendCode" in result.stdout
    assert "status" in result.stdout
    assert "traces" in result.stdout
    assert "workspace_root" in result.stdout


def test_fix_command_runs_agent_loop_and_reports_failure_insight(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)
    tests_dir = repo_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_calculator.py").write_text(
        "def test_add():\n    assert -1 == 5\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "tests/test_calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add failing test"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    command = (
        f"{PYTHON} -c "
        "\"print('FAILED tests/test_calculator.py::test_add - "
        "AssertionError: assert -1 == 5'); raise SystemExit(1)\""
    )

    result = runner.invoke(
        app,
        [
            "fix",
            "修复 pytest 失败",
            "--test",
            command,
            "--repo",
            str(repo_path),
        ],
        terminal_width=200,
    )

    assert result.exit_code == 0
    assert "Agent Fix" in result.stdout
    assert "修复 pytest 失败" in result.stdout
    assert "agent-" in result.stdout
    assert "status" in result.stdout
    assert "failed" in result.stdout
    assert "failed_node" in result.stdout
    assert "tests/test_calculator.py::test_add" in result.stdout
    assert "error_summary" in result.stdout
    assert "AssertionError: assert -1 == 5" in result.stdout
    assert "workspace_path" in result.stdout
    assert ".worktrees" in result.stdout
    assert "location_status" in result.stdout
    assert "location_steps" in result.stdout
    assert "read_file:succeeded" in result.stdout
    assert "search_code:succeeded" in result.stdout
    assert "trace_path" in result.stdout


def test_fix_command_reports_provider_failure_without_agent_loop(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "fix",
            "修复 pytest 失败",
            "--repo",
            str(repo_path),
        ],
        terminal_width=200,
    )

    assert result.exit_code != 0
    assert "Agent Fix" in result.stdout
    assert "provider failed" in result.stdout.lower()
    assert "at least one verification command is required" in result.stdout
    assert "agent-" not in result.stdout


def test_task_command_is_no_longer_registered() -> None:
    result = runner.invoke(app, ["task", "validate", "task.json"])

    assert result.exit_code != 0
    assert "No such command" in result.output
