# Phase 1B Command Policy And Worktree Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a controlled verification execution boundary and isolated git worktree workspace so `task run` executes verification commands under policy in a per-run workspace instead of directly in the repository root.

**Architecture:** Keep the existing CLI and runner entrypoints, but move execution concerns out of `app/orchestrator/runner.py`. Add a small `app/workspace/` package with a command policy, single-command executor, and git worktree manager; extend schemas/settings to carry workspace-aware state; then wire the runner and CLI onto those new boundaries.

**Tech Stack:** Python 3.11, subprocess, pathlib, Pydantic v2, Typer, pytest, git CLI, rich

---

## File Map

- `app/schemas/task.py`: add optional `base_ref` so tasks can request a worktree starting point without expanding scope beyond one repo.
- `app/schemas/verification.py`: expand command-result semantics to distinguish `passed`, `failed`, `timed_out`, and `rejected`.
- `app/schemas/run_state.py`: expose `workspace_path` on the final run state.
- `app/config/settings.py`: add `workspace_root`, `verification_timeout_seconds`, and `cleanup_success_workspace`.
- `app/core/paths.py`: ensure the workspace root is created alongside `data/tasks` and `data/traces`.
- `app/workspace/command_policy.py`: validate command membership and allowed working directory boundaries.
- `app/workspace/executor.py`: execute one verification command with timeout, output trimming, and policy enforcement.
- `app/workspace/worktree.py`: create and optionally clean up detached git worktrees under `.worktrees/`.
- `app/orchestrator/runner.py`: orchestrate workspace setup, command execution, cleanup, trace emission, and state assembly.
- `app/cli/main.py`: pass `Settings` into the runner and print `workspace_path`.
- `tests/unit/test_task_schema.py`, `tests/unit/test_verification_schema.py`, `tests/unit/test_run_state.py`, `tests/unit/test_settings.py`: lock the new schema/config contracts.
- `tests/unit/test_command_policy.py`, `tests/unit/test_executor.py`, `tests/unit/test_worktree.py`: cover the new workspace package in isolation.
- `tests/unit/test_runner.py`, `tests/integration/test_cli.py`: cover the end-to-end orchestration changes and CLI output contract.
- `README.md`, `MendCode_开发方案.md`, `MendCode_问题记录.md`: sync docs after the implementation is stable.

### Task 1: Extend Schemas And Settings For Workspace-Aware Execution

**Files:**
- Modify: `app/schemas/task.py`
- Modify: `app/schemas/verification.py`
- Modify: `app/schemas/run_state.py`
- Modify: `app/config/settings.py`
- Modify: `app/core/paths.py`
- Modify: `tests/unit/test_task_schema.py`
- Modify: `tests/unit/test_verification_schema.py`
- Modify: `tests/unit/test_run_state.py`
- Modify: `tests/unit/test_settings.py`
- Test: `tests/unit/test_task_schema.py`
- Test: `tests/unit/test_verification_schema.py`
- Test: `tests/unit/test_run_state.py`
- Test: `tests/unit/test_settings.py`

- [ ] **Step 1: Write the failing schema and settings tests**

Add these tests to the existing files.

`tests/unit/test_task_schema.py`

```python
def test_task_spec_defaults_base_ref_to_none(tmp_path):
    payload = {
        "task_id": "default-base-ref-001",
        "task_type": "ci_fix",
        "title": "Defaults base_ref",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "ok"},
        "verification_commands": ["pytest -q"],
    }

    task = TaskSpec.model_validate(payload)

    assert task.base_ref is None
```

`tests/unit/test_verification_schema.py`

```python
def test_verification_command_result_supports_timeout_and_rejection_statuses():
    timed_out = VerificationCommandResult(
        command="pytest -q",
        exit_code=-1,
        status="timed_out",
        duration_ms=1000,
        stdout_excerpt="",
        stderr_excerpt="command timed out after 1 seconds",
        timed_out=True,
        rejected=False,
        cwd="/tmp/worktree",
    )
    rejected = VerificationCommandResult(
        command="pytest -q",
        exit_code=-1,
        status="rejected",
        duration_ms=0,
        stdout_excerpt="",
        stderr_excerpt="command rejected by policy",
        timed_out=False,
        rejected=True,
        cwd="/tmp/worktree",
    )

    assert timed_out.status == "timed_out"
    assert timed_out.timed_out is True
    assert rejected.status == "rejected"
    assert rejected.rejected is True
```

`tests/unit/test_run_state.py`

```python
def test_run_state_accepts_workspace_path():
    state = RunState(
        run_id="preview-123456789abc",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="completed",
        current_step="summarize",
        summary="Verification passed",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/worktree",
        verification=None,
    )

    assert state.workspace_path == "/tmp/worktree"
```

`tests/unit/test_settings.py`

```python
def test_settings_exposes_workspace_configuration(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    settings = get_settings()

    assert settings.workspace_root == tmp_path / ".worktrees"
    assert settings.verification_timeout_seconds == 60
    assert settings.cleanup_success_workspace is False


def test_ensure_data_directories_creates_workspace_root(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    settings = get_settings()

    created = ensure_data_directories(settings)

    assert created["workspace_root"] == tmp_path / ".worktrees"
    assert created["workspace_root"].exists()
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/unit/test_task_schema.py tests/unit/test_verification_schema.py tests/unit/test_run_state.py tests/unit/test_settings.py -v`
Expected: FAIL because `base_ref`, `workspace_path`, extended verification fields, and workspace settings do not exist yet.

- [ ] **Step 3: Implement the schema and settings changes**

Update `app/schemas/task.py` to add `base_ref`:

```python
class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: TaskType
    title: str
    repo_path: str
    base_ref: str | None = None
    entry_artifacts: dict[str, Any]
    verification_commands: list[str]
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
```

Update `app/schemas/verification.py` to support richer statuses:

```python
VerificationCommandStatus = Literal["passed", "failed", "timed_out", "rejected"]
VerificationSummaryStatus = Literal["passed", "failed"]


class VerificationCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    exit_code: int
    status: VerificationCommandStatus
    duration_ms: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    timed_out: bool = False
    rejected: bool = False
    cwd: str

    @model_validator(mode="after")
    def validate_status_flags(self) -> "VerificationCommandResult":
        if self.status == "passed" and self.exit_code != 0:
            raise ValueError("passed status requires exit_code 0")
        if self.status == "failed" and self.exit_code == 0:
            raise ValueError("failed status requires non-zero exit_code")
        if self.status == "timed_out" and not self.timed_out:
            raise ValueError("timed_out status requires timed_out=True")
        if self.status == "rejected" and not self.rejected:
            raise ValueError("rejected status requires rejected=True")
        if self.status in {"timed_out", "rejected"} and self.exit_code != -1:
            raise ValueError("timed_out and rejected statuses require exit_code -1")
        return self


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: VerificationSummaryStatus
    command_results: list[VerificationCommandResult] = Field(default_factory=list)
    passed_count: int
    failed_count: int

    @model_validator(mode="after")
    def validate_aggregate_consistency(self) -> "VerificationResult":
        passed_results = sum(1 for result in self.command_results if result.status == "passed")
        failed_results = len(self.command_results) - passed_results

        if self.passed_count != passed_results:
            raise ValueError("passed_count must match command_results")
        if self.failed_count != failed_results:
            raise ValueError("failed_count must match command_results")

        expected_status: VerificationSummaryStatus = "passed" if failed_results == 0 else "failed"
        if self.status != expected_status:
            raise ValueError("status must match command_results")

        return self
```

Update `app/schemas/run_state.py`:

```python
class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    task_type: TaskType
    status: Literal["running", "completed", "failed"]
    current_step: Literal["bootstrap", "verify", "summarize"]
    summary: str
    trace_path: str
    workspace_path: str | None = None
    verification: VerificationResult | None = None
```

Update `app/config/settings.py`:

```python
class Settings(BaseModel):
    app_name: str
    app_version: str
    project_root: Path
    data_dir: Path
    tasks_dir: Path
    traces_dir: Path
    workspace_root: Path
    verification_timeout_seconds: int
    cleanup_success_workspace: bool


def get_settings() -> Settings:
    root = Path(getenv("MENDCODE_PROJECT_ROOT", Path.cwd())).resolve()
    data_dir = root / "data"
    return Settings(
        app_name=APP_NAME,
        app_version=__version__,
        project_root=root,
        data_dir=data_dir,
        tasks_dir=data_dir / "tasks",
        traces_dir=data_dir / "traces",
        workspace_root=root / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )
```

Update `app/core/paths.py`:

```python
def ensure_data_directories(settings: Settings) -> dict[str, Path]:
    paths = {
        "data_dir": settings.data_dir,
        "tasks_dir": settings.tasks_dir,
        "traces_dir": settings.traces_dir,
        "workspace_root": settings.workspace_root,
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/unit/test_task_schema.py tests/unit/test_verification_schema.py tests/unit/test_run_state.py tests/unit/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/task.py app/schemas/verification.py app/schemas/run_state.py app/config/settings.py app/core/paths.py tests/unit/test_task_schema.py tests/unit/test_verification_schema.py tests/unit/test_run_state.py tests/unit/test_settings.py
git commit -m "feat: add workspace-aware run configuration"
```

### Task 2: Add Command Policy And Single-Command Executor

**Files:**
- Create: `app/workspace/__init__.py`
- Create: `app/workspace/command_policy.py`
- Create: `app/workspace/executor.py`
- Create: `tests/unit/test_command_policy.py`
- Create: `tests/unit/test_executor.py`
- Test: `tests/unit/test_command_policy.py`
- Test: `tests/unit/test_executor.py`

- [ ] **Step 1: Write the failing policy and executor tests**

Create `tests/unit/test_command_policy.py`:

```python
from pathlib import Path

from app.workspace.command_policy import CommandPolicy


def test_command_policy_allows_declared_command_in_allowed_root(tmp_path):
    policy = CommandPolicy(
        allowed_commands=["pytest -q"],
        allowed_root=tmp_path,
        timeout_seconds=60,
    )

    decision = policy.evaluate("pytest -q", tmp_path / "nested")

    assert decision.allowed is True
    assert decision.reason is None


def test_command_policy_rejects_unknown_command(tmp_path):
    policy = CommandPolicy(
        allowed_commands=["pytest -q"],
        allowed_root=tmp_path,
        timeout_seconds=60,
    )

    decision = policy.evaluate("make test", tmp_path)

    assert decision.allowed is False
    assert decision.reason == "command is not declared in verification_commands"
```

Create `tests/unit/test_executor.py`:

```python
import shlex
import sys

from app.workspace.command_policy import CommandPolicy
from app.workspace.executor import execute_verification_command

PYTHON = shlex.quote(sys.executable)


def test_execute_verification_command_returns_passed_result(tmp_path):
    policy = CommandPolicy(
        allowed_commands=[f"{PYTHON} -c \"print('ok')\""],
        allowed_root=tmp_path,
        timeout_seconds=60,
    )

    result = execute_verification_command(
        command=f"{PYTHON} -c \"print('ok')\"",
        cwd=tmp_path,
        policy=policy,
    )

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.stdout_excerpt == "ok\n"
    assert result.cwd == str(tmp_path)


def test_execute_verification_command_returns_timed_out_result(tmp_path):
    policy = CommandPolicy(
        allowed_commands=[f"{PYTHON} -c \"import time; time.sleep(2)\""],
        allowed_root=tmp_path,
        timeout_seconds=1,
    )

    result = execute_verification_command(
        command=f"{PYTHON} -c \"import time; time.sleep(2)\"",
        cwd=tmp_path,
        policy=policy,
    )

    assert result.status == "timed_out"
    assert result.timed_out is True
    assert result.exit_code == -1
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/unit/test_command_policy.py tests/unit/test_executor.py -v`
Expected: FAIL with `ModuleNotFoundError` for `app.workspace.command_policy` and `app.workspace.executor`.

- [ ] **Step 3: Implement the policy and executor**

Create `app/workspace/__init__.py`:

```python
"""Workspace execution helpers."""
```

Create `app/workspace/command_policy.py`:

```python
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class CommandPolicyDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed: bool
    reason: str | None = None


class CommandPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_commands: list[str]
    allowed_root: Path
    timeout_seconds: int

    def evaluate(self, command: str, cwd: Path) -> CommandPolicyDecision:
        if command not in self.allowed_commands:
            return CommandPolicyDecision(
                allowed=False,
                reason="command is not declared in verification_commands",
            )

        resolved_root = self.allowed_root.resolve()
        resolved_cwd = cwd.resolve()
        try:
            resolved_cwd.relative_to(resolved_root)
        except ValueError:
            return CommandPolicyDecision(
                allowed=False,
                reason="cwd escapes allowed workspace root",
            )

        return CommandPolicyDecision(allowed=True)
```

Create `app/workspace/executor.py`:

```python
import subprocess
import time
from pathlib import Path

from app.schemas.verification import VerificationCommandResult
from app.workspace.command_policy import CommandPolicy

_OUTPUT_EXCERPT_LIMIT = 2000


def _trim_output(value: str) -> str:
    if len(value) <= _OUTPUT_EXCERPT_LIMIT:
        return value
    return value[:_OUTPUT_EXCERPT_LIMIT]


def execute_verification_command(
    command: str,
    cwd: Path,
    policy: CommandPolicy,
) -> VerificationCommandResult:
    decision = policy.evaluate(command, cwd)
    if not decision.allowed:
        return VerificationCommandResult(
            command=command,
            exit_code=-1,
            status="rejected",
            duration_ms=0,
            stdout_excerpt="",
            stderr_excerpt=decision.reason or "command rejected by policy",
            timed_out=False,
            rejected=True,
            cwd=str(cwd),
        )

    started_at = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=policy.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return VerificationCommandResult(
            command=command,
            exit_code=-1,
            status="timed_out",
            duration_ms=duration_ms,
            stdout_excerpt="",
            stderr_excerpt=f"command timed out after {policy.timeout_seconds} seconds",
            timed_out=True,
            rejected=False,
            cwd=str(cwd),
        )
    except OSError as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        return VerificationCommandResult(
            command=command,
            exit_code=-1,
            status="failed",
            duration_ms=duration_ms,
            stdout_excerpt="",
            stderr_excerpt=str(exc),
            timed_out=False,
            rejected=False,
            cwd=str(cwd),
        )

    duration_ms = int((time.perf_counter() - started_at) * 1000)
    status = "passed" if completed.returncode == 0 else "failed"
    return VerificationCommandResult(
        command=command,
        exit_code=completed.returncode,
        status=status,
        duration_ms=duration_ms,
        stdout_excerpt=_trim_output(completed.stdout),
        stderr_excerpt=_trim_output(completed.stderr),
        timed_out=False,
        rejected=False,
        cwd=str(cwd),
    )
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/unit/test_command_policy.py tests/unit/test_executor.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workspace/__init__.py app/workspace/command_policy.py app/workspace/executor.py tests/unit/test_command_policy.py tests/unit/test_executor.py
git commit -m "feat: add command policy and executor"
```

### Task 3: Add Git Worktree Management

**Files:**
- Create: `app/workspace/worktree.py`
- Create: `tests/unit/test_worktree.py`
- Test: `tests/unit/test_worktree.py`

- [ ] **Step 1: Write the failing worktree tests**

Create `tests/unit/test_worktree.py`:

```python
import subprocess
from pathlib import Path

from app.workspace.worktree import cleanup_worktree, prepare_worktree


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
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


def test_prepare_worktree_creates_run_scoped_workspace(tmp_path):
    repo_path = init_git_repo(tmp_path)
    workspace_root = tmp_path / ".worktrees"

    workspace_path = prepare_worktree(
        repo_path=repo_path,
        workspace_root=workspace_root,
        run_id="preview-123456789abc",
        base_ref=None,
    )

    assert workspace_path == workspace_root / "preview-123456789abc"
    assert workspace_path.exists()
    assert (workspace_path / "README.md").exists()


def test_cleanup_worktree_removes_workspace_and_reports_success(tmp_path):
    repo_path = init_git_repo(tmp_path)
    workspace_root = tmp_path / ".worktrees"
    workspace_path = prepare_worktree(
        repo_path=repo_path,
        workspace_root=workspace_root,
        run_id="preview-123456789abc",
        base_ref=None,
    )

    cleanup = cleanup_worktree(repo_path=repo_path, workspace_path=workspace_path)

    assert cleanup.cleanup_attempted is True
    assert cleanup.cleanup_succeeded is True
    assert cleanup.workspace_path == str(workspace_path)
    assert not workspace_path.exists()
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/unit/test_worktree.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.workspace.worktree'`

- [ ] **Step 3: Implement the worktree manager**

Create `app/workspace/worktree.py`:

```python
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class WorkspaceCleanupResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_path: str
    cleanup_attempted: bool
    cleanup_succeeded: bool
    cleanup_reason: str


def prepare_worktree(
    repo_path: Path,
    workspace_root: Path,
    run_id: str,
    base_ref: str | None,
) -> Path:
    workspace_root.mkdir(parents=True, exist_ok=True)
    workspace_path = workspace_root / run_id
    ref = base_ref or "HEAD"

    subprocess.run(
        ["git", "-C", str(repo_path), "worktree", "add", "--detach", str(workspace_path), ref],
        check=True,
        capture_output=True,
        text=True,
    )

    return workspace_path


def cleanup_worktree(repo_path: Path, workspace_path: Path) -> WorkspaceCleanupResult:
    try:
        subprocess.run(
            ["git", "-C", str(repo_path), "worktree", "remove", "--force", str(workspace_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        return WorkspaceCleanupResult(
            workspace_path=str(workspace_path),
            cleanup_attempted=True,
            cleanup_succeeded=False,
            cleanup_reason=exc.stderr.strip() or exc.stdout.strip() or str(exc),
        )

    return WorkspaceCleanupResult(
        workspace_path=str(workspace_path),
        cleanup_attempted=True,
        cleanup_succeeded=True,
        cleanup_reason="workspace removed",
    )
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/unit/test_worktree.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/workspace/worktree.py tests/unit/test_worktree.py
git commit -m "feat: add git worktree manager"
```

### Task 4: Wire Runner And CLI To The Workspace Boundary

**Files:**
- Modify: `app/orchestrator/runner.py`
- Modify: `app/cli/main.py`
- Modify: `tests/unit/test_runner.py`
- Modify: `tests/integration/test_cli.py`
- Test: `tests/unit/test_runner.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing runner and CLI tests**

Add these tests and adjustments.

`tests/unit/test_runner.py`

```python
import subprocess

from app.config.settings import Settings


def init_git_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True, text=True)
    (repo_path / "repo_only.txt").write_text("repo-relative", encoding="utf-8")
    subprocess.run(["git", "add", "repo_only.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
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
        title="Worktree verification",
        repo_path=str(repo_path),
        base_ref=None,
        entry_artifacts={},
        verification_commands=[command],
    )

    result = run_task_preview(task, settings)
    trace_lines = Path(result.trace_path).read_text(encoding='utf-8').strip().splitlines()
    events = [json.loads(line) for line in trace_lines]

    assert result.status == "completed"
    assert result.workspace_path is not None
    assert Path(result.workspace_path) != repo_path
    assert events[-2]["event_type"] == "run.workspace.cleanup"
    assert events[-2]["payload"]["cleanup_attempted"] is False
    assert result.verification is not None
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
```

Update `tests/integration/test_cli.py`:

```python
import subprocess


def init_git_repo(path: Path) -> Path:
    repo_path = path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True, text=True)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    return repo_path
```

Change `write_task_file()` and `write_failing_task_file()` so they call `init_git_repo(path)` and store that repo path in `repo_path`.

Add this assertion block to `test_task_run_writes_trace_and_prints_summary`:

```python
    assert "workspace_path" in result.stdout
    assert "run.workspace.cleanup" in [event["event_type"] for event in trace_events]
    assert trace_events[0]["payload"]["workspace_path"].startswith(str(tmp_path / ".worktrees" / "preview-"))
```

- [ ] **Step 2: Run the focused tests to verify they fail**

Run: `pytest tests/unit/test_runner.py tests/integration/test_cli.py -v`
Expected: FAIL because `run_task_preview()` still accepts `traces_dir`, does not create worktrees, does not emit cleanup events, and the CLI does not print `workspace_path`.

- [ ] **Step 3: Implement the runner and CLI integration**

Update `app/orchestrator/runner.py` so `run_task_preview()` accepts `Settings`, prepares a worktree, builds a policy, executes commands through the executor, and records cleanup:

```python
from pathlib import Path
from uuid import uuid4

from app.config.settings import Settings
from app.schemas.run_state import RunState
from app.schemas.task import TaskSpec
from app.schemas.trace import TraceEvent
from app.schemas.verification import VerificationCommandResult, VerificationResult
from app.tracing.recorder import TraceRecorder
from app.workspace.command_policy import CommandPolicy
from app.workspace.executor import execute_verification_command
from app.workspace.worktree import WorkspaceCleanupResult, cleanup_worktree, prepare_worktree


def run_task_preview(task: TaskSpec, settings: Settings) -> RunState:
    recorder = TraceRecorder(settings.traces_dir)
    run_id = f"preview-{uuid4().hex[:12]}"

    try:
        workspace_path = prepare_worktree(
            repo_path=Path(task.repo_path),
            workspace_root=settings.workspace_root,
            run_id=run_id,
            base_ref=task.base_ref,
        )
    except Exception as exc:
        trace_path = recorder.record(
            TraceEvent(
                run_id=run_id,
                event_type="run.completed",
                message="Task run failed before verification",
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "status": "failed",
                    "summary": f"Workspace setup failed: {exc}",
                },
            )
        )
        return RunState(
            run_id=run_id,
            task_id=task.task_id,
            task_type=task.task_type,
            status="failed",
            current_step="summarize",
            summary=f"Workspace setup failed: {exc}",
            trace_path=str(trace_path),
            workspace_path=None,
            verification=None,
        )

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.started",
            message="Started task preview run",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": "running",
                "summary": "Task preview started",
                "workspace_path": str(workspace_path),
            },
        )
    )

    policy = CommandPolicy(
        allowed_commands=task.verification_commands,
        allowed_root=workspace_path,
        timeout_seconds=settings.verification_timeout_seconds,
    )

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.verification.started",
            message="Started verification commands",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "command_count": len(task.verification_commands),
                "status": "running",
                "workspace_path": str(workspace_path),
            },
        )
    )

    command_results: list[VerificationCommandResult] = []
    for command in task.verification_commands:
        result = execute_verification_command(command=command, cwd=workspace_path, policy=policy)
        command_results.append(result)
        trace_path = recorder.record(
            TraceEvent(
                run_id=run_id,
                event_type="run.verification.command.completed",
                message="Completed verification command",
                payload={
                    "task_id": task.task_id,
                    "task_type": task.task_type,
                    "command": result.command,
                    "exit_code": result.exit_code,
                    "status": result.status,
                    "duration_ms": result.duration_ms,
                    "stdout_excerpt": result.stdout_excerpt,
                    "stderr_excerpt": result.stderr_excerpt,
                    "timed_out": result.timed_out,
                    "rejected": result.rejected,
                    "cwd": result.cwd,
                },
            )
        )

    if not command_results:
        command_results.append(
            VerificationCommandResult(
                command="<none>",
                exit_code=-1,
                status="failed",
                duration_ms=0,
                stdout_excerpt="",
                stderr_excerpt="no verification commands provided",
                timed_out=False,
                rejected=False,
                cwd=str(workspace_path),
            )
        )

    failed_count = len(command_results) - sum(
        1 for result in command_results if result.status == "passed"
    )
    passed_count = len(command_results) - failed_count
    verification = VerificationResult(
        status="passed" if failed_count == 0 else "failed",
        command_results=command_results,
        passed_count=passed_count,
        failed_count=failed_count,
    )
    run_status = "completed" if verification.status == "passed" else "failed"
    summary = (
        f"Verification passed: {passed_count}/{len(command_results)} commands succeeded"
        if verification.status == "passed"
        else f"Verification failed: {failed_count} of {len(command_results)} commands failed"
    )

    cleanup = WorkspaceCleanupResult(
        workspace_path=str(workspace_path),
        cleanup_attempted=False,
        cleanup_succeeded=False,
        cleanup_reason="workspace preserved",
    )
    if run_status == "completed" and settings.cleanup_success_workspace:
        cleanup = cleanup_worktree(repo_path=Path(task.repo_path), workspace_path=workspace_path)

    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.workspace.cleanup",
            message="Workspace cleanup evaluated",
            payload=cleanup.model_dump(mode="json"),
        )
    )
    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.completed",
            message="Completed task preview run",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "status": run_status,
                "summary": summary,
                "workspace_path": str(workspace_path),
            },
        )
    )

    return RunState(
        run_id=run_id,
        task_id=task.task_id,
        task_type=task.task_type,
        status=run_status,
        current_step="summarize",
        summary=summary,
        trace_path=str(trace_path),
        workspace_path=str(workspace_path),
        verification=verification,
    )
```

Update `app/cli/main.py` so `task run` passes `settings` instead of `settings.traces_dir` and prints `workspace_path`:

```python
    state = run_task_preview(task, settings)
```

```python
    table.add_row("workspace_path", state.workspace_path or "")
```

Update the first-failure selection so non-passing statuses are included:

```python
    if state.verification and state.verification.failed_count > 0:
        first_failed = next(
            (item for item in state.verification.command_results if item.status != "passed"),
            None,
        )
```

- [ ] **Step 4: Run the focused tests to verify they pass**

Run: `pytest tests/unit/test_runner.py tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator/runner.py app/cli/main.py tests/unit/test_runner.py tests/integration/test_cli.py
git commit -m "feat: run verification inside controlled worktrees"
```

### Task 5: Sync Docs And Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_问题记录.md`
- Test: `tests/unit/test_task_schema.py`
- Test: `tests/unit/test_verification_schema.py`
- Test: `tests/unit/test_run_state.py`
- Test: `tests/unit/test_settings.py`
- Test: `tests/unit/test_command_policy.py`
- Test: `tests/unit/test_executor.py`
- Test: `tests/unit/test_worktree.py`
- Test: `tests/unit/test_runner.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Update README for command policy and worktree execution**

Make these exact README changes:

```markdown
## Current Capabilities

- Python project skeleton with `pyproject.toml`
- CLI health check, task file inspection, and `task run` verification execution inside a per-run git worktree
- Command-policy guarded verification execution with timeout and trace output
- FastAPI health endpoint
- JSONL trace output for task runs
```

Add a short note under `CLI`:

```markdown
`task run` now creates a temporary workspace under `.worktrees/preview-<id>/`, executes verification commands there, and records `workspace_path` plus cleanup results in trace output.
```

- [ ] **Step 2: Update the root plan and issue log**

Append the following status notes.

`MendCode_开发方案.md`

```markdown
- command policy 已落地：验证命令必须经过受控 executor，具备 timeout、rejected、timed_out 语义
- worktree manager 已落地：`task run` 默认在 `.worktrees/preview-<id>/` 中执行 verification
- runner 已从“直接执行命令”收敛为“编排 workspace、executor、trace 和 cleanup”
```

`MendCode_问题记录.md`

```markdown
## 问题 9：没有 workspace 隔离时，verification 命令会直接对仓库工作目录产生副作用

- 时间：Phase 1B command policy / worktree 落地
- 阶段：runner 执行边界治理
- 状态：已解决

### 现象

verification 命令原先直接在 `task.repo_path` 下执行，后续一旦引入补丁修改能力，真实仓库会直接暴露给任务运行副作用。

### 根因

- 初版 runner 只追求跑通验证链路，没有 workspace 抽象
- 命令执行边界和 repo 工作目录耦合在一起

### 解决方案

- 为每次 run 创建独立 `.worktrees/preview-<id>/`
- verification 默认在 worktree 中执行
- trace 记录 `workspace_path` 与 cleanup 结果

### 后续约束

- 后续 `read_file` / `search_code` / `apply_patch` 都应优先围绕 `workspace_path`，而不是直接操作 `task.repo_path`
```

- [ ] **Step 3: Run the targeted suite for this feature**

Run: `pytest tests/unit/test_task_schema.py tests/unit/test_verification_schema.py tests/unit/test_run_state.py tests/unit/test_settings.py tests/unit/test_command_policy.py tests/unit/test_executor.py tests/unit/test_worktree.py tests/unit/test_runner.py tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 4: Run the full project verification**

Run: `pytest -q`
Expected: all tests pass

Run: `ruff check .`
Expected: `All checks passed!`

Run: `python -m app.cli.main task run data/tasks/demo.json`
Expected: output includes `Task Run`, `workspace_path`, `passed_count`, `failed_count`, and `trace_path`

- [ ] **Step 5: Commit**

```bash
git add README.md MendCode_开发方案.md MendCode_问题记录.md
git commit -m "docs: sync command policy and worktree execution"
```
