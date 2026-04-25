import shlex
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from app.agent.provider import AgentProviderStepInput, ProviderResponse
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


class FakeOpenAICompatibleProvider:
    def __init__(self) -> None:
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) == 1:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "repo_status",
                        "reason": "inspect repo",
                        "args": {},
                    }
                ],
            )
        if len(self.calls) == 2:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "run_command",
                        "reason": "run verification",
                        "args": {"command": step_input.verification_commands[0]},
                    }
                ],
            )
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "fake openai-compatible provider completed",
                }
            ],
        )


class PatchReviewProvider:
    def __init__(self, *, command: str, patch: str) -> None:
        self.command = command
        self.patch = patch
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) == 1:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "patch_proposal",
                        "reason": "make add return the sum",
                        "files_to_modify": ["calculator.py"],
                        "patch": self.patch,
                    }
                ],
            )
        if len(self.calls) == 2:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "run_command",
                        "reason": "verify patch",
                        "args": {"command": self.command},
                    }
                ],
            )
        if len(self.calls) == 3:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "show_diff",
                        "reason": "summarize changed files",
                        "args": {},
                    }
                ],
            )
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "repair verified",
                }
            ],
        )


class FailedReviewProvider:
    def __init__(self, *, command: str) -> None:
        self.command = command
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) == 1:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "run_command",
                        "reason": "run failing verification",
                        "args": {"command": self.command},
                    }
                ],
            )
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "failed",
                    "summary": "verification failed",
                }
            ],
        )


def add_calculator_repo_file(repo_path: Path) -> None:
    (repo_path / "calculator.py").write_text(
        "def add(a, b):\n    return a - b\n",
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "add", "calculator.py"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add calculator"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )


def calculator_patch() -> str:
    return """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""


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


def test_fix_command_reports_provider_configuration_error(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("MENDCODE_PROVIDER", "openai-compatible")
    monkeypatch.delenv("MENDCODE_MODEL", raising=False)
    monkeypatch.delenv("MENDCODE_BASE_URL", raising=False)
    monkeypatch.delenv("MENDCODE_API_KEY", raising=False)
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "fix",
            "修复 pytest 失败",
            "--test",
            f"{PYTHON} -c \"raise SystemExit(0)\"",
            "--repo",
            str(repo_path),
        ],
        terminal_width=200,
    )

    assert result.exit_code != 0
    assert "Provider Configuration" in result.stdout
    assert "MENDCODE_MODEL" in result.stdout
    assert "agent-" not in result.stdout


def test_fix_command_can_use_openai_compatible_provider_without_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setenv("MENDCODE_PROVIDER", "openai-compatible")
    monkeypatch.setenv("MENDCODE_MODEL", "test-model")
    monkeypatch.setenv("MENDCODE_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("MENDCODE_API_KEY", "secret-key")
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    fake_provider = FakeOpenAICompatibleProvider()
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: fake_provider)
    repo_path = init_git_repo(tmp_path)

    result = runner.invoke(
        app,
        [
            "fix",
            "修复 pytest 失败",
            "--test",
            f"{PYTHON} -c \"raise SystemExit(0)\"",
            "--repo",
            str(repo_path),
        ],
        terminal_width=200,
    )

    assert result.exit_code == 0
    assert "fake openai-compatible provider completed" in result.stdout
    assert len(fake_provider.calls) == 3
    assert fake_provider.calls[0].verification_commands


def test_no_args_command_runs_minimal_tui_turn(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    fake_provider = FakeOpenAICompatibleProvider()
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: fake_provider)
    repo_path = init_git_repo(tmp_path)
    command = f"{PYTHON} -c \"raise SystemExit(0)\""

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(
            app,
            [],
            input=f"修复 pytest 失败\n{command}\n",
            terminal_width=200,
        )

    assert result.exit_code == 0
    assert "MendCode" in result.stdout
    assert "repo:" in result.stdout
    assert "mode: guided" in result.stdout
    assert "Tool Summary" in result.stdout
    assert "Review" in result.stdout
    assert "fake openai-compatible provider completed" in result.stdout
    assert "view_trace" in result.stdout
    assert len(fake_provider.calls) == 3


def test_no_args_command_launches_textual_app_in_tty(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    repo_path = init_git_repo(tmp_path)
    launched: dict[str, object] = {}

    def fake_run_textual_app(*, repo_path: Path, settings) -> None:
        launched["repo_path"] = repo_path
        launched["provider"] = settings.provider

    monkeypatch.setattr("app.cli.main._is_interactive_terminal", lambda: True)
    monkeypatch.setattr("app.cli.main._run_textual_app", fake_run_textual_app)

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(app, [], terminal_width=200)

    assert result.exit_code == 0
    assert launched == {"repo_path": repo_path.resolve(), "provider": "scripted"}


def test_no_args_command_can_apply_verified_worktree_changes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)
    add_calculator_repo_file(repo_path)
    command = (
        f"{PYTHON} -c "
        "\"import calculator; "
        "raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)\""
    )
    provider = PatchReviewProvider(command=command, patch=calculator_patch())
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: provider)

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(
            app,
            [],
            input=f"修复 add\n{command}\napply\n",
            terminal_width=200,
        )

    assert result.exit_code == 0
    assert "Review Actions" in result.stdout
    assert "Applied worktree changes to main workspace" in result.stdout
    assert (repo_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a + b\n"
    )


def test_no_args_command_can_view_diff_then_discard_worktree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)
    add_calculator_repo_file(repo_path)
    command = (
        f"{PYTHON} -c "
        "\"import calculator; "
        "raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)\""
    )
    provider = PatchReviewProvider(command=command, patch=calculator_patch())
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: provider)

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(
            app,
            [],
            input=f"修复 add\n{command}\nview_diff\ndiscard\n",
            terminal_width=200,
        )

    assert result.exit_code == 0
    assert "-    return a - b" in result.stdout
    assert "+    return a + b" in result.stdout
    assert "Discarded worktree" in result.stdout
    assert not list((tmp_path / ".worktrees").glob("agent-*"))


def test_no_args_command_does_not_allow_apply_for_failed_turn(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)
    add_calculator_repo_file(repo_path)
    command = f"{PYTHON} -c \"raise SystemExit(1)\""
    provider = FailedReviewProvider(command=command)
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: provider)

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(
            app,
            [],
            input=f"修复 add\n{command}\napply\n",
            terminal_width=200,
        )

    assert result.exit_code == 0
    assert "Action not available: apply" in result.stdout
    assert "Applied worktree changes to main workspace" not in result.stdout
    assert (repo_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a - b\n"
    )


def test_no_args_command_reports_failure_insight_and_location_steps(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    fake_provider = FakeOpenAICompatibleProvider()
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: fake_provider)
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

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(
            app,
            [],
            input=f"修复 pytest 失败\n{command}\n",
            terminal_width=200,
        )

    assert result.exit_code == 0
    assert "failed_node" in result.stdout
    assert "tests/test_calculator.py::test_add" in result.stdout
    assert "error_summary" in result.stdout
    assert "AssertionError: assert -1 == 5" in result.stdout
    assert "location_status" in result.stdout
    assert "location_steps" in result.stdout
    assert "read_file:succeeded" in result.stdout
    assert "search_code:succeeded" in result.stdout


def test_no_args_command_rejects_empty_verification_command(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    fake_provider = FakeOpenAICompatibleProvider()
    monkeypatch.setattr("app.cli.main.build_agent_provider", lambda settings: fake_provider)
    repo_path = init_git_repo(tmp_path)

    with monkeypatch.context() as context:
        context.chdir(repo_path)
        result = runner.invoke(
            app,
            [],
            input="修复 pytest 失败\n   \n",
            terminal_width=200,
        )

    assert result.exit_code != 0
    assert "Verification command is required" in result.stdout
    assert fake_provider.calls == []


def test_task_command_is_no_longer_registered() -> None:
    result = runner.invoke(app, ["task", "validate", "task.json"])

    assert result.exit_code != 0
    assert "No such command" in result.output
