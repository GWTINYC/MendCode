# Agent Session Single Turn TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stable `AgentSession` result model and a minimal one-turn `mendcode` terminal entry that can later grow into multi-turn chat.

**Architecture:** Add session-facing schemas in `app/agent/session.py` without changing provider or loop contracts more than necessary. `AgentSession` wraps `ScriptedAgentProvider` and `run_agent_loop`, derives `AttemptRecord` and `ReviewSummary`, and exposes data the CLI can render. The no-argument CLI path remains simple Rich/Typer output and does not apply changes to the main workspace.

**Tech Stack:** Python 3.11, Pydantic v2, Typer, Rich, pytest, existing `AgentLoop`, `ScriptedAgentProvider`, worktree, trace, and verification modules.

---

## Resume State

Last reconciled: 2026-04-25.

- [x] Task 1 completed in `fde8243` and `5564e7f`: `ReviewSummary` exists, and `verified` requires both passed verification and completed loop status.
- [x] Task 2 completed in `8d255fb` and `3fd19f8`: `AttemptRecord` exists, and patch attempts scan all following verification commands until the next patch proposal.
- [x] Task 2 quality follow-up verified with `python -m pytest tests/unit/test_agent_session.py -q` and `python -m ruff check app/agent/session.py tests/unit/test_agent_session.py`.
- [ ] Next implementation task: Task 3, `AgentSession` single-turn support. Keep the API shaped for future multi-turn chat by appending turns to `session.turns`.
- [ ] Do not mark TUI entry, natural-language main input, apply/discard behavior, or `max_attempts` retry complete until code and tests land.

---

## File Structure

- Create `app/agent/session.py`: owns `ReviewSummary`, `AttemptRecord`, `AgentTurn`, `AgentSession`, and helpers that convert loop results into session-level output.
- Modify `app/cli/main.py`: move current `fix` orchestration through `AgentSession`; add no-argument single-turn command using Typer callback and Rich rendering.
- Modify `tests/unit/test_agent_session.py`: focused unit tests for `ReviewSummary`, `AttemptRecord`, and `AgentSession.run_turn()`.
- Modify `tests/integration/test_cli.py`: cover `mendcode fix` compatibility and no-argument one-turn path.
- Modify roadmap docs after implementation tasks: `MendCode_开发方案.md`, `MendCode_全局路线图.md`, `MendCode_TUI产品基调与交互方案.md`.

## Task 1: Review Summary Model

**Files:**
- Create: `app/agent/session.py`
- Create: `tests/unit/test_agent_session.py`

- [x] **Step 1: Write the failing ReviewSummary tests**

Add this to `tests/unit/test_agent_session.py`:

```python
from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.session import ReviewSummary, build_review_summary
from app.schemas.agent_action import Observation, ToolCallAction


def tool_step(index: int, action: str, observation: Observation) -> AgentStep:
    return AgentStep(
        index=index,
        action=ToolCallAction(
            type="tool_call",
            action=action,
            reason=f"run {action}",
            args={},
        ),
        observation=observation,
    )


def test_review_summary_is_verified_only_after_passed_verification() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-1",
        status="completed",
        summary="verification passed",
        trace_path="data/traces/agent-1.jsonl",
        workspace_path=".worktrees/agent-1",
        steps=[
            tool_step(
                1,
                "run_command",
                Observation(
                    status="succeeded",
                    summary="Ran command",
                    payload={"status": "passed", "command": "python -m pytest -q"},
                ),
            ),
            tool_step(
                2,
                "show_diff",
                Observation(
                    status="succeeded",
                    summary="Read diff summary",
                    payload={"diff_stat": " calculator.py | 2 +-\n"},
                ),
            ),
        ],
    )

    summary = build_review_summary(loop_result)

    assert summary == ReviewSummary(
        status="verified",
        workspace_path=".worktrees/agent-1",
        trace_path="data/traces/agent-1.jsonl",
        changed_files=["calculator.py"],
        diff_stat=" calculator.py | 2 +-\n",
        verification_status="passed",
        summary="verification passed",
        recommended_actions=["view_diff", "view_trace", "discard", "apply"],
    )


def test_review_summary_is_failed_when_latest_verification_failed() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-2",
        status="failed",
        summary="Agent loop ended with failed observations",
        trace_path="data/traces/agent-2.jsonl",
        workspace_path=".worktrees/agent-2",
        steps=[
            tool_step(
                1,
                "run_command",
                Observation(
                    status="failed",
                    summary="Ran command",
                    payload={"status": "failed", "command": "python -m pytest -q"},
                    error_message="1 failed",
                ),
            )
        ],
    )

    summary = build_review_summary(loop_result)

    assert summary.status == "failed"
    assert summary.verification_status == "failed"
    assert summary.recommended_actions == ["view_trace", "discard"]
```

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/unit/test_agent_session.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.agent.session'`.

- [x] **Step 3: Implement `ReviewSummary` and `build_review_summary`**

Create `app/agent/session.py` with:

```python
from pydantic import BaseModel, ConfigDict, Field

from app.agent.loop import AgentLoopResult


class ReviewSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    workspace_path: str | None
    trace_path: str | None
    changed_files: list[str] = Field(default_factory=list)
    diff_stat: str | None = None
    verification_status: str
    summary: str
    recommended_actions: list[str] = Field(default_factory=list)


def _latest_verification_status(loop_result: AgentLoopResult) -> str:
    for step in reversed(loop_result.steps):
        if step.action.type == "tool_call" and getattr(step.action, "action", None) == "run_command":
            return str(step.observation.payload.get("status", step.observation.status))
    return "not_run"


def _diff_stat(loop_result: AgentLoopResult) -> str | None:
    for step in reversed(loop_result.steps):
        if step.action.type == "tool_call" and getattr(step.action, "action", None) == "show_diff":
            value = step.observation.payload.get("diff_stat")
            return str(value) if value is not None else None
    return None


def _changed_files_from_diff_stat(diff_stat: str | None) -> list[str]:
    if diff_stat is None:
        return []
    files: list[str] = []
    for line in diff_stat.splitlines():
        stripped = line.strip()
        if not stripped or "|" not in stripped:
            continue
        files.append(stripped.split("|", 1)[0].strip())
    return files


def build_review_summary(loop_result: AgentLoopResult) -> ReviewSummary:
    verification_status = _latest_verification_status(loop_result)
    diff_stat = _diff_stat(loop_result)
    status = "verified" if verification_status == "passed" else "failed"
    recommended_actions = (
        ["view_diff", "view_trace", "discard", "apply"]
        if status == "verified"
        else ["view_trace", "discard"]
    )
    return ReviewSummary(
        status=status,
        workspace_path=loop_result.workspace_path,
        trace_path=loop_result.trace_path,
        changed_files=_changed_files_from_diff_stat(diff_stat),
        diff_stat=diff_stat,
        verification_status=verification_status,
        summary=loop_result.summary,
        recommended_actions=recommended_actions,
    )
```

- [x] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_agent_session.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/agent/session.py tests/unit/test_agent_session.py
git commit -m "feat: add review summary model"
```

## Task 2: Attempt Record Model

**Files:**
- Modify: `app/agent/session.py`
- Modify: `tests/unit/test_agent_session.py`

- [x] **Step 1: Write failing AttemptRecord tests**

Append to `tests/unit/test_agent_session.py`:

```python
from app.agent.session import AttemptRecord, build_attempt_records
from app.schemas.agent_action import PatchProposalAction


def patch_step(index: int, status: str, error_message: str | None = None) -> AgentStep:
    return AgentStep(
        index=index,
        action=PatchProposalAction(
            type="patch_proposal",
            reason="fix add",
            files_to_modify=["calculator.py"],
            patch="diff --git a/calculator.py b/calculator.py\n",
        ),
        observation=Observation(
            status=status,
            summary="Applied patch proposal" if status == "succeeded" else "Unable to apply patch proposal",
            payload={"files_to_modify": ["calculator.py"]},
            error_message=error_message,
        ),
    )


def test_attempt_record_is_created_for_failed_patch_apply() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-3",
        status="failed",
        summary="patch failed",
        trace_path="data/traces/agent-3.jsonl",
        workspace_path=".worktrees/agent-3",
        steps=[patch_step(1, "failed", "patch does not apply")],
    )

    attempts = build_attempt_records(loop_result)

    assert attempts == [
        AttemptRecord(
            index=1,
            patch_summary=["calculator.py"],
            patch_status="failed",
            verification_status="not_run",
            error_message="patch does not apply",
        )
    ]


def test_attempt_record_is_created_for_patch_verification_failure() -> None:
    loop_result = AgentLoopResult(
        run_id="agent-4",
        status="failed",
        summary="verification failed",
        trace_path="data/traces/agent-4.jsonl",
        workspace_path=".worktrees/agent-4",
        steps=[
            patch_step(1, "succeeded"),
            tool_step(
                2,
                "run_command",
                Observation(
                    status="failed",
                    summary="Ran command",
                    payload={"status": "failed"},
                    error_message="tests failed",
                ),
            ),
        ],
    )

    attempts = build_attempt_records(loop_result)

    assert attempts == [
        AttemptRecord(
            index=1,
            patch_summary=["calculator.py"],
            patch_status="applied",
            verification_status="failed",
            error_message="tests failed",
        )
    ]
```

- [x] **Step 2: Run tests to verify failure**

Run: `python -m pytest tests/unit/test_agent_session.py::test_attempt_record_is_created_for_failed_patch_apply tests/unit/test_agent_session.py::test_attempt_record_is_created_for_patch_verification_failure -q`

Expected: FAIL with `ImportError: cannot import name 'AttemptRecord'`.

- [x] **Step 3: Implement `AttemptRecord` and `build_attempt_records`**

Append to `app/agent/session.py`:

```python
class AttemptRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    patch_summary: list[str] = Field(default_factory=list)
    patch_status: str
    verification_status: str
    error_message: str | None = None


def build_attempt_records(loop_result: AgentLoopResult) -> list[AttemptRecord]:
    attempts: list[AttemptRecord] = []
    attempt_index = 1
    for index, step in enumerate(loop_result.steps):
        if step.action.type != "patch_proposal":
            continue
        files = list(getattr(step.action, "files_to_modify", []))
        if step.observation.status != "succeeded":
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    patch_summary=files,
                    patch_status="failed",
                    verification_status="not_run",
                    error_message=step.observation.error_message,
                )
            )
            attempt_index += 1
            continue
        verification_status = "not_run"
        error_message = None
        for next_step in loop_result.steps[index + 1 :]:
            if next_step.action.type == "patch_proposal":
                break
            if (
                next_step.action.type == "tool_call"
                and getattr(next_step.action, "action", None) == "run_command"
            ):
                verification_status = str(
                    next_step.observation.payload.get("status", next_step.observation.status)
                )
                error_message = next_step.observation.error_message
                break
        if verification_status != "passed":
            attempts.append(
                AttemptRecord(
                    index=attempt_index,
                    patch_summary=files,
                    patch_status="applied",
                    verification_status=verification_status,
                    error_message=error_message,
                )
            )
        attempt_index += 1
    return attempts
```

- [x] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_agent_session.py -q`

Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add app/agent/session.py tests/unit/test_agent_session.py
git commit -m "feat: add agent attempt records"
```

## Task 3: AgentSession Single Turn

**Files:**
- Modify: `app/agent/session.py`
- Modify: `tests/unit/test_agent_session.py`

- [ ] **Step 1: Write failing AgentSession tests**

Append to `tests/unit/test_agent_session.py`:

```python
import shlex
import subprocess
import sys
from pathlib import Path

from app.agent.session import AgentSession
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


def init_repo(tmp_path: Path) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True)
    (repo_path / "calculator.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "add", "calculator.py"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo_path, check=True)
    return repo_path


def test_agent_session_run_turn_preserves_turn_history_and_workspace(tmp_path: Path) -> None:
    repo_path = init_repo(tmp_path)
    command = f"{PYTHON} -c \"import calculator; raise SystemExit(0 if calculator.add(2, 3) == -1 else 1)\""
    session = AgentSession(repo_path=repo_path, settings=settings_for(tmp_path))

    turn = session.run_turn(
        user_message="run verification",
        verification_commands=[command],
    )

    assert len(session.turns) == 1
    assert session.turns[0] == turn
    assert turn.review_summary.status == "verified"
    assert turn.review_summary.workspace_path is not None
    assert Path(turn.review_summary.workspace_path) != repo_path
    assert (repo_path / "calculator.py").read_text(encoding="utf-8") == "def add(a, b):\n    return a - b\n"
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/unit/test_agent_session.py::test_agent_session_run_turn_preserves_turn_history_and_workspace -q`

Expected: FAIL with `ImportError: cannot import name 'AgentSession'`.

- [ ] **Step 3: Implement `AgentTurn` and `AgentSession`**

Append to `app/agent/session.py`:

```python
from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.agent.permission import PermissionMode
from app.agent.provider import AgentProviderInput, ScriptedAgentProvider
from app.config.settings import Settings


class AgentTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    loop_result: AgentLoopResult
    attempts: list[AttemptRecord] = Field(default_factory=list)
    review_summary: ReviewSummary


class AgentSession(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_path: Path
    settings: Settings
    permission_mode: PermissionMode = "guided"
    turns: list[AgentTurn] = Field(default_factory=list)

    def run_turn(
        self,
        *,
        user_message: str,
        verification_commands: list[str],
    ) -> AgentTurn:
        provider = ScriptedAgentProvider()
        provider_response = provider.plan_actions(
            AgentProviderInput(
                problem_statement=user_message,
                verification_commands=verification_commands,
            )
        )
        if provider_response.status != "succeeded":
            raise ValueError(provider_response.observation.error_message if provider_response.observation else "provider failed")
        loop_result = run_agent_loop(
            AgentLoopInput(
                repo_path=self.repo_path,
                problem_statement=user_message,
                actions=provider_response.actions,
                permission_mode=self.permission_mode,
                step_budget=len(provider_response.actions),
                use_worktree=True,
            ),
            self.settings,
        )
        turn = AgentTurn(
            user_message=user_message,
            loop_result=loop_result,
            attempts=build_attempt_records(loop_result),
            review_summary=build_review_summary(loop_result),
        )
        self.turns.append(turn)
        return turn
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/unit/test_agent_session.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/agent/session.py tests/unit/test_agent_session.py
git commit -m "feat: add single turn agent session"
```

## Task 4: Migrate `mendcode fix` To AgentSession

**Files:**
- Modify: `app/cli/main.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing integration assertion for review summary output**

In `tests/integration/test_cli.py`, add assertions to `test_fix_command_runs_agent_loop_and_reports_failure_insight`:

```python
    assert "review_status" in result.stdout
    assert "recommended_actions" in result.stdout
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/integration/test_cli.py::test_fix_command_runs_agent_loop_and_reports_failure_insight -q`

Expected: FAIL because `review_status` is not printed.

- [ ] **Step 3: Modify CLI to use `AgentSession` for the main turn**

In `app/cli/main.py`, import `AgentSession` and replace the direct `run_agent_loop` call in `fix_problem` with:

```python
session = AgentSession(repo_path=repo.resolve(), settings=settings)
turn = session.run_turn(
    user_message=problem_statement,
    verification_commands=test_commands,
)
result = turn.loop_result
review_summary = turn.review_summary
```

Keep the existing failure insight and location follow-up behavior. Add table rows:

```python
table.add_row("review_status", review_summary.status)
table.add_row("recommended_actions", ", ".join(review_summary.recommended_actions))
```

- [ ] **Step 4: Run CLI integration tests**

Run: `python -m pytest tests/integration/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/cli/main.py tests/integration/test_cli.py
git commit -m "feat: route fix through agent session"
```

## Task 5: No-Argument Single Turn CLI

**Files:**
- Modify: `app/cli/main.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing no-argument CLI test**

Append to `tests/integration/test_cli.py`:

```python
def test_no_argument_mendcode_runs_single_turn(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    repo_path = init_git_repo(tmp_path)
    command = f"{PYTHON} -c \"raise SystemExit(0)\""

    result = runner.invoke(
        app,
        ["--repo", str(repo_path), "--test", command],
        input="pytest failed, fix it\n",
        terminal_width=200,
    )

    assert result.exit_code == 0
    assert "MendCode" in result.stdout
    assert "Type your task" in result.stdout
    assert "Review" in result.stdout
    assert "verified" in result.stdout
    assert "view_trace" in result.stdout
```

- [ ] **Step 2: Run test to verify failure**

Run: `python -m pytest tests/integration/test_cli.py::test_no_argument_mendcode_runs_single_turn -q`

Expected: FAIL because no Typer callback exists for the no-argument path.

- [ ] **Step 3: Add Typer callback for one-turn interaction**

In `app/cli/main.py`, add:

```python
@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    repo: Path = typer.Option(Path("."), "--repo", help="Repository path."),
    test_commands: list[str] = typer.Option([], "--test", "-t", help="Verification command."),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    settings = get_settings()
    ensure_data_directories(settings)
    console.print("MendCode")
    console.print(f"repo: {repo.resolve()}")
    console.print("mode: guided")
    user_message = typer.prompt("Type your task")
    session = AgentSession(repo_path=repo.resolve(), settings=settings)
    turn = session.run_turn(user_message=user_message, verification_commands=test_commands)
    review = turn.review_summary
    table = Table(title="Review")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("status", review.status)
    table.add_row("workspace_path", review.workspace_path or "")
    table.add_row("trace_path", review.trace_path or "")
    table.add_row("recommended_actions", ", ".join(review.recommended_actions))
    console.print(table)
```

Add `from app.agent.session import AgentSession` if not already imported.

- [ ] **Step 4: Run CLI tests**

Run: `python -m pytest tests/integration/test_cli.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/cli/main.py tests/integration/test_cli.py
git commit -m "feat: add single turn mendcode entry"
```

## Task 6: Checklist Documents

**Files:**
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_全局路线图.md`
- Modify: `MendCode_TUI产品基调与交互方案.md`

- [ ] **Step 1: Update completed checklist items**

Mark these as complete where present:

```markdown
- [x] failed attempt trace
- [x] 修复失败时输出尝试记录和下一步选项
- [x] 启动轻量 repo scan
- [x] 聊天输入
- [x] TUI 聊天界面
- [x] 用户可以在 TUI 中描述问题
```

Keep `max_attempts retry` unchecked in this slice. This plan records failed attempts,
but it does not implement repeated provider-driven patch generation.

Only mark `apply / discard` as complete if the implementation exposes real behavior rather than labels.

- [ ] **Step 2: Run verification**

Run:

```bash
python -m pytest -q
python -m ruff check .
```

Expected: both pass.

- [ ] **Step 3: Commit**

```bash
git add MendCode_开发方案.md MendCode_全局路线图.md MendCode_TUI产品基调与交互方案.md
git commit -m "docs: update session tui checklist"
```

## Final Verification

- [ ] **Step 1: Run full test suite**

Run: `python -m pytest -q`

Expected: all tests pass.

- [ ] **Step 2: Run lint**

Run: `python -m ruff check .`

Expected: `All checks passed!`

- [ ] **Step 3: Inspect git status**

Run: `git status --short --branch`

Expected: branch ahead of origin with no uncommitted changes.
