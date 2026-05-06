import json
import shlex
import subprocess
import sys
from pathlib import Path

from typer.testing import CliRunner

from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.cli.main import app
from app.tools.structured import ToolInvocation

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
                tool_invocations=[
                    ToolInvocation(
                        id="call_repo_status",
                        name="repo_status",
                        args={},
                        source="openai_tool_call",
                    )
                ],
            )
        if len(self.calls) == 2:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id="call_run_command",
                        name="run_command",
                        args={"command": step_input.verification_commands[0]},
                        source="openai_tool_call",
                    )
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
                tool_invocations=[
                    ToolInvocation(
                        id="call_apply_patch",
                        name="apply_patch",
                        args={
                            "files_to_modify": ["calculator.py"],
                            "patch": self.patch,
                        },
                        source="openai_tool_call",
                    )
                ],
            )
        if len(self.calls) == 2:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id="call_verify_patch",
                        name="run_command",
                        args={"command": self.command},
                        source="openai_tool_call",
                    )
                ],
            )
        if len(self.calls) == 3:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id="call_show_diff",
                        name="show_diff",
                        args={},
                        source="openai_tool_call",
                    )
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
                tool_invocations=[
                    ToolInvocation(
                        id="call_failed_verify",
                        name="run_command",
                        args={"command": self.command},
                        source="openai_tool_call",
                    )
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


def test_story_next_prints_highest_priority_unpassed_story(tmp_path: Path) -> None:
    plan_path = tmp_path / "tasks" / "context-v2" / "plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        """
{
  "branch_name": "feature/context-compaction-v2",
  "stories": [
    {
      "id": "MC-002",
      "title": "Lower priority",
      "priority": 20,
      "passes": false,
      "acceptance_criteria": ["second story works"],
      "verification_commands": ["pytest tests/unit/test_second.py -q"]
    },
    {
      "id": "MC-001",
      "title": "Add tokenizer-aware context budget",
      "priority": 10,
      "passes": false,
      "acceptance_criteria": ["budget uses model window"],
      "verification_commands": ["pytest tests/unit/test_context_manager.py -q"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["story", "next", str(plan_path)])

    assert result.exit_code == 0
    assert "MC-001" in result.stdout
    assert "Add tokenizer-aware context budget" in result.stdout
    assert "pytest tests/unit/test_context_manager.py -q" in result.stdout


def test_story_mark_passed_and_append_progress(tmp_path: Path) -> None:
    plan_path = tmp_path / "tasks" / "context-v2" / "plan.json"
    plan_path.parent.mkdir(parents=True)
    plan_path.write_text(
        """
{
  "branch_name": "feature/context-compaction-v2",
  "progress_path": "tasks/context-v2/progress.md",
  "stories": [
    {
      "id": "MC-001",
      "title": "Add tokenizer-aware context budget",
      "priority": 10,
      "passes": false,
      "acceptance_criteria": ["budget uses model window"],
      "verification_commands": ["pytest tests/unit/test_context_manager.py -q"]
    }
  ]
}
""".strip(),
        encoding="utf-8",
    )

    mark_result = runner.invoke(app, ["story", "mark-passed", str(plan_path), "MC-001"])
    progress_result = runner.invoke(
        app,
        [
            "story",
            "append-progress",
            str(plan_path),
            "MC-001",
            "--status",
            "passed",
            "--summary",
            "Implemented tokenizer-aware budget.",
            "--verification",
            "pytest tests/unit/test_context_manager.py -q",
            "--trace",
            "data/traces/run-123.jsonl",
            "--commit",
            "abc1234",
            "--learning",
            "Keep provider context compact.",
        ],
    )

    assert mark_result.exit_code == 0
    assert progress_result.exit_code == 0
    assert '"passes": true' in plan_path.read_text(encoding="utf-8")
    progress = (tmp_path / "tasks" / "context-v2" / "progress.md").read_text(
        encoding="utf-8"
    )
    assert "## MC-001 - passed" in progress
    assert "Implemented tokenizer-aware budget." in progress
    assert "Keep provider context compact." in progress


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


def test_benchmark_status_prints_manifest_coverage(tmp_path: Path) -> None:
    manifest_path = tmp_path / "benchmark.json"
    manifest_path.write_text(json.dumps(_benchmark_manifest_payload()), encoding="utf-8")

    result = runner.invoke(app, ["benchmark", "status", str(manifest_path)])

    assert result.exit_code == 0
    assert "quick" in result.stdout
    assert "case_count" in result.stdout
    assert "repository_inspection" in result.stdout
    assert "missing_target_categories" in result.stdout
    assert "none" in result.stdout


def test_benchmark_check_prints_result_coverage(tmp_path: Path) -> None:
    manifest_path = tmp_path / "benchmark.json"
    manifest_path.write_text(json.dumps(_benchmark_manifest_payload()), encoding="utf-8")
    result_path = tmp_path / "result.json"
    result_path.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "repo-list",
                        "passed": True,
                        "tool_chain_passed": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["benchmark", "check", str(manifest_path), str(result_path)])

    assert result.exit_code == 0
    assert "Benchmark Coverage" in result.stdout
    assert "missing_case_ids" in result.stdout
    assert "file-answer" in result.stdout
    assert "complete" in result.stdout
    assert "false" in result.stdout


def test_trace_analyze_session_writes_json_and_markdown(tmp_path: Path) -> None:
    conversation = tmp_path / "conversation.md"
    conversation.write_text(
        "\n".join(
            [
                "## User",
                "帮我查看当前文件夹里的文件",
                "## Assistant",
                "当前目录有 README.md。",
            ]
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    result = runner.invoke(
        app,
        ["trace", "analyze-session", str(conversation), "--output-dir", str(output_dir)],
    )

    assert result.exit_code == 0
    assert "Analysis reports written" in result.stdout
    assert (output_dir / "conversation.json").exists()
    assert (output_dir / "conversation.md").exists()
    assert "missing_directory_listing" in (
        output_dir / "conversation.json"
    ).read_text(encoding="utf-8")


def test_trace_analyze_session_json_format_only(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps(
            {
                "run_id": "run-1",
                "event_type": "agent.user_message",
                "message": "user",
                "payload": {"message": "查看 git status"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"

    result = runner.invoke(
        app,
        [
            "trace",
            "analyze-session",
            str(trace),
            "--output-dir",
            str(output_dir),
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "trace.json").exists()
    assert not (output_dir / "trace.md").exists()


def test_trace_analyze_session_rejects_llm_flag_for_first_version(
    tmp_path: Path,
) -> None:
    conversation = tmp_path / "conversation.md"
    conversation.write_text("## User\n列文件\n", encoding="utf-8")

    result = runner.invoke(app, ["trace", "analyze-session", str(conversation), "--llm"])

    assert result.exit_code != 0
    assert "--llm is reserved" in result.stdout


def _benchmark_manifest_payload() -> dict[str, object]:
    return {
        "name": "quick",
        "cases": [
            {
                "id": "repo-list",
                "category": "repository_inspection",
                "prompt": "列文件",
                "expected_tools": ["list_dir"],
            },
            {
                "id": "file-answer",
                "category": "file_question",
                "prompt": "最后一句",
                "expected_tools": ["read_file"],
            },
            {
                "id": "code-search",
                "category": "code_search",
                "prompt": "搜索",
                "expected_tools": ["rg"],
            },
            {
                "id": "git-status",
                "category": "git_status",
                "prompt": "git 状态",
                "expected_tools": ["git"],
            },
            {
                "id": "patch-fix",
                "category": "patch_repair",
                "prompt": "修复",
                "expected_tools": ["apply_patch"],
            },
            {
                "id": "danger",
                "category": "permission_safety",
                "prompt": "危险命令",
                "expected_tools": ["run_shell_command"],
                "expects_dangerous_block": True,
            },
            {
                "id": "memory",
                "category": "memory_context",
                "prompt": "记忆",
                "expected_tools": ["memory_search"],
            },
        ],
    }
