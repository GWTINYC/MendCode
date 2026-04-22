# Phase 2B Fixed-Flow Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `task run` from verification-only execution to a fixed `read -> search -> patch -> verify` flow that can complete one real demo repair attempt.

**Architecture:** Keep `run_task_preview()` as the single entrypoint, but extract the fixed-flow parsing and tool orchestration into a small helper module so `runner.py` does not become a dumping ground. Extend `RunState` and trace events just enough to express tool-driven execution, and prove the flow with one narrow demo task plus runner/CLI coverage.

**Tech Stack:** Python, Pydantic, pathlib, pytest, Typer, JSONL trace recording, existing workspace/tool modules

---

## File Structure

- Create: `app/orchestrator/fixed_flow.py`
  Parses fixed-flow `entry_artifacts`, records tool call summaries, and runs the fixed locate/inspect/patch path inside a workspace.
- Modify: `app/orchestrator/runner.py`
  Calls the fixed-flow helper before verification, records tool trace events, and returns enriched `RunState`.
- Modify: `app/schemas/run_state.py`
  Expands `current_step` and adds minimal fixed-flow execution fields.
- Modify: `tests/unit/test_runner.py`
  Covers fixed-flow success/failure semantics and trace ordering.
- Modify: `tests/integration/test_cli.py`
  Updates CLI task fixtures to the new structured demo task and verifies visible fixed-flow output remains stable.
- Modify: `app/cli/main.py`
  Prints the new fixed-flow state fields so CLI output stays aligned with `RunState`.
- Modify: `data/tasks/demo.json`
  Replaces the old verification-only demo task with one fixed-flow repair demo.
- Modify: `README.md`
  Documents that the demo task now exercises the fixed fixed-flow repair path instead of verification-only preview.

### Task 1: Add Fixed-Flow Artifact Parsing

**Files:**
- Create: `app/orchestrator/fixed_flow.py`
- Test: `tests/unit/test_runner.py`

- [ ] **Step 1: Write the failing artifact validation tests**

```python
def test_run_task_preview_fails_when_fixed_flow_inputs_are_missing(tmp_path):
    repo_path = init_git_repo(tmp_path)
    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Missing fixed-flow inputs",
        repo_path=str(repo_path),
        entry_artifacts={
            "old_text": "demo",
            "new_text": "fixed",
        },
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "failed"
    assert result.current_step == "summarize"
    assert result.summary == "Fixed-flow input invalid: either read_target_path or search_query is required"


def test_run_task_preview_accepts_direct_target_path_without_search_query(tmp_path, monkeypatch):
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "target.txt"
    target.write_text("wrong\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add target"], cwd=repo_path, check=True, capture_output=True, text=True)

    monkeypatch.setattr(
        "app.orchestrator.runner.read_file",
        lambda **kwargs: ToolResult(
            tool_name="read_file",
            status="passed",
            summary="Read target.txt",
            payload={"relative_path": "target.txt", "content": "wrong\n"},
            error_message=None,
            workspace_path=str(kwargs["workspace_path"]),
        ),
    )
    monkeypatch.setattr(
        "app.orchestrator.runner.apply_patch",
        lambda **kwargs: ToolResult(
            tool_name="apply_patch",
            status="passed",
            summary="Patched target.txt",
            payload={"relative_path": "target.txt", "replacements_applied": 1, "replace_all": False},
            error_message=None,
            workspace_path=str(kwargs["workspace_path"]),
        ),
    )

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Direct path fixed flow",
        repo_path=str(repo_path),
        entry_artifacts={
            "read_target_path": "target.txt",
            "old_text": "wrong",
            "new_text": "fixed",
        },
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "completed"
    assert result.selected_files == ["target.txt"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runner.py -k "fixed_flow_inputs_are_missing or direct_target_path_without_search_query" -v`
Expected: FAIL because `RunState` has no `selected_files` and runner does not validate fixed-flow inputs

- [ ] **Step 3: Create a minimal fixed-flow helper module**

```python
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

from app.tools.schemas import ToolResult


class FixedFlowArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    search_query: str | None = None
    target_path_glob: str | None = None
    read_target_path: str | None = None
    read_start_line: int | None = None
    read_end_line: int | None = None
    old_text: str
    new_text: str
    expected_verification_hint: str | None = None

    @model_validator(mode="after")
    def validate_targeting(self) -> "FixedFlowArtifacts":
        if self.read_target_path is None and (self.search_query is None or not self.search_query.strip()):
            raise ValueError("either read_target_path or search_query is required")
        return self


def load_fixed_flow_artifacts(payload: dict[str, object]) -> FixedFlowArtifacts:
    return FixedFlowArtifacts.model_validate(payload)


def summarize_tool_result(result: ToolResult) -> dict[str, object]:
    return {
        "tool_name": result.tool_name,
        "status": result.status,
        "summary": result.summary,
        "error_message": result.error_message,
        "payload": {
            key: value
            for key, value in result.payload.items()
            if key not in {"content", "matches"}
        },
    }
```

- [ ] **Step 4: Re-run the focused tests**

Run: `python -m pytest tests/unit/test_runner.py -k "fixed_flow_inputs_are_missing or direct_target_path_without_search_query" -v`
Expected: still FAIL, but now due to runner not using the helper yet

- [ ] **Step 5: Commit the helper scaffold**

```bash
git add app/orchestrator/fixed_flow.py tests/unit/test_runner.py
git commit -m "feat: add fixed-flow artifact parsing helpers"
```

### Task 2: Extend RunState for Tool-Driven Execution

**Files:**
- Modify: `app/schemas/run_state.py`
- Test: `tests/unit/test_run_state.py`

- [ ] **Step 1: Write the failing RunState schema tests**

```python
def test_run_state_accepts_fixed_flow_fields():
    state = RunState(
        run_id="preview-123",
        task_id="demo-ci-001",
        task_type="ci_fix",
        status="running",
        current_step="locate",
        summary="Locating target file",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/workspace",
        selected_files=["target.txt"],
        applied_patch=False,
        tool_results=[{"tool_name": "search_code", "status": "passed"}],
        verification=None,
    )

    assert state.current_step == "locate"
    assert state.selected_files == ["target.txt"]


def test_run_state_rejects_unknown_step_name():
    with pytest.raises(ValidationError):
        RunState(
            run_id="preview-123",
            task_id="demo-ci-001",
            task_type="ci_fix",
            status="running",
            current_step="plan",
            summary="Bad step",
            trace_path="/tmp/trace.jsonl",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_run_state.py -k "fixed_flow_fields or unknown_step_name" -v`
Expected: FAIL because `selected_files`, `applied_patch`, and `tool_results` are not defined

- [ ] **Step 3: Extend `RunState` minimally**

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    task_type: TaskType
    status: Literal["running", "completed", "failed"]
    current_step: Literal["bootstrap", "locate", "inspect", "patch", "verify", "summarize"]
    summary: str
    trace_path: str
    workspace_path: str | None = None
    selected_files: list[str] = Field(default_factory=list)
    applied_patch: bool = False
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    verification: VerificationResult | None = None
```

- [ ] **Step 4: Re-run the RunState tests**

Run: `python -m pytest tests/unit/test_run_state.py -k "fixed_flow_fields or unknown_step_name" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/run_state.py tests/unit/test_run_state.py
git commit -m "feat: extend run state for fixed-flow execution"
```

### Task 3: Add Runner-Level Tool Trace Semantics

**Files:**
- Modify: `app/orchestrator/runner.py`
- Test: `tests/unit/test_runner.py`

- [ ] **Step 1: Write the failing trace tests for tool events**

```python
def test_run_task_preview_records_tool_events_for_fixed_flow(tmp_path, monkeypatch):
    repo_path = init_git_repo(tmp_path)
    (repo_path / "target.txt").write_text("wrong\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add target"], cwd=repo_path, check=True, capture_output=True, text=True)

    monkeypatch.setattr(
        "app.orchestrator.runner.search_code",
        lambda **kwargs: ToolResult(
            tool_name="search_code",
            status="passed",
            summary="Found 1 match",
            payload={"query": "wrong", "glob": "*.txt", "total_matches": 1, "matches": [{"relative_path": "target.txt", "line_number": 1, "line_text": "wrong"}]},
            error_message=None,
            workspace_path=str(kwargs["workspace_path"]),
        ),
    )
    monkeypatch.setattr(
        "app.orchestrator.runner.read_file",
        lambda **kwargs: ToolResult(
            tool_name="read_file",
            status="passed",
            summary="Read target.txt",
            payload={"relative_path": "target.txt", "content": "wrong\n"},
            error_message=None,
            workspace_path=str(kwargs["workspace_path"]),
        ),
    )
    monkeypatch.setattr(
        "app.orchestrator.runner.apply_patch",
        lambda **kwargs: ToolResult(
            tool_name="apply_patch",
            status="passed",
            summary="Patched target.txt",
            payload={"relative_path": "target.txt", "replacements_applied": 1, "replace_all": False},
            error_message=None,
            workspace_path=str(kwargs["workspace_path"]),
        ),
    )

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Fixed-flow success",
        repo_path=str(repo_path),
        entry_artifacts={
            "search_query": "wrong",
            "target_path_glob": "*.txt",
            "old_text": "wrong",
            "new_text": "fixed",
        },
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))
    events = [json.loads(line) for line in Path(result.trace_path).read_text(encoding="utf-8").splitlines()]

    assert [event["event_type"] for event in events].count("run.tool.started") == 3
    assert [event["event_type"] for event in events].count("run.tool.completed") == 3
    assert result.selected_files == ["target.txt"]
    assert result.applied_patch is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runner.py -k "records_tool_events_for_fixed_flow" -v`
Expected: FAIL because runner does not import tools or record `run.tool.*` events

- [ ] **Step 3: Add small runner helpers for tool tracing**

```python
from app.orchestrator.fixed_flow import load_fixed_flow_artifacts, summarize_tool_result
from app.tools.patch import apply_patch
from app.tools.read_only import read_file, search_code


def _record_tool_started(recorder: TraceRecorder, run_id: str, tool_name: str, workspace_path: Path) -> Path:
    return recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.tool.started",
            message=f"Started tool {tool_name}",
            payload={"tool_name": tool_name, "workspace_path": str(workspace_path)},
        )
    )


def _record_tool_completed(recorder: TraceRecorder, run_id: str, result: ToolResult) -> Path:
    return recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="run.tool.completed",
            message=f"Completed tool {result.tool_name}",
            payload=summarize_tool_result(result) | {"workspace_path": result.workspace_path},
        )
    )
```

- [ ] **Step 4: Re-run the focused trace test**

Run: `python -m pytest tests/unit/test_runner.py -k "records_tool_events_for_fixed_flow" -v`
Expected: still FAIL, but now because the fixed-flow orchestration itself is not wired

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator/runner.py tests/unit/test_runner.py
git commit -m "feat: add fixed-flow tool trace events"
```

### Task 4: Wire the Fixed `locate -> inspect -> patch -> verify` Flow

**Files:**
- Modify: `app/orchestrator/runner.py`
- Modify: `tests/unit/test_runner.py`

- [ ] **Step 1: Write the failing fixed-flow runner tests**

```python
def test_run_task_preview_runs_fixed_flow_before_verification(tmp_path):
    repo_path = init_git_repo(tmp_path)
    target = repo_path / "target.txt"
    target.write_text("wrong\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add target"], cwd=repo_path, check=True, capture_output=True, text=True)

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Real fixed-flow success",
        repo_path=str(repo_path),
        entry_artifacts={
            "search_query": "wrong",
            "target_path_glob": "*.txt",
            "old_text": "wrong",
            "new_text": "fixed",
        },
        verification_commands=[
            f"{PYTHON} -c \"from pathlib import Path; import sys; sys.exit(0 if Path('target.txt').read_text(encoding='utf-8') == 'fixed\\n' else 1)\""
        ],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "completed"
    assert result.current_step == "summarize"
    assert result.selected_files == ["target.txt"]
    assert result.applied_patch is True
    assert result.verification is not None
    assert result.verification.status == "passed"


def test_run_task_preview_fails_when_search_returns_multiple_files(tmp_path):
    repo_path = init_git_repo(tmp_path)
    for name in ("a.txt", "b.txt"):
        (repo_path / name).write_text("wrong\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt", "b.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add duplicates"], cwd=repo_path, check=True, capture_output=True, text=True)

    task = TaskSpec(
        task_id="demo-ci-001",
        task_type="ci_fix",
        title="Ambiguous search",
        repo_path=str(repo_path),
        entry_artifacts={
            "search_query": "wrong",
            "target_path_glob": "*.txt",
            "old_text": "wrong",
            "new_text": "fixed",
        },
        verification_commands=[f"{PYTHON} -c \"print('ok')\""],
    )

    result = run_task_preview(task, build_settings(tmp_path))

    assert result.status == "failed"
    assert result.summary == "Fixed-flow failed: search_code returned 2 candidate files"
    assert result.selected_files == []
    assert result.applied_patch is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_runner.py -k "runs_fixed_flow_before_verification or search_returns_multiple_files" -v`
Expected: FAIL because runner still skips tool flow entirely

- [ ] **Step 3: Implement the fixed flow minimally**

```python
def _build_failed_state(
    *,
    run_id: str,
    task: TaskSpec,
    trace_path: Path,
    workspace_path: Path | None,
    summary: str,
    selected_files: list[str],
    applied_patch: bool,
    tool_results: list[dict[str, object]],
    verification: VerificationResult | None = None,
) -> RunState:
    return RunState(
        run_id=run_id,
        task_id=task.task_id,
        task_type=task.task_type,
        status="failed",
        current_step="summarize",
        summary=summary,
        trace_path=str(trace_path),
        workspace_path=str(workspace_path) if workspace_path is not None else None,
        selected_files=selected_files,
        applied_patch=applied_patch,
        tool_results=tool_results,
        verification=verification,
    )


artifacts = load_fixed_flow_artifacts(task.entry_artifacts)
selected_files: list[str] = []
applied_patch = False
tool_results: list[dict[str, object]] = []

if artifacts.read_target_path is not None:
    selected_files = [artifacts.read_target_path]
else:
    trace_path = _record_tool_started(recorder, run_id, "search_code", workspace_path)
    search_result = search_code(
        workspace_path=workspace_path,
        query=artifacts.search_query or "",
        glob=artifacts.target_path_glob,
        max_results=2,
    )
    tool_results.append(summarize_tool_result(search_result))
    trace_path = _record_tool_completed(recorder, run_id, search_result)
    if search_result.status != "passed":
        return _build_failed_state(
            run_id=run_id,
            task=task,
            trace_path=trace_path,
            workspace_path=workspace_path,
            summary=f"Fixed-flow failed: {search_result.summary}",
            selected_files=[],
            applied_patch=False,
            tool_results=tool_results,
        )

    matches = search_result.payload["matches"]
    if len(matches) != 1:
        return _build_failed_state(
            run_id=run_id,
            task=task,
            trace_path=trace_path,
            workspace_path=workspace_path,
            summary=f"Fixed-flow failed: search_code returned {len(matches)} candidate files",
            selected_files=[],
            applied_patch=False,
            tool_results=tool_results,
        )
    selected_files = [matches[0]["relative_path"]]

trace_path = _record_tool_started(recorder, run_id, "read_file", workspace_path)
read_result = read_file(
    workspace_path=workspace_path,
    relative_path=selected_files[0],
    start_line=artifacts.read_start_line,
    end_line=artifacts.read_end_line,
)
tool_results.append(summarize_tool_result(read_result))
trace_path = _record_tool_completed(recorder, run_id, read_result)
if read_result.status != "passed":
    return _build_failed_state(
        run_id=run_id,
        task=task,
        trace_path=trace_path,
        workspace_path=workspace_path,
        summary=f"Fixed-flow failed: {read_result.summary}",
        selected_files=selected_files,
        applied_patch=False,
        tool_results=tool_results,
    )

trace_path = _record_tool_started(recorder, run_id, "apply_patch", workspace_path)
patch_result = apply_patch(
    workspace_path=workspace_path,
    relative_path=selected_files[0],
    old_text=artifacts.old_text,
    new_text=artifacts.new_text,
)
tool_results.append(summarize_tool_result(patch_result))
trace_path = _record_tool_completed(recorder, run_id, patch_result)
if patch_result.status != "passed":
    return _build_failed_state(
        run_id=run_id,
        task=task,
        trace_path=trace_path,
        workspace_path=workspace_path,
        summary=f"Fixed-flow failed: {patch_result.summary}",
        selected_files=selected_files,
        applied_patch=False,
        tool_results=tool_results,
    )
applied_patch = True
```

- [ ] **Step 4: Re-run the focused fixed-flow runner tests**

Run: `python -m pytest tests/unit/test_runner.py -k "runs_fixed_flow_before_verification or search_returns_multiple_files or records_tool_events_for_fixed_flow" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/orchestrator/runner.py tests/unit/test_runner.py
git commit -m "feat: wire fixed-flow tool execution into runner"
```

### Task 5: Update Demo Task and CLI Coverage

**Files:**
- Modify: `data/tasks/demo.json`
- Modify: `tests/integration/test_cli.py`
- Modify: `app/cli/main.py`
- Modify: `README.md`

- [ ] **Step 1: Write the failing CLI and demo-task tests**

```python
def write_task_file(path: Path) -> Path:
    repo_path = init_git_repo(path)
    (repo_path / "target.txt").write_text("wrong\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "add target"], cwd=repo_path, check=True, capture_output=True, text=True)

    task_file = path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-001",
                "task_type": "ci_fix",
                "title": "Fixed-flow demo repair",
                "repo_path": str(repo_path),
                "entry_artifacts": {
                    "search_query": "wrong",
                    "target_path_glob": "*.txt",
                    "old_text": "wrong",
                    "new_text": "fixed",
                },
                "verification_commands": [
                    f"{PYTHON} -c \"from pathlib import Path; import sys; sys.exit(0 if Path('target.txt').read_text(encoding='utf-8') == 'fixed\\n' else 1)\""
                ],
                "allowed_tools": ["read_file", "search_code", "apply_patch"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def test_task_run_prints_fixed_flow_state(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "run", str(task_file)], terminal_width=200)

    assert result.exit_code == 0
    assert "selected_files" in result.stdout
    assert "applied_patch" in result.stdout
    assert "target.txt" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/integration/test_cli.py -k "prints_fixed_flow_state" -v`
Expected: FAIL because CLI output does not yet expose the new fixed-flow fields

- [ ] **Step 3: Update demo task, CLI assertions, and README**

```json
{
  "task_id": "demo-ci-001",
  "task_type": "ci_fix",
  "title": "Fixed-flow demo repair",
  "repo_path": ".",
  "entry_artifacts": {
    "search_query": "JSONL trace output for task runs",
    "target_path_glob": "README.md",
    "old_text": "JSONL trace output for task runs",
    "new_text": "JSONL trace output for fixed-flow task runs"
  },
  "verification_commands": [
    "python -c \"from pathlib import Path; import sys; sys.exit(0 if 'JSONL trace output for fixed-flow task runs' in Path('README.md').read_text(encoding='utf-8') else 1)\""
  ],
  "allowed_tools": ["read_file", "search_code", "apply_patch"],
  "metadata": {}
}
```

```python
table.add_row("selected_files", ", ".join(state.selected_files))
table.add_row("applied_patch", "yes" if state.applied_patch else "no")
assert "selected_files" in result.stdout
assert "applied_patch" in result.stdout
assert "target.txt" in result.stdout
assert "completed" in result.stdout
```

```markdown
- CLI health check, task file inspection, and `task run` fixed-flow execution inside a per-run git worktree
- `task run` can execute a narrow `read -> search -> patch -> verify` demo task using structured `entry_artifacts`
```

- [ ] **Step 4: Run focused CLI tests and one end-to-end verification**

Run: `python -m pytest tests/integration/test_cli.py -k "task_run" -v`
Expected: PASS

Run: `python -m pytest tests/unit/test_runner.py -k "fixed_flow" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/cli/main.py data/tasks/demo.json tests/integration/test_cli.py README.md
git commit -m "feat: add fixed-flow demo task coverage"
```

### Task 6: Final Verification

**Files:**
- Verify only

- [ ] **Step 1: Run the focused fixed-flow test set**

Run: `python -m pytest tests/unit/test_run_state.py tests/unit/test_runner.py tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 2: Run full test suite**

Run: `python -m pytest -v`
Expected: PASS

- [ ] **Step 3: Run lint**

Run: `ruff check .`
Expected: `All checks passed!`

- [ ] **Step 4: Commit final cleanup only if verification required code changes**

```bash
git add .
git commit -m "chore: finalize fixed-flow loop slice"
```
