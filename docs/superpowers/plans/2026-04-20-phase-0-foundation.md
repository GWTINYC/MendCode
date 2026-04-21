# Phase 0 Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 0 MendCode foundation: a Python project skeleton with unified `pyproject.toml` configuration, a minimal CLI, a minimal FastAPI health endpoint, task-file validation, and JSONL trace output.

**Architecture:** Keep the implementation deliberately small. Phase 0 creates only the stable interfaces that Phase 1 will reuse: package metadata, settings/path resolution, task and trace schemas, a trace recorder, CLI commands, and an API health endpoint. It does not implement orchestrator, tools, or worktree execution yet.

**Tech Stack:** Python 3.11+, Typer, FastAPI, Pydantic v2, pytest, ruff, orjson, uvicorn

---

### Task 1: Bootstrap Project Package And Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `app/__init__.py`
- Create: `app/cli/__init__.py`
- Create: `app/api/__init__.py`
- Create: `app/config/__init__.py`
- Create: `app/core/__init__.py`
- Create: `app/schemas/__init__.py`
- Create: `app/tracing/__init__.py`
- Create: `tests/unit/test_app_metadata.py`
- Test: `tests/unit/test_app_metadata.py`

- [ ] **Step 1: Write the failing metadata test**

```python
from app import APP_NAME, __version__


def test_package_metadata():
    assert APP_NAME == "MendCode"
    assert __version__ == "0.1.0"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_app_metadata.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write the minimal package bootstrap**

`pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "mendcode"
description = "A maintenance agent for enterprise local repositories"
readme = "README.md"
requires-python = ">=3.11"
dynamic = ["version"]
dependencies = [
  "fastapi==0.136.0",
  "uvicorn[standard]==0.44.0",
  "pydantic>=2.12,<2.13",
  "python-dotenv==1.2.2",
  "typer==0.24.1",
  "rich==15.0.0",
  "httpx>=0.28,<0.29",
  "orjson==3.11.8",
  "Jinja2==3.1.6",
  "GitPython==3.1.46",
  "tree-sitter==0.25.2",
  "tree-sitter-language-pack==1.6.2",
  "openai==2.32.0",
  "watchfiles==1.1.1",
]

[project.optional-dependencies]
dev = [
  "pytest==9.0.3",
  "pytest-asyncio==1.3.0",
  "ruff==0.15.11",
]

[tool.setuptools.dynamic]
version = {attr = "app.__version__"}

[tool.setuptools.packages.find]
include = ["app*"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I"]
```

`app/__init__.py`

```python
APP_NAME = "MendCode"
__version__ = "0.1.0"
```

Note: keep `app.__version__` as the single source of truth and source the package version from it in `pyproject.toml`.

Create these package markers with the same content:

```python
"""Package marker."""
```

Files:

- `app/cli/__init__.py`
- `app/api/__init__.py`
- `app/config/__init__.py`
- `app/core/__init__.py`
- `app/schemas/__init__.py`
- `app/tracing/__init__.py`

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_app_metadata.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/__init__.py app/cli/__init__.py app/api/__init__.py app/config/__init__.py app/core/__init__.py app/schemas/__init__.py app/tracing/__init__.py tests/unit/test_app_metadata.py
git commit -m "chore: bootstrap project package and tooling"
```

### Task 2: Add Settings And Path Helpers

**Files:**
- Create: `app/config/settings.py`
- Create: `app/core/paths.py`
- Create: `tests/unit/test_settings.py`
- Test: `tests/unit/test_settings.py`

- [ ] **Step 1: Write the failing settings test**

```python
from pathlib import Path

from app.config.settings import get_settings
from app.core.paths import ensure_data_directories


def test_settings_default_paths(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    settings = get_settings()

    assert settings.project_root == tmp_path
    assert settings.data_dir == tmp_path / "data"
    assert settings.tasks_dir == tmp_path / "data" / "tasks"
    assert settings.traces_dir == tmp_path / "data" / "traces"


def test_settings_default_root_without_env(monkeypatch):
    monkeypatch.delenv("MENDCODE_PROJECT_ROOT", raising=False)

    settings = get_settings()

    assert settings.project_root == Path.cwd().resolve()
    assert settings.data_dir == Path.cwd().resolve() / "data"


def test_ensure_data_directories_creates_missing_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    settings = get_settings()

    created = ensure_data_directories(settings)

    assert created == {
        "data_dir": tmp_path / "data",
        "tasks_dir": tmp_path / "data" / "tasks",
        "traces_dir": tmp_path / "data" / "traces",
    }
    assert all(path.exists() for path in created.values())
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_settings.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.config.settings'`

- [ ] **Step 3: Write the minimal settings and path helpers**

`app/config/settings.py`

```python
from os import getenv
from pathlib import Path

from pydantic import BaseModel

from app import APP_NAME, __version__


class Settings(BaseModel):
    app_name: str
    app_version: str
    project_root: Path
    data_dir: Path
    tasks_dir: Path
    traces_dir: Path


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
    )
```

Note: keep `settings.py` side-effect free. If `.env` loading is needed later, do it in CLI or API bootstrap code instead of at module import time.

`app/core/paths.py`

```python
from pathlib import Path

from app.config.settings import Settings


def ensure_data_directories(settings: Settings) -> dict[str, Path]:
    paths = {
        "data_dir": settings.data_dir,
        "tasks_dir": settings.tasks_dir,
        "traces_dir": settings.traces_dir,
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/config/settings.py app/core/paths.py tests/unit/test_settings.py
git commit -m "feat: add settings and path helpers"
```

### Task 3: Add Task Schema And Demo Task Fixture

**Files:**
- Create: `app/schemas/task.py`
- Create: `data/tasks/demo.json`
- Create: `tests/unit/test_task_schema.py`
- Test: `tests/unit/test_task_schema.py`

- [ ] **Step 1: Write the failing task schema tests**

```python
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.task import TaskSpec, load_task_spec


def test_task_spec_accepts_valid_payload(tmp_path):
    payload = {
        "task_id": "demo-ci-001",
        "task_type": "ci_fix",
        "title": "Fix failing unit test",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "pytest failed"},
        "verification_commands": ["pytest -q"],
        "allowed_tools": ["read_file", "search_code"],
        "metadata": {},
    }

    task = TaskSpec.model_validate(payload)

    assert task.task_id == "demo-ci-001"
    assert task.task_type == "ci_fix"
    assert task.repo_path == str(tmp_path)
    assert task.allowed_tools == ["read_file", "search_code"]
    assert task.metadata == {}


def test_task_spec_rejects_invalid_task_type(tmp_path):
    payload = {
        "task_id": "bad-001",
        "task_type": "deploy",
        "title": "Bad task",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "bad"},
        "verification_commands": ["pytest -q"],
        "allowed_tools": [],
        "metadata": {},
    }

    with pytest.raises(ValidationError):
        TaskSpec.model_validate(payload)


def test_task_spec_rejects_unknown_fields(tmp_path):
    payload = {
        "task_id": "bad-002",
        "task_type": "ci_fix",
        "title": "Bad task",
        "repo_path": str(tmp_path),
        "entry_artifacts": {"log": "bad"},
        "verification_commands": ["pytest -q"],
        "allowed_tools": [],
        "metadata": {},
        "unexpected": "value",
    }

    with pytest.raises(ValidationError):
        TaskSpec.model_validate(payload)


def test_load_demo_task_spec_fixture():
    repo_root = Path(__file__).resolve().parents[2]
    task = load_task_spec(repo_root / "data" / "tasks" / "demo.json")

    assert task.task_id == "demo-ci-001"
    assert task.allowed_tools == ["read_file", "search_code"]
    assert task.entry_artifacts["log"] == "pytest failed: test_example"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_task_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.task'`

- [ ] **Step 3: Write the minimal task schema implementation**

`app/schemas/task.py`

```python
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    task_type: Literal["ci_fix", "test_regression_fix", "pr_review"]
    title: str
    repo_path: str
    entry_artifacts: dict[str, Any]
    verification_commands: list[str]
    allowed_tools: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


def load_task_spec(path: str | Path) -> TaskSpec:
    file_path = Path(path)
    payload = json.loads(file_path.read_text(encoding="utf-8"))
    return TaskSpec.model_validate(payload)
```

`data/tasks/demo.json`

```json
{
  "task_id": "demo-ci-001",
  "task_type": "ci_fix",
  "title": "Fix failing unit test",
  "repo_path": ".",
  "entry_artifacts": {
    "log": "pytest failed: test_example"
  },
  "verification_commands": [
    "pytest -q"
  ],
  "allowed_tools": [
    "read_file",
    "search_code"
  ],
  "metadata": {}
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_task_schema.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/task.py data/tasks/demo.json tests/unit/test_task_schema.py
git commit -m "feat: add task schema and demo fixture"
```

### Task 4: Add Trace Schema And JSONL Recorder

**Files:**
- Create: `app/schemas/trace.py`
- Create: `app/tracing/recorder.py`
- Create: `tests/unit/test_trace_recorder.py`
- Test: `tests/unit/test_trace_recorder.py`

- [ ] **Step 1: Write the failing trace recorder tests**

```python
import json
from datetime import UTC, datetime

import pytest
from app.schemas.trace import TraceEvent
from app.tracing.recorder import TraceRecorder


def test_trace_event_serializes_expected_fields():
    event = TraceEvent(
        run_id="run-001",
        event_type="task.show",
        message="Previewed task",
        timestamp=datetime(2026, 4, 20, tzinfo=UTC),
        payload={"task_id": "demo-ci-001"},
    )

    serialized = event.model_dump(mode="json")

    assert serialized["run_id"] == "run-001"
    assert serialized["event_type"] == "task.show"
    assert serialized["message"] == "Previewed task"
    assert serialized["payload"]["task_id"] == "demo-ci-001"
    assert isinstance(serialized["timestamp"], str)


@pytest.mark.parametrize(
    "run_id",
    ["", "../bad", "bad/name", r"bad\\name", " bad", ".hidden", "trail.", "con"],
)
def test_trace_event_rejects_unsafe_run_id(run_id):
    with pytest.raises(ValueError):
        TraceEvent(run_id=run_id, event_type="task.show", message="bad")


def test_trace_recorder_writes_jsonl_file(tmp_path):
    recorder = TraceRecorder(base_dir=tmp_path)
    event = TraceEvent(
        run_id="run-001",
        event_type="task.show",
        message="Previewed task",
        payload={"task_id": "demo-ci-001"},
    )

    output_path = recorder.record(event)

    lines = output_path.read_text(encoding="utf-8").strip().splitlines()
    payload = json.loads(lines[0])

    assert output_path.name == "run-001.jsonl"
    assert len(lines) == 1
    assert payload["run_id"] == "run-001"
    assert payload["event_type"] == "task.show"
    assert payload["message"] == "Previewed task"
    assert payload["payload"]["task_id"] == "demo-ci-001"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_trace_recorder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.schemas.trace'`

- [ ] **Step 3: Write the minimal trace schema and recorder**

`app/schemas/trace.py`

```python
import re
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TraceEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    event_type: str
    message: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)

    @field_validator("run_id")
    @classmethod
    def validate_run_id(cls, value: str) -> str:
        if not value:
            raise ValueError("run_id must not be empty")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
            raise ValueError("run_id must be a safe filename segment")
        if value.endswith("."):
            raise ValueError("run_id must not end with a dot")
        if value.lower() in {"con", "prn", "aux", "nul", "com1", "lpt1"}:
            raise ValueError("run_id uses a reserved filename")
        return value
```

`app/tracing/recorder.py`

```python
from pathlib import Path

import orjson

from app.schemas.trace import TraceEvent


class TraceRecorder:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def record(self, event: TraceEvent) -> Path:
        output_path = self.base_dir / f"{event.run_id}.jsonl"
        with output_path.open("ab") as handle:
            handle.write(orjson.dumps(event.model_dump(mode="json")))
            handle.write(b"\n")
        return output_path
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/unit/test_trace_recorder.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/schemas/trace.py app/tracing/recorder.py tests/unit/test_trace_recorder.py
git commit -m "feat: add trace schema and recorder"
```

### Task 5: Add The CLI Health And Task Commands

**Files:**
- Create: `app/cli/main.py`
- Create: `tests/integration/test_cli.py`
- Modify: `pyproject.toml`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write the failing CLI integration tests**

```python
import json
from pathlib import Path

import orjson
from typer.testing import CliRunner

from app.cli.main import app


runner = CliRunner()


def write_task_file(path: Path) -> Path:
    task_file = path / "task.json"
    task_file.write_text(
        json.dumps(
            {
                "task_id": "demo-ci-001",
                "task_type": "ci_fix",
                "title": "Fix failing unit test",
                "repo_path": str(path),
                "entry_artifacts": {"log": "pytest failed"},
                "verification_commands": ["pytest -q"],
                "allowed_tools": ["read_file", "search_code"],
                "metadata": {},
            }
        ),
        encoding="utf-8",
    )
    return task_file


def test_health_command_reports_status(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    result = runner.invoke(app, ["health"])

    assert result.exit_code == 0
    assert "MendCode" in result.stdout
    assert "status" in result.stdout
    assert str(tmp_path / "data" / "traces") in result.stdout


def test_task_validate_command_accepts_valid_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "validate", str(task_file)])

    assert result.exit_code == 0
    assert "Task file is valid" in result.stdout
    assert "demo-ci-001" in result.stdout


def test_task_validate_returns_user_facing_error_for_missing_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    result = runner.invoke(app, ["task", "validate", str(tmp_path / "missing.json")])

    assert result.exit_code != 0
    assert "Task file not found" in result.stdout


def test_task_validate_returns_user_facing_error_for_directory_input(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))

    result = runner.invoke(app, ["task", "validate", str(tmp_path)])

    assert result.exit_code != 0
    assert "Task file could not be read" in result.stdout


def test_task_show_writes_trace_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MENDCODE_PROJECT_ROOT", str(tmp_path))
    task_file = write_task_file(tmp_path)

    result = runner.invoke(app, ["task", "show", str(task_file)])

    trace_dir = tmp_path / "data" / "traces"
    trace_files = list(trace_dir.glob("*.jsonl"))

    assert result.exit_code == 0
    assert "Fix failing unit test" in result.stdout
    assert len(trace_files) == 1
    payload = orjson.loads(trace_files[0].read_bytes().splitlines()[0])
    assert payload["event_type"] == "task.show"
    assert payload["payload"]["task_id"] == "demo-ci-001"
    assert payload["payload"]["title"] == "Fix failing unit test"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cli.main'`

- [ ] **Step 3: Write the minimal CLI implementation**

Update `pyproject.toml` to add the script entry point:

```toml
[project.scripts]
mendcode = "app.cli.main:app"
```

`app/cli/main.py`

```python
import json
from pathlib import Path
from uuid import uuid4

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from app.config.settings import get_settings
from app.core.paths import ensure_data_directories
from app.schemas.task import load_task_spec
from app.schemas.trace import TraceEvent
from app.tracing.recorder import TraceRecorder

app = typer.Typer(help="MendCode CLI")
task_app = typer.Typer(help="Task file utilities")
app.add_typer(task_app, name="task")
console = Console()


@app.command()
def version() -> None:
    settings = get_settings()
    console.print(f"{settings.app_name} {settings.app_version}")


@app.command()
def health() -> None:
    settings = get_settings()
    ensure_data_directories(settings)

    table = Table(title="MendCode Health")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("app", settings.app_name)
    table.add_row("version", settings.app_version)
    table.add_row("status", "ok")
    table.add_row("project_root", str(settings.project_root))
    table.add_row("tasks_dir", str(settings.tasks_dir))
    table.add_row("traces_dir", str(settings.traces_dir))
    console.print(table)


@task_app.command("validate")
def validate_task(file_path: Path) -> None:
    try:
        task = load_task_spec(file_path)
    except FileNotFoundError:
        console.print(f"Task file not found: {file_path}")
        raise typer.Exit(code=1)
    except json.JSONDecodeError as exc:
        console.print(f"Task file is not valid JSON: {exc}")
        raise typer.Exit(code=1)
    except ValidationError as exc:
        console.print(f"Task file failed schema validation: {exc}")
        raise typer.Exit(code=1)
    except OSError as exc:
        console.print(f"Task file could not be read: {exc}")
        raise typer.Exit(code=1)
    console.print(f"Task file is valid: {task.task_id} ({task.task_type})")


@task_app.command("show")
def show_task(file_path: Path) -> None:
    try:
        task = load_task_spec(file_path)
    except FileNotFoundError:
        console.print(f"Task file not found: {file_path}")
        raise typer.Exit(code=1)
    except json.JSONDecodeError as exc:
        console.print(f"Task file is not valid JSON: {exc}")
        raise typer.Exit(code=1)
    except ValidationError as exc:
        console.print(f"Task file failed schema validation: {exc}")
        raise typer.Exit(code=1)
    except OSError as exc:
        console.print(f"Task file could not be read: {exc}")
        raise typer.Exit(code=1)
    settings = get_settings()
    ensure_data_directories(settings)
    recorder = TraceRecorder(settings.traces_dir)
    run_id = f"preview-{uuid4().hex[:12]}"
    trace_path = recorder.record(
        TraceEvent(
            run_id=run_id,
            event_type="task.show",
            message="Previewed task file",
            payload={
                "task_id": task.task_id,
                "task_type": task.task_type,
                "title": task.title,
            },
        )
    )

    table = Table(title="Task Preview")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("task_id", task.task_id)
    table.add_row("task_type", task.task_type)
    table.add_row("title", task.title)
    table.add_row("repo_path", task.repo_path)
    table.add_row("trace_path", str(trace_path))
    console.print(table)


if __name__ == "__main__":
    app()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml app/cli/main.py tests/integration/test_cli.py
git commit -m "feat: add cli health and task commands"
```

### Task 6: Add The FastAPI Health Endpoint

**Files:**
- Create: `app/api/server.py`
- Create: `tests/integration/test_api.py`
- Test: `tests/integration/test_api.py`

- [ ] **Step 1: Write the failing API test**

```python
from fastapi.testclient import TestClient

from app.api.server import app


client = TestClient(app)


def test_healthz_returns_status_payload():
    response = client.get("/healthz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "MendCode"
    assert payload["status"] == "ok"
    assert "timestamp" in payload
    assert "traces_dir" in payload
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/integration/test_api.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.server'`

- [ ] **Step 3: Write the minimal FastAPI server**

`app/api/server.py`

```python
from datetime import UTC, datetime

from fastapi import FastAPI

from app.config.settings import get_settings
from app.core.paths import ensure_data_directories

app = FastAPI(title="MendCode API", version="0.1.0")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    settings = get_settings()
    ensure_data_directories(settings)
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "status": "ok",
        "timestamp": datetime.now(UTC).isoformat(),
        "project_root": str(settings.project_root),
        "tasks_dir": str(settings.tasks_dir),
        "traces_dir": str(settings.traces_dir),
    }
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/integration/test_api.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/server.py tests/integration/test_api.py
git commit -m "feat: add api health endpoint"
```

### Task 7: Add Minimal README Usage And Run Smoke Verification

**Files:**
- Modify: `README.md`
- Test: `tests/unit/test_app_metadata.py`
- Test: `tests/unit/test_settings.py`
- Test: `tests/unit/test_task_schema.py`
- Test: `tests/unit/test_trace_recorder.py`
- Test: `tests/integration/test_cli.py`
- Test: `tests/integration/test_api.py`

- [ ] **Step 1: Update the README with Phase 0 usage**

Replace `README.md` with:

````markdown
# MendCode

一款专为企业本地环境设计的代码维护 Agent。

## Phase 0 Capabilities

- Python project skeleton with `pyproject.toml`
- CLI health check and task file inspection
- FastAPI health endpoint
- JSONL trace output for task previews

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

## CLI

```bash
mendcode version
mendcode health
mendcode task validate data/tasks/demo.json
mendcode task show data/tasks/demo.json
```

## API

```bash
uvicorn app.api.server:app --reload
```
````

- [ ] **Step 2: Run the complete verification suite**

Run: `pytest -v`
Expected: PASS

Run: `ruff check .`
Expected: PASS

Run: `python -m app.cli.main health`
Expected: exits 0 and prints a health table containing `status` and `MendCode`

Run: `python -m app.cli.main task validate data/tasks/demo.json`
Expected: exits 0 and prints `Task file is valid`

Run: `python -m app.cli.main task show data/tasks/demo.json`
Expected: exits 0, prints the task title, and creates one `.jsonl` file under `data/traces/`

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add phase 0 usage guide"
```

### Task 8: Final Phase 0 Verification Checkpoint

**Files:**
- Modify: none
- Test: all previously created test files

- [ ] **Step 1: Re-run the acceptance commands**

Run: `pytest -v`
Expected: PASS for all unit and integration tests

Run: `ruff check .`
Expected: PASS

Run: `python -m app.cli.main health`
Expected: exits 0

Run: `python -m app.cli.main task validate data/tasks/demo.json`
Expected: exits 0

Run: `python -m app.cli.main task show data/tasks/demo.json`
Expected: exits 0 and writes a trace file

Run: `python -c "from fastapi.testclient import TestClient; from app.api.server import app; print(TestClient(app).get('/healthz').status_code)"`
Expected: prints `200`

- [ ] **Step 2: Inspect the resulting tree**

Run: `find app data tests -maxdepth 3 -type f | sort`
Expected: includes:

- `app/cli/main.py`
- `app/api/server.py`
- `app/config/settings.py`
- `app/core/paths.py`
- `app/schemas/task.py`
- `app/schemas/trace.py`
- `app/tracing/recorder.py`
- `data/tasks/demo.json`
- `tests/unit/test_app_metadata.py`
- `tests/unit/test_settings.py`
- `tests/unit/test_task_schema.py`
- `tests/unit/test_trace_recorder.py`
- `tests/integration/test_cli.py`
- `tests/integration/test_api.py`

- [ ] **Step 3: Commit**

```bash
git status --short
```

Expected: clean working tree except for intentionally untracked local artifacts such as ad-hoc trace output if not gitignored yet
