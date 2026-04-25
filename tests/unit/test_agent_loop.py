import shlex
import subprocess
import sys
from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.config.settings import Settings

PYTHON = shlex.quote(sys.executable)


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )


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
    return repo_path


def test_agent_loop_executes_allowed_search_code_action(tmp_path: Path) -> None:
    (tmp_path / "calculator.py").write_text(
        "def add(a, b):\n    return a + b\n",
        encoding="utf-8",
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="find add",
            actions=[
                {
                    "type": "tool_call",
                    "action": "search_code",
                    "reason": "locate implementation",
                    "args": {"query": "def add", "glob": "*.py"},
                },
                {"type": "final_response", "status": "completed", "summary": "done"},
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.steps[0].observation.status == "succeeded"
    assert result.steps[0].observation.payload["total_matches"] == 1
    assert result.trace_path is not None


def test_agent_loop_turns_invalid_action_into_rejected_observation(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="bad action",
            actions=[
                {
                    "type": "tool_call",
                    "action": "delete_repo",
                    "reason": "bad",
                    "args": {},
                }
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.summary == "Invalid MendCode action"


def test_agent_loop_returns_confirmation_request_when_permission_requires_it(
    tmp_path: Path,
) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="safe mode command",
            permission_mode="safe",
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "run tests",
                    "args": {"command": "pytest -q"},
                }
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "needs_user_confirmation"
    assert result.steps[0].action.type == "user_confirmation_request"
    assert result.steps[0].observation.status == "rejected"


def test_agent_loop_does_not_complete_after_failed_tool_observation(tmp_path: Path) -> None:
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="failed verification",
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "run failing command",
                    "args": {"command": "python -c 'raise SystemExit(1)'"},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "done",
                },
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"


def test_agent_loop_applies_patch_proposal_in_worktree_then_verifies(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
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
    command = (
        f"{PYTHON} -c "
        "\"import calculator; "
        "raise SystemExit(0 if calculator.add(2, 3) == 5 else 1)\""
    )
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            use_worktree=True,
            actions=[
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "reproduce failing verification",
                    "args": {"command": command},
                },
                {
                    "type": "patch_proposal",
                    "reason": "add should add operands",
                    "files_to_modify": ["calculator.py"],
                    "patch": patch,
                },
                {
                    "type": "tool_call",
                    "action": "run_command",
                    "reason": "verify patch",
                    "args": {"command": command},
                },
                {
                    "type": "tool_call",
                    "action": "show_diff",
                    "reason": "summarize changed files",
                    "args": {},
                },
                {
                    "type": "final_response",
                    "status": "completed",
                    "summary": "verification passed",
                },
            ],
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.workspace_path is not None
    workspace_path = Path(result.workspace_path)
    assert workspace_path != repo_path
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
    assert (workspace_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a + b\n"
    )
    assert result.steps[1].observation.status == "succeeded"
    assert result.steps[1].observation.payload["files_to_modify"] == ["calculator.py"]
    assert "calculator.py" in result.steps[3].observation.payload["diff_stat"]
