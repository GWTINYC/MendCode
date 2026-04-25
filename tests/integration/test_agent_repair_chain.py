import shlex
import subprocess
import sys
from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.agent.provider import AgentProviderStepInput, ProviderResponse
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


class RepairChainProvider:
    def __init__(self, *, command: str, patch: str, verify_after_patch: bool = True) -> None:
        self.command = command
        self.patch = patch
        self.verify_after_patch = verify_after_patch
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        index = len(self.calls)
        if index == 1:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "run_command",
                        "reason": "reproduce failing verification",
                        "args": {"command": self.command},
                    }
                ],
            )
        if index == 2:
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "patch_proposal",
                        "reason": "add should add operands",
                        "files_to_modify": ["calculator.py"],
                        "patch": self.patch,
                    }
                ],
            )
        if index == 3:
            command = self.command
            if not self.verify_after_patch:
                command = f"{PYTHON} -c \"raise SystemExit(1)\""
            return ProviderResponse(
                status="succeeded",
                actions=[
                    {
                        "type": "tool_call",
                        "action": "run_command",
                        "reason": "verify patch",
                        "args": {"command": command},
                    }
                ],
            )
        if index == 4:
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


def test_fake_provider_repair_chain_applies_patch_in_worktree_and_completes(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "add", "calculator.py"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "add calculator"], cwd=repo_path, check=True)
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
    provider = RepairChainProvider(command=command, patch=patch)

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            provider=provider,
            verification_commands=[command],
            step_budget=8,
            use_worktree=True,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.workspace_path is not None
    workspace_path = Path(result.workspace_path)
    assert target.read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
    assert (workspace_path / "calculator.py").read_text(encoding="utf-8") == (
        "def add(a, b):\n    return a + b\n"
    )
    assert "calculator.py" in result.steps[3].observation.payload["diff_stat"]
    assert len(provider.calls) == 5


def test_fake_provider_repair_chain_cannot_complete_after_failed_patch_verification(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "calculator.py"
    target.write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "add", "calculator.py"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "add calculator"], cwd=repo_path, check=True)
    command = f"{PYTHON} -c \"raise SystemExit(1)\""
    patch = """diff --git a/calculator.py b/calculator.py
--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    provider = RepairChainProvider(command=command, patch=patch, verify_after_patch=False)

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="fix add",
            provider=provider,
            verification_commands=[command],
            step_budget=8,
            use_worktree=True,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "Agent loop ended with failed observations"
