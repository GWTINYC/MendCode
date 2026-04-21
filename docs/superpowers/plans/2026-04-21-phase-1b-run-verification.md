# Phase 1B Run Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve the Phase 1A run skeleton into a real verification execution path that sequentially runs `TaskSpec.verification_commands`, records verification results in trace events, and reports pass/fail summaries through the CLI.

**Architecture:** Keep the implementation narrow. Add a small verification schema, extend `RunState` to carry verification results, evolve the existing runner in `app/orchestrator/runner.py` to execute commands with `subprocess.run(...)`, and expand the current CLI summary and tests. Do not introduce tool-layer abstractions, worktree management, or command-policy systems yet.

**Tech Stack:** Python 3.11, subprocess, Typer, Pydantic v2, orjson, pytest, rich

---

### Task 1: Add Verification Result Schemas

**Files:**
- Create: `app/schemas/verification.py`
- Modify: `app/schemas/__init__.py`
- Create: `tests/unit/test_verification_schema.py`
- Test: `tests/unit/test_verification_schema.py`

- [ ] **Step 1: Write the failing verification schema tests**

`tests/unit/test_verification_schema.py`

```python
import pytest
from pydantic import ValidationError

from app.schemas.verification import VerificationCommandResult, VerificationResult


def test_verification_result_serializes_expected_fields():
    result = VerificationResult(
        status="failed",
        passed_count=1,
        failed_count=1,
        command_results=[
            VerificationCommandResult(
                command="pytest -q",
                exit_code=0,
                status="passed",
                duration_ms=120,
                stdout_excerpt="2 passed",
                stderr_excerpt="",
            ),
            VerificationCommandResult(
                command="python -m bad.module",
                exit_code=1,
                status="failed",
                duration_ms=80,
                stdout_excerpt="",
                stderr_excerpt="ModuleNotFoundError",
            ),
        ],
    )

    assert result.model_dump() == {
        "status": "failed",
        "command_results": [
            {
                "command": "pytest -q",
                "exit_code": 0,
                "status": "passed",
                "duration_ms": 120,
                "stdout_excerpt": "2 passed",
                "stderr_excerpt": "",
            },
            {
                "command": "python -m bad.module",
                "exit_code": 1,
                "status": "failed",
                "duration_ms": 80,
                "stdout_excerpt": "",
                "stderr_excerpt": "ModuleNotFoundError",
            },
        ],
        "passed_count": 1,
        "failed_count": 1,
    }


def test_verification_schema_rejects_invalid_status():
    with pytest.raises(ValidationError):
        VerificationCommandResult(
            command="pytest -q",
            exit_code=0,
            status="unknown",
            duration_ms=100,
            stdout_excerpt="ok",
            stderr_excerpt="",
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_verification_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.verification'`

- [ ] **Step 3: Write the minimal verification schemas**

`app/schemas/verification.py`

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class VerificationCommandResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str
    exit_code: int
    status: Literal["passed", "failed"]
    duration_ms: int
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""


class VerificationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["passed", "failed"]
    command_results: list[VerificationCommandResult] = Field(default_factory=list)
    passed_count: int
    failed_count: int
```

Update `app/schemas/__init__.py` to export:

```python
"""Schema package exports."""

from app.schemas.run_state import RunState
from app.schemas.task import TaskSpec
from app.schemas.trace import TraceEvent
from app.schemas.verification import VerificationCommandResult, VerificationResult

__all__ = [
    "RunState",
    "TaskSpec",
    "TraceEvent",
    "VerificationCommandResult",
    "VerificationResult",
]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_verification_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/__init__.py app/schemas/verification.py tests/unit/test_verification_schema.py
git commit -m "feat: add verification result schemas"
```

### Task 2: Extend RunState For Verification Summaries

**Files:**
- Modify: `app/schemas/run_state.py`
- Modify: `tests/unit/test_run_state.py`
- Test: `tests/unit/test_run_state.py`

- [ ] **Step 1: Write the failing RunState verification test**

Add this test to `tests/unit/test_run_state.py`:

```python
from app.schemas.verification import VerificationResult


def test_run_state_includes_verification_result():
    state = RunState(
        run_id="preview-123456789abc",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="failed",
        current_step="summarize",
        summary="Verification failed",
        trace_path="/tmp/demo.jsonl",
        verification=VerificationResult(
            status="failed",
            passed_count=0,
            failed_count=1,
            command_results=[],
        ),
    )

    assert state.verification is not None
    assert state.verification.status == "failed"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_run_state.py::test_run_state_includes_verification_result -v`
Expected: FAIL because `RunState` does not accept `verification`

- [ ] **Step 3: Extend `RunState` minimally**

Update `app/schemas/run_state.py` to:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.task import TaskType
from app.schemas.verification import VerificationResult


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    task_type: TaskType
    status: Literal["running", "completed", "failed"]
    current_step: Literal["bootstrap", "verify", "summarize"]
    summary: str
    trace_path: str
    verification: VerificationResult | None = None
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_run_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/run_state.py tests/unit/test_run_state.py
git commit -m "feat: extend run state with verification summary"
```

### Task 3: Execute Verification Commands In Runner

**Files:**
- Modify: `app/orchestrator/runner.py`
- Modify: `tests/unit/test_runner.py`
- Test: `tests/unit/test_runner.py`

- [ ] **Step 1: Write the failing runner tests for verification execution**

Add tests like these to `tests/unit/test_runner.py`:

```python
def test_run_task_preview_marks_run_passed_when_all_commands_succeed(tmp_path):
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Verify success path",
        repo_path="/repo/demo",
        entry_artifacts={},
        verification_commands=["python -c \"print('ok')\""],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.verification is not None
    assert result.verification.status == "passed"
    assert result.verification.passed_count == 1
    assert result.verification.failed_count == 0
    assert result.summary == "Verification passed: 1/1 commands succeeded"


def test_run_task_preview_marks_run_failed_when_a_command_fails(tmp_path):
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Verify fail path",
        repo_path="/repo/demo",
        entry_artifacts={},
        verification_commands=[
            "python -c \"print('ok')\"",
            "python -c \"import sys; sys.exit(2)\"",
        ],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.status == "failed"
    assert result.verification.passed_count == 1
    assert result.verification.failed_count == 1
    assert "Verification failed" in result.summary


def test_run_task_preview_fails_when_no_verification_commands_are_defined(tmp_path):
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="No verification commands",
        repo_path="/repo/demo",
        entry_artifacts={},
        verification_commands=[],
    )

    result = run_task_preview(task, tmp_path)

    assert result.status == "failed"
    assert result.verification is not None
    assert result.verification.failed_count == 1
    assert result.summary == "Verification failed: no verification commands provided"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_runner.py -v`
Expected: FAIL because the current preview runner never executes commands or populates verification results

- [ ] **Step 3: Evolve the runner into a verification executor**

Update `app/orchestrator/runner.py` to:

- import `subprocess` and `time`
- add a small helper to trim output strings to `2000` chars
- sequentially execute each command with `subprocess.run(..., shell=True, capture_output=True, text=True)`
- record:
  - `run.started`
  - `run.verification.started`
  - one `run.verification.command.completed` per command
  - `run.completed`
- convert command results into `VerificationCommandResult`
- build `VerificationResult`
- return a `RunState` carrying `verification`

Use this status behavior:

- all commands pass:
  - `RunState.status = "completed"`
  - `VerificationResult.status = "passed"`
  - summary: `Verification passed: <passed>/<total> commands succeeded`
- any command fails:
  - `RunState.status = "failed"`
  - `VerificationResult.status = "failed"`
  - summary: `Verification failed: <failed> of <total> commands failed`
- no commands:
  - synthesize one failed command result with:
    - `command = "<none>"`
    - `exit_code = -1`
    - `status = "failed"`
    - `duration_ms = 0`
    - `stderr_excerpt = "no verification commands provided"`
  - summary: `Verification failed: no verification commands provided`

If `subprocess.run(...)` raises `OSError`, convert it into a failed command result with:

- `exit_code = -1`
- `status = "failed"`
- `stderr_excerpt = str(exc)`

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_runner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator/runner.py tests/unit/test_runner.py
git commit -m "feat: execute verification commands in runner"
```

### Task 4: Expand CLI Summary And Integration Coverage

**Files:**
- Modify: `app/cli/main.py`
- Modify: `tests/integration/test_cli.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing CLI integration tests**

Add tests like these to `tests/integration/test_cli.py`:

```python
def test_task_run_reports_passed_verification(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    assert result.exit_code == 0
    assert "passed_count" in result.stdout
    assert "failed_count" in result.stdout
    assert "completed" in result.stdout


def test_task_run_reports_failed_verification(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    failing_task = tmp_path / "task-fail.json"
    failing_task.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-002",
                "task_type": "ci_fix",
                "title": "Fail verification",
                "repo_path": str(tmp_path),
                "entry_artifacts": {},
                "verification_commands": [
                    "python -c \"import sys; sys.exit(3)\""
                ],
            }
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["task", "run", str(failing_task)], terminal_width=200)

    assert result.exit_code == 0
    assert "failed" in result.stdout
    assert "failed_count" in result.stdout
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/integration/test_cli.py::test_task_run_reports_passed_verification tests/integration/test_cli.py::test_task_run_reports_failed_verification -v`
Expected: FAIL because the current CLI summary does not print verification counts or failed verification details

- [ ] **Step 3: Expand the CLI summary minimally**

Update `app/cli/main.py` so the `task run` command:

- keeps the existing `Table(title="Task Run")`
- continues to show:
  - `run_id`
  - `task_id`
  - `task_type`
  - `status`
  - `current_step`
  - `summary`
  - `trace_path`
- additionally shows:
  - `passed_count`
  - `failed_count`

Use:

```python
    passed_count = state.verification.passed_count if state.verification else 0
    failed_count = state.verification.failed_count if state.verification else 0
```

and add rows:

```python
    table.add_row("passed_count", str(passed_count))
    table.add_row("failed_count", str(failed_count))
```

If `state.verification` exists and `state.verification.failed_count > 0`, print the first failed command below the table:

```python
    first_failed = next(
        (item for item in state.verification.command_results if item.status == "failed"),
        None,
    )
    if first_failed is not None:
        console.print(
            f"First failed command: {first_failed.command} (exit {first_failed.exit_code})"
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/cli/main.py tests/integration/test_cli.py
git commit -m "feat: report verification summaries in cli"
```

### Task 5: Sync Docs And Verify Whole Slice

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_问题记录.md` (only if implementation surfaces a real new issue worth recording)
- Test: `tests/unit/test_verification_schema.py`
- Test: `tests/unit/test_run_state.py`
- Test: `tests/unit/test_runner.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Update README for real verification execution**

Adjust `README.md` so the capabilities section reflects the new behavior:

- change `minimal task run preview` to `task run verification execution`
- change `JSONL trace output for task run previews` to `JSONL trace output for task runs`

The CLI example block should continue to include:

```bash
mendcode task run data/tasks/demo.json
```

- [ ] **Step 2: Update the root development plan**

Update `MendCode_开发方案.md` to reflect:

- Phase 1B first slice is complete
- `run_verification` now executes `verification_commands`
- next priority becomes command-policy tightening or workspace/worktree management

- [ ] **Step 3: Update the problem record if and only if implementation reveals a real new issue**

If a real new engineering issue appears during implementation, add one new entry to `MendCode_问题记录.md` using the existing template. If no meaningful new issue appears, leave this file unchanged.

- [ ] **Step 4: Run the full verification set**

Run: `pytest tests/unit/test_verification_schema.py tests/unit/test_run_state.py tests/unit/test_runner.py tests/integration/test_cli.py -v`
Expected: PASS

Run: `pytest -q`
Expected: PASS with all tests passing

Run: `ruff check .`
Expected: `All checks passed!`

Run: `python -m app.cli.main task run data/tasks/demo.json`
Expected: output includes `Task Run`, `passed_count`, `failed_count`, `run_id`, `trace_path`, and a verification summary

- [ ] **Step 5: Commit**

```bash
git add README.md MendCode_开发方案.md app/schemas/verification.py app/schemas/run_state.py app/schemas/__init__.py app/orchestrator/runner.py app/cli/main.py tests/unit/test_verification_schema.py tests/unit/test_run_state.py tests/unit/test_runner.py tests/integration/test_cli.py
git commit -m "feat: add run verification execution"
```
