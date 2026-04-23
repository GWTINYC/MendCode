# MVP Eval and Python Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the fastest useful MVP by adding a minimal batch eval path, one real Python unit-test repair demo, and the docs needed to run and understand the result.

**Architecture:** Reuse the existing single-task fixed-flow runner as the only execution path. Add a thin eval layer that batches task files, normalizes `RunState` into stable summary artifacts, and writes JSON/Markdown reports under `data/evals/`. Add one repo-native Python demo that still uses `task run` and `run_task_preview()` without any special-case execution path.

**Tech Stack:** Python, Pydantic, Typer, pathlib, pytest, Rich, JSON/Markdown file output, existing fixed-flow runner and worktree/executor modules

---

## File Structure

- Create: `app/schemas/eval.py`
  Defines the stable machine-readable eval summary models.
- Create: `app/eval/__init__.py`
  Package marker for eval helpers.
- Create: `app/eval/batch.py`
  Runs a list of task files through the existing runner and writes `summary.json` / `summary.md`.
- Create: `tests/unit/test_eval_schema.py`
  Covers the new eval summary schema.
- Create: `tests/unit/test_batch_eval.py`
  Covers batch execution, summary normalization, and file output.
- Create: `data/demo-fixtures/python-unit-fix/buggy_math.py`
  Tiny Python source file with a deliberate bug.
- Create: `data/demo-fixtures/python-unit-fix/checks/buggy_math_check.py`
  Verification target proving the bug exists and then passes after patching.
- Create: `data/tasks/demos/python-unit-fix.json`
  Fifth demo task that performs a real Python source edit and runs `pytest`.
- Modify: `app/config/settings.py`
  Adds `evals_dir` to runtime settings.
- Modify: `app/core/paths.py`
  Ensures `data/evals/` is created with the other runtime directories.
- Modify: `app/cli/main.py`
  Adds `eval run` CLI entrypoint that executes batch eval and prints summary paths/counts.
- Modify: `tests/unit/test_settings.py`
  Covers the new `evals_dir` setting and directory creation.
- Modify: `.gitignore`
  Ignores runtime `data/evals/` output.
- Modify: `tests/unit/test_repo_hygiene.py`
  Locks in the new ignore rule.
- Modify: `tests/unit/test_task_schema.py`
  Extends the demo-suite assertions to include `python-unit-fix.json`.
- Modify: `tests/integration/test_cli.py`
  Covers the new eval CLI and the fifth demo fixture.
- Modify: `README.md`
  Documents the MVP batch eval path and the Python repair demo.
- Modify: `MendCode_开发方案.md`
  Syncs the root development plan with the MVP status and next step.
- Modify: `MendCode_问题记录.md`
  Records any real engineering issue discovered while landing eval/demo support.
- Modify: `MendCode_全局路线图.md`
  Updates the route from “next build eval” to “MVP eval landed / next compare iterations”.

### Task 1: Add Eval Settings and Summary Schema

**Files:**
- Create: `app/schemas/eval.py`
- Create: `tests/unit/test_eval_schema.py`
- Modify: `app/config/settings.py`
- Modify: `app/core/paths.py`
- Modify: `tests/unit/test_settings.py`
- Modify: `.gitignore`
- Modify: `tests/unit/test_repo_hygiene.py`

- [ ] **Step 1: Write the failing settings and hygiene tests**

```python
def test_settings_exposes_evals_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    settings = get_settings()

    assert settings.evals_dir == tmp_path / "data" / "evals"


def test_ensure_data_directories_creates_evals_directory(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    settings = get_settings()

    created = ensure_data_directories(settings)

    assert created["evals_dir"] == tmp_path / "data" / "evals"
    assert created["evals_dir"].exists()


def test_gitignore_covers_eval_runtime_artifacts() -> None:
    contents = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "data/evals/" in contents
```

- [ ] **Step 2: Run the focused settings and hygiene tests to verify they fail**

Run: `python -m pytest tests/unit/test_settings.py tests/unit/test_repo_hygiene.py -k "evals_directory or eval_runtime_artifacts" -v`
Expected: FAIL because `Settings` has no `evals_dir`, `ensure_data_directories()` does not create it, and `.gitignore` does not list `data/evals/`

- [ ] **Step 3: Write the failing eval schema tests**

```python
from app.schemas.eval import BatchEvalResult, BatchEvalSummary


def test_batch_eval_result_accepts_runner_summary_fields():
    result = BatchEvalResult(
        task_id="demo-ci-success",
        task_type="ci_fix",
        task_file="data/tasks/demos/success.json",
        status="completed",
        current_step="summarize",
        summary="Verification passed: 1/1 commands succeeded",
        passed_count=1,
        failed_count=0,
        applied_patch=True,
        tool_results=[{"tool_name": "search_code", "status": "passed"}],
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/workspace",
    )

    assert result.task_id == "demo-ci-success"
    assert result.applied_patch is True


def test_batch_eval_summary_rejects_mismatched_result_counts():
    with pytest.raises(ValidationError):
        BatchEvalSummary(
            run_id="eval-123",
            task_count=2,
            completed_count=2,
            failed_count=0,
            output_dir="/tmp/evals/eval-123",
            summary_json_path="/tmp/evals/eval-123/summary.json",
            summary_md_path="/tmp/evals/eval-123/summary.md",
            results=[
                BatchEvalResult(
                    task_id="demo-ci-success",
                    task_type="ci_fix",
                    task_file="data/tasks/demos/success.json",
                    status="completed",
                    current_step="summarize",
                    summary="ok",
                    passed_count=1,
                    failed_count=0,
                    applied_patch=True,
                    tool_results=[],
                    trace_path="/tmp/trace.jsonl",
                    workspace_path="/tmp/workspace",
                )
            ],
        )
```

- [ ] **Step 4: Run the eval schema tests to verify they fail**

Run: `python -m pytest tests/unit/test_eval_schema.py -v`
Expected: FAIL because `app.schemas.eval` does not exist yet

- [ ] **Step 5: Implement the minimal settings changes**

```python
class Settings(BaseModel):
    app_name: str
    app_version: str
    project_root: Path
    data_dir: Path
    tasks_dir: Path
    traces_dir: Path
    evals_dir: Path
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
        evals_dir=data_dir / "evals",
        workspace_root=root / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
    )
```

```python
def ensure_data_directories(settings: Settings) -> dict[str, Path]:
    paths = {
        "data_dir": settings.data_dir,
        "tasks_dir": settings.tasks_dir,
        "traces_dir": settings.traces_dir,
        "evals_dir": settings.evals_dir,
        "workspace_root": settings.workspace_root,
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
```

```gitignore
.worktrees/
data/traces/
data/evals/
.pytest_cache/
.ruff_cache/
__pycache__/
*.py[cod]
```

- [ ] **Step 6: Implement the minimal eval schema module**

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.task import TaskType


class BatchEvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: TaskType
    task_file: str
    status: Literal["completed", "failed"]
    current_step: Literal["bootstrap", "locate", "inspect", "patch", "verify", "summarize"]
    summary: str
    passed_count: int
    failed_count: int
    applied_patch: bool
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    trace_path: str
    workspace_path: str | None = None


class BatchEvalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_count: int
    completed_count: int
    failed_count: int
    output_dir: str
    summary_json_path: str
    summary_md_path: str
    results: list[BatchEvalResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_counts(self) -> "BatchEvalSummary":
        if self.task_count != len(self.results):
            raise ValueError("task_count must match the number of results")
        if self.completed_count + self.failed_count != self.task_count:
            raise ValueError("completed_count and failed_count must add up to task_count")
        return self
```

- [ ] **Step 7: Re-run the focused tests**

Run: `python -m pytest tests/unit/test_settings.py tests/unit/test_repo_hygiene.py tests/unit/test_eval_schema.py -v`
Expected: PASS

- [ ] **Step 8: Commit the settings/schema slice**

```bash
git add app/config/settings.py app/core/paths.py app/schemas/eval.py tests/unit/test_settings.py tests/unit/test_repo_hygiene.py tests/unit/test_eval_schema.py .gitignore
git commit -m "feat: add eval settings and summary schema"
```

### Task 2: Add Batch Eval Engine and CLI

**Files:**
- Create: `app/eval/__init__.py`
- Create: `app/eval/batch.py`
- Create: `tests/unit/test_batch_eval.py`
- Modify: `app/cli/main.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing unit test for batch eval output**

```python
def test_run_batch_eval_writes_json_and_markdown_summaries(tmp_path, monkeypatch):
    settings = build_settings(tmp_path)
    ensure_data_directories(settings)

    task_paths = []
    for task_id in ("demo-ci-success", "demo-ci-fail"):
        task_path = tmp_path / f"{task_id}.json"
        task_path.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "task_type": "ci_fix",
                    "title": task_id,
                    "repo_path": str(tmp_path),
                    "entry_artifacts": {},
                    "verification_commands": [],
                    "metadata": {},
                }
            ),
            encoding="utf-8",
        )
        task_paths.append(task_path)

    def fake_run_task_preview(task, settings):
        status = "completed" if task.task_id == "demo-ci-success" else "failed"
        return RunState(
            run_id=f"preview-{task.task_id}",
            task_id=task.task_id,
            task_type=task.task_type,
            status=status,
            current_step="summarize" if status == "completed" else "verify",
            summary="ok" if status == "completed" else "boom",
            trace_path=str(tmp_path / "data" / "traces" / f"{task.task_id}.jsonl"),
            workspace_path=str(tmp_path / ".worktrees" / task.task_id),
            selected_files=[],
            applied_patch=status == "completed",
            tool_results=[],
            verification=None,
        )

    monkeypatch.setattr("app.eval.batch.run_task_preview", fake_run_task_preview)

    summary = run_batch_eval(task_paths, settings)

    assert summary.task_count == 2
    assert summary.completed_count == 1
    assert summary.failed_count == 1
    assert Path(summary.summary_json_path).exists()
    assert Path(summary.summary_md_path).exists()
```

- [ ] **Step 2: Run the batch eval unit test to verify it fails**

Run: `python -m pytest tests/unit/test_batch_eval.py -v`
Expected: FAIL because `app.eval.batch` does not exist

- [ ] **Step 3: Write the failing CLI test for `eval run`**

```python
def test_eval_run_writes_summary_files(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    monkeypatch.setattr("app.cli.main.console.width", 200, raising=False)

    task_file = write_task_file(tmp_path)
    failing_task = write_failing_task_file(tmp_path)

    result = runner.invoke(
        app,
        ["eval", "run", str(task_file), str(failing_task)],
        terminal_width=200,
    )

    assert result.exit_code == 0
    assert "Batch Eval" in result.stdout
    assert "task_count" in result.stdout
    assert "summary_json_path" in result.stdout
    assert "summary_md_path" in result.stdout
```

- [ ] **Step 4: Run the focused CLI test to verify it fails**

Run: `python -m pytest tests/integration/test_cli.py -k eval_run_writes_summary_files -v`
Expected: FAIL because the CLI has no `eval` command yet

- [ ] **Step 5: Implement the minimal batch eval engine**

```python
from pathlib import Path
from uuid import uuid4

import orjson

from app.orchestrator.runner import run_task_preview
from app.schemas.eval import BatchEvalResult, BatchEvalSummary
from app.schemas.task import load_task_spec


def _result_from_run_state(task_file: Path, state: RunState) -> BatchEvalResult:
    passed_count = state.verification.passed_count if state.verification is not None else 0
    failed_count = state.verification.failed_count if state.verification is not None else 0
    return BatchEvalResult(
        task_id=state.task_id,
        task_type=state.task_type,
        task_file=str(task_file),
        status=state.status,
        current_step=state.current_step,
        summary=state.summary,
        passed_count=passed_count,
        failed_count=failed_count,
        applied_patch=state.applied_patch,
        tool_results=state.tool_results,
        trace_path=state.trace_path,
        workspace_path=state.workspace_path,
    )


def _render_markdown(summary: BatchEvalSummary) -> str:
    lines = [
        "# Batch Eval Summary",
        "",
        f"- run_id: `{summary.run_id}`",
        f"- task_count: `{summary.task_count}`",
        f"- completed_count: `{summary.completed_count}`",
        f"- failed_count: `{summary.failed_count}`",
        "",
        "| task_id | status | current_step | applied_patch | summary |",
        "| --- | --- | --- | --- | --- |",
    ]
    for result in summary.results:
        lines.append(
            f"| {result.task_id} | {result.status} | {result.current_step} | "
            f"{'yes' if result.applied_patch else 'no'} | {result.summary} |"
        )
    lines.append("")
    return "\n".join(lines)


def run_batch_eval(task_files: list[Path], settings: Settings) -> BatchEvalSummary:
    run_id = f"eval-{uuid4().hex[:12]}"
    output_dir = settings.evals_dir / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for task_file in task_files:
        task = load_task_spec(task_file)
        state = run_task_preview(task, settings)
        results.append(_result_from_run_state(task_file, state))

    summary_json_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"
    summary = BatchEvalSummary(
        run_id=run_id,
        task_count=len(results),
        completed_count=sum(1 for result in results if result.status == "completed"),
        failed_count=sum(1 for result in results if result.status == "failed"),
        output_dir=str(output_dir),
        summary_json_path=str(summary_json_path),
        summary_md_path=str(summary_md_path),
        results=results,
    )

    summary_json_path.write_bytes(orjson.dumps(summary.model_dump(mode="json"), option=orjson.OPT_INDENT_2))
    summary_md_path.write_text(_render_markdown(summary), encoding="utf-8")
    return summary
```

- [ ] **Step 6: Add the minimal eval CLI**

```python
eval_app = typer.Typer(help="Batch evaluation utilities")
app.add_typer(eval_app, name="eval")


@eval_app.command("run")
def run_eval(task_files: list[Path]) -> None:
    if not task_files:
        typer.echo("At least one task file is required")
        raise typer.Exit(code=1)

    settings = get_settings()
    ensure_data_directories(settings)
    summary = run_batch_eval(task_files, settings)

    table = Table(title="Batch Eval")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("run_id", summary.run_id)
    table.add_row("task_count", str(summary.task_count))
    table.add_row("completed_count", str(summary.completed_count))
    table.add_row("failed_count", str(summary.failed_count))
    table.add_row("summary_json_path", summary.summary_json_path)
    table.add_row("summary_md_path", summary.summary_md_path)
    console.print(table)
```

- [ ] **Step 7: Re-run the focused unit and CLI tests**

Run: `python -m pytest tests/unit/test_batch_eval.py tests/integration/test_cli.py -k "batch_eval or eval_run_writes_summary_files" -v`
Expected: PASS

- [ ] **Step 8: Commit the batch eval slice**

```bash
git add app/eval/__init__.py app/eval/batch.py app/cli/main.py tests/unit/test_batch_eval.py tests/integration/test_cli.py
git commit -m "feat: add batch eval cli"
```

### Task 3: Add the Python Unit-Fix Demo and Fold It into the Demo Suite

**Files:**
- Create: `data/demo-fixtures/python-unit-fix/buggy_math.py`
- Create: `data/demo-fixtures/python-unit-fix/checks/buggy_math_check.py`
- Create: `data/tasks/demos/python-unit-fix.json`
- Modify: `tests/unit/test_task_schema.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing demo-suite schema tests for the fifth fixture**

```python
def test_demo_task_suite_files_exist():
    demo_dir = Path(__file__).resolve().parents[2] / "data" / "tasks" / "demos"

    assert (demo_dir / "success.json").exists()
    assert (demo_dir / "unauthorized-tool.json").exists()
    assert (demo_dir / "ambiguous-search.json").exists()
    assert (demo_dir / "verification-fail.json").exists()
    assert (demo_dir / "python-unit-fix.json").exists()


def test_load_task_spec_from_python_unit_fix_demo_fixture():
    fixture_path = (
        Path(__file__).resolve().parents[2]
        / "data"
        / "tasks"
        / "demos"
        / "python-unit-fix.json"
    )
    task = load_task_spec(fixture_path)

    assert task.task_id == "demo-ci-python-unit-fix"
    assert task.entry_artifacts["search_query"] == "return a - b"
    assert task.entry_artifacts["target_path_glob"] == "data/demo-fixtures/python-unit-fix/buggy_math.py"
```

- [ ] **Step 2: Run the focused schema tests to verify they fail**

Run: `python -m pytest tests/unit/test_task_schema.py -k "demo_task_suite_files_exist or python_unit_fix_demo_fixture" -v`
Expected: FAIL because `python-unit-fix.json` does not exist yet

- [ ] **Step 3: Create the buggy Python fixture**

```python
# data/demo-fixtures/python-unit-fix/buggy_math.py
def add(a: int, b: int) -> int:
    return a - b
```

```python
# data/demo-fixtures/python-unit-fix/checks/buggy_math_check.py
import sys
from pathlib import Path

FIXTURE_ROOT = Path(__file__).resolve().parents[1]
if str(FIXTURE_ROOT) not in sys.path:
    sys.path.insert(0, str(FIXTURE_ROOT))

from buggy_math import add


def test_add_returns_sum():
    assert add(2, 3) == 5
```

The check file intentionally does not use a `test_*.py` filename under a `tests/`
directory. It must be runnable by explicit `pytest` path for the demo task, but it
must not be collected by broad project-level commands such as `python -m pytest .`
before the demo repair has patched `buggy_math.py`.

- [ ] **Step 4: Create the demo task file**

```json
{
  "task_id": "demo-ci-python-unit-fix",
  "task_type": "ci_fix",
  "title": "Python unit test repair demo",
  "repo_path": ".",
  "entry_artifacts": {
    "search_query": "return a - b",
    "target_path_glob": "data/demo-fixtures/python-unit-fix/buggy_math.py",
    "old_text": "return a - b",
    "new_text": "return a + b"
  },
  "verification_commands": [
    "python -m pytest data/demo-fixtures/python-unit-fix/checks/buggy_math_check.py -q"
  ],
  "allowed_tools": [
    "read_file",
    "search_code",
    "apply_patch"
  ],
  "metadata": {}
}
```

- [ ] **Step 5: Add the failing CLI coverage for the fifth demo**

```python
def test_task_validate_accepts_python_unit_fix_demo(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "python-unit-fix.json"

    result = runner.invoke(app, ["task", "validate", str(fixture_path)])

    assert result.exit_code == 0
    assert "demo-ci-python-unit-fix" in result.stdout


def test_python_unit_fix_demo_completes(monkeypatch):
    fixture_root = configure_repo_native_demo_env(monkeypatch)
    fixture_path = fixture_root / "python-unit-fix.json"

    result = runner.invoke(app, ["task", "run", str(fixture_path)], terminal_width=200)

    assert result.exit_code == 0
    assert "demo-ci-python-unit-fix" in result.stdout
    assert "completed" in result.stdout
    assert "Verification passed: 1/1 commands succeeded" in result.stdout
```

- [ ] **Step 6: Run the focused schema and CLI tests**

Run: `python -m pytest tests/unit/test_task_schema.py tests/integration/test_cli.py -k "python_unit_fix or demo_task_suite_files_exist" -v`
Expected: PASS

- [ ] **Step 7: Commit the Python demo slice**

```bash
git add data/demo-fixtures/python-unit-fix/buggy_math.py data/demo-fixtures/python-unit-fix/checks/buggy_math_check.py data/tasks/demos/python-unit-fix.json tests/unit/test_task_schema.py tests/integration/test_cli.py
git commit -m "feat: add python unit-fix demo task"
```

### Task 4: Document the MVP Path and Sync Root Docs

**Files:**
- Modify: `README.md`
- Modify: `tests/integration/test_cli.py`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_问题记录.md`
- Modify: `MendCode_全局路线图.md`

- [ ] **Step 1: Strengthen the README contract test for the MVP eval command**

```python
def test_readme_references_mvp_eval_commands():
    readme = (repo_root / "README.md").read_text(encoding="utf-8")

    assert "python -m app.cli.main eval run" in readme
    assert "summary.json" in readme
    assert "summary.md" in readme
    assert "python-unit-fix.json" in readme
```

- [ ] **Step 2: Run the focused README test to verify it fails**

Run: `python -m pytest tests/integration/test_cli.py -k readme_references_mvp_eval_commands -v`
Expected: FAIL because README does not mention batch eval or the Python unit-fix demo yet

- [ ] **Step 3: Update README with the MVP path**

```markdown
## MVP Eval

Run the full MVP demo suite:

    python -m app.cli.main eval run \
      data/tasks/demos/success.json \
      data/tasks/demos/unauthorized-tool.json \
      data/tasks/demos/ambiguous-search.json \
      data/tasks/demos/verification-fail.json \
      data/tasks/demos/python-unit-fix.json

Result files are written under `data/evals/eval-<id>/`:

- `summary.json`: machine-readable eval summary
- `summary.md`: quick human-readable summary

`python-unit-fix.json` is the first real code-repair demo: it patches a Python source file in a worktree and proves the fix by making `pytest` pass.
```

- [ ] **Step 4: Update the root docs to reflect MVP progress**

```markdown
In `MendCode_开发方案.md`, add a short section that Phase 2C has advanced from demo-suite alignment to MVP landing, with current focus on batch eval and one real Python repair demo.

In `MendCode_问题记录.md`, append any real issue discovered while landing batch eval or repo-native Python demo support, using the existing template.

In `MendCode_全局路线图.md`, change the near-term priority from “build minimum batch eval” to “batch eval landed; next compare iterations and expand demos only if needed.”
```

- [ ] **Step 5: Re-run the focused README test**

Run: `python -m pytest tests/integration/test_cli.py -k "readme_references_mvp_eval_commands or readme_references_demo_task_suite_paths" -v`
Expected: PASS

- [ ] **Step 6: Run full verification**

Run: `python -m pytest -q`
Expected: PASS

Run: `ruff check .`
Expected: `All checks passed!`

- [ ] **Step 7: Commit the docs slice**

```bash
git add README.md tests/integration/test_cli.py MendCode_开发方案.md MendCode_问题记录.md MendCode_全局路线图.md
git commit -m "docs: document mvp eval workflow"
```
