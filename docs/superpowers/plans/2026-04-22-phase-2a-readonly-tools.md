# Phase 2A Read-Only Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `read_file` and `search_code` as stable read-only tools with shared path guards, unified result schemas, and focused unit tests.

**Architecture:** Introduce a small `app/tools/` layer that is independent from CLI and runner. Freeze a narrow `ToolResult` contract, centralize workspace path validation in a guard module, and implement both read-only tools as plain functions returning structured results.

**Tech Stack:** Python, Pydantic, pathlib, subprocess, pytest, ruff, ripgrep (`rg`)

---

### Task 1: Add Tool Result Schemas

**Files:**
- Create: `app/tools/__init__.py`
- Create: `app/tools/schemas.py`
- Test: `tests/unit/test_tool_schemas.py`

- [ ] **Step 1: Write the failing schema tests**

```python
from app.tools.schemas import ToolResult


def test_tool_result_accepts_passed_payload() -> None:
    result = ToolResult(
        tool_name="read_file",
        status="passed",
        summary="Read 3 lines from README.md",
        payload={"relative_path": "README.md", "content": "hello"},
        error_message=None,
        workspace_path="/tmp/workspace",
    )

    assert result.tool_name == "read_file"
    assert result.status == "passed"
    assert result.payload["relative_path"] == "README.md"


def test_tool_result_rejects_unknown_fields() -> None:
    payload = {
        "tool_name": "search_code",
        "status": "passed",
        "summary": "Found 1 match",
        "payload": {"matches": []},
        "error_message": None,
        "workspace_path": "/tmp/workspace",
        "extra": "boom",
    }

    try:
        ToolResult.model_validate(payload)
    except Exception as exc:
        assert "extra" in str(exc)
    else:
        raise AssertionError("ToolResult should reject unknown fields")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_tool_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.tools'`

- [ ] **Step 3: Write minimal schema implementation**

```python
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolStatus = Literal["passed", "failed", "rejected"]


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: ToolStatus
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    error_message: str | None = None
    workspace_path: str
```

- [ ] **Step 4: Add module export**

```python
from app.tools.schemas import ToolResult, ToolStatus

__all__ = ["ToolResult", "ToolStatus"]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_tool_schemas.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/tools/__init__.py app/tools/schemas.py tests/unit/test_tool_schemas.py
git commit -m "feat: add tool result schemas"
```

### Task 2: Add Workspace Path Guards

**Files:**
- Create: `app/tools/guard.py`
- Test: `tests/unit/test_tool_guard.py`

- [ ] **Step 1: Write the failing guard tests**

```python
from pathlib import Path

from app.tools.guard import resolve_workspace_file


def test_resolve_workspace_file_returns_file_path(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "README.md"
    target.write_text("demo\n", encoding="utf-8")

    resolved = resolve_workspace_file(workspace_path, "README.md")

    assert resolved == target


def test_resolve_workspace_file_rejects_escape(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    try:
        resolve_workspace_file(workspace_path, "../secret.txt")
    except ValueError as exc:
        assert "workspace" in str(exc)
    else:
        raise AssertionError("escape path should be rejected")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_tool_guard.py -v`
Expected: FAIL with `ModuleNotFoundError` for `app.tools.guard`

- [ ] **Step 3: Write minimal guard implementation**

```python
from pathlib import Path


def resolve_workspace_path(workspace_path: Path, relative_path: str) -> Path:
    resolved_workspace = workspace_path.resolve()
    candidate = (resolved_workspace / relative_path).resolve()
    try:
        candidate.relative_to(resolved_workspace)
    except ValueError as exc:
        raise ValueError("path escapes workspace root") from exc
    return candidate


def resolve_workspace_file(workspace_path: Path, relative_path: str) -> Path:
    candidate = resolve_workspace_path(workspace_path, relative_path)
    if not candidate.exists():
        raise ValueError("path does not exist")
    if candidate.is_dir():
        raise ValueError("path points to a directory")
    return candidate
```

- [ ] **Step 4: Extend tests for missing path and directory misuse**

```python
def test_resolve_workspace_file_rejects_missing_path(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    try:
        resolve_workspace_file(workspace_path, "missing.txt")
    except ValueError as exc:
        assert "does not exist" in str(exc)
    else:
        raise AssertionError("missing path should be rejected")


def test_resolve_workspace_file_rejects_directory(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "nested").mkdir()

    try:
        resolve_workspace_file(workspace_path, "nested")
    except ValueError as exc:
        assert "directory" in str(exc)
    else:
        raise AssertionError("directory path should be rejected")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_tool_guard.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/tools/guard.py tests/unit/test_tool_guard.py
git commit -m "feat: add workspace path guards for tools"
```

### Task 3: Implement `read_file`

**Files:**
- Create: `app/tools/read_only.py`
- Test: `tests/unit/test_read_only_tools.py`

- [ ] **Step 1: Write the failing `read_file` tests**

```python
from pathlib import Path

from app.tools.read_only import read_file


def test_read_file_returns_full_content(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("a\nb\nc\n", encoding="utf-8")

    result = read_file(workspace_path=workspace_path, relative_path="notes.txt")

    assert result.status == "passed"
    assert result.payload["relative_path"] == "notes.txt"
    assert result.payload["content"] == "a\nb\nc\n"
    assert result.payload["total_lines"] == 3


def test_read_file_supports_line_ranges(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("a\nb\nc\nd\n", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        start_line=2,
        end_line=3,
    )

    assert result.status == "passed"
    assert result.payload["content"] == "b\nc\n"
    assert result.payload["start_line"] == 2
    assert result.payload["end_line"] == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_read_only_tools.py -k read_file -v`
Expected: FAIL with `ModuleNotFoundError` for `app.tools.read_only`

- [ ] **Step 3: Write minimal `read_file` implementation**

```python
from pathlib import Path

from app.tools.guard import resolve_workspace_file
from app.tools.schemas import ToolResult


def read_file(
    workspace_path: Path,
    relative_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int | None = None,
) -> ToolResult:
    try:
        target = resolve_workspace_file(workspace_path, relative_path)
        text = target.read_text(encoding="utf-8")
    except (UnicodeDecodeError, ValueError, OSError) as exc:
        status = "rejected" if isinstance(exc, ValueError) else "failed"
        return ToolResult(
            tool_name="read_file",
            status=status,
            summary=f"Unable to read {relative_path}",
            payload={"relative_path": relative_path},
            error_message=str(exc),
            workspace_path=str(workspace_path),
        )

    lines = text.splitlines(keepends=True)
    total_lines = len(lines)
    start = 1 if start_line is None else start_line
    end = total_lines if end_line is None else end_line
    selected = "".join(lines[max(start - 1, 0) : end])
    truncated = False
    if max_chars is not None and len(selected) > max_chars:
        selected = selected[:max_chars]
        truncated = True

    return ToolResult(
        tool_name="read_file",
        status="passed",
        summary=f"Read {relative_path}",
        payload={
            "relative_path": relative_path,
            "start_line": start,
            "end_line": end,
            "total_lines": total_lines,
            "content": selected,
            "truncated": truncated,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )
```

- [ ] **Step 4: Extend tests for truncation and rejection**

```python
def test_read_file_truncates_large_content(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    target = workspace_path / "notes.txt"
    target.write_text("abcdef", encoding="utf-8")

    result = read_file(
        workspace_path=workspace_path,
        relative_path="notes.txt",
        max_chars=3,
    )

    assert result.status == "passed"
    assert result.payload["content"] == "abc"
    assert result.payload["truncated"] is True


def test_read_file_rejects_missing_path(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = read_file(workspace_path=workspace_path, relative_path="missing.txt")

    assert result.status == "rejected"
    assert result.error_message is not None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_read_only_tools.py -k read_file -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/tools/read_only.py tests/unit/test_read_only_tools.py
git commit -m "feat: add read_file tool"
```

### Task 4: Implement `search_code`

**Files:**
- Modify: `app/tools/read_only.py`
- Test: `tests/unit/test_read_only_tools.py`

- [ ] **Step 1: Write the failing `search_code` tests**

```python
from pathlib import Path

from app.tools.read_only import search_code


def test_search_code_returns_matches(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "alpha.py").write_text("needle = 1\n", encoding="utf-8")
    (workspace_path / "beta.py").write_text("other = 2\nneedle = 3\n", encoding="utf-8")

    result = search_code(workspace_path=workspace_path, query="needle")

    assert result.status == "passed"
    assert result.payload["query"] == "needle"
    assert result.payload["total_matches"] == 2
    assert len(result.payload["matches"]) == 2


def test_search_code_rejects_empty_query(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()

    result = search_code(workspace_path=workspace_path, query="")

    assert result.status == "rejected"
    assert result.error_message is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_read_only_tools.py -k search_code -v`
Expected: FAIL with `ImportError` because `search_code` is not defined

- [ ] **Step 3: Write minimal `search_code` implementation**

```python
import subprocess


def search_code(
    workspace_path: Path,
    query: str,
    glob: str | None = None,
    max_results: int | None = None,
) -> ToolResult:
    if not query.strip():
        return ToolResult(
            tool_name="search_code",
            status="rejected",
            summary="Rejected empty query",
            payload={"query": query, "matches": []},
            error_message="query must not be empty",
            workspace_path=str(workspace_path),
        )

    command = ["rg", "--line-number", "--no-heading", query, str(workspace_path)]
    if glob:
        command.extend(["--glob", glob])

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        return ToolResult(
            tool_name="search_code",
            status="failed",
            summary=f"Search failed for {query}",
            payload={"query": query, "matches": []},
            error_message=str(exc),
            workspace_path=str(workspace_path),
        )

    if completed.returncode not in (0, 1):
        return ToolResult(
            tool_name="search_code",
            status="failed",
            summary=f"Search failed for {query}",
            payload={"query": query, "matches": []},
            error_message=completed.stderr.strip() or completed.stdout.strip(),
            workspace_path=str(workspace_path),
        )

    matches = []
    for line in completed.stdout.splitlines():
        file_path, line_number, line_text = line.split(":", 2)
        relative_path = str(Path(file_path).resolve().relative_to(workspace_path.resolve()))
        matches.append(
            {
                "relative_path": relative_path,
                "line_number": int(line_number),
                "line_text": line_text,
            }
        )

    if max_results is not None:
        matches = matches[:max_results]

    return ToolResult(
        tool_name="search_code",
        status="passed",
        summary=f"Found {len(matches)} matches for {query}",
        payload={
            "query": query,
            "glob": glob,
            "total_matches": len(matches),
            "matches": matches,
        },
        error_message=None,
        workspace_path=str(workspace_path),
    )
```

- [ ] **Step 4: Extend tests for `glob`, result limits, and no matches**

```python
def test_search_code_applies_glob_filter(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "alpha.py").write_text("needle = 1\n", encoding="utf-8")
    (workspace_path / "beta.txt").write_text("needle = 2\n", encoding="utf-8")

    result = search_code(workspace_path=workspace_path, query="needle", glob="*.py")

    assert result.status == "passed"
    assert result.payload["total_matches"] == 1
    assert result.payload["matches"][0]["relative_path"] == "alpha.py"


def test_search_code_limits_results(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "alpha.py").write_text("needle = 1\nneedle = 2\n", encoding="utf-8")

    result = search_code(workspace_path=workspace_path, query="needle", max_results=1)

    assert result.status == "passed"
    assert result.payload["total_matches"] == 1


def test_search_code_returns_empty_matches_when_not_found(tmp_path: Path) -> None:
    workspace_path = tmp_path / "workspace"
    workspace_path.mkdir()
    (workspace_path / "alpha.py").write_text("other = 1\n", encoding="utf-8")

    result = search_code(workspace_path=workspace_path, query="needle")

    assert result.status == "passed"
    assert result.payload["total_matches"] == 0
    assert result.payload["matches"] == []
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_read_only_tools.py -k search_code -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/tools/read_only.py tests/unit/test_read_only_tools.py
git commit -m "feat: add search_code tool"
```

### Task 5: Verify Read-Only Tools Slice And Sync Docs

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Verify: `tests/unit/test_tool_schemas.py`
- Verify: `tests/unit/test_tool_guard.py`
- Verify: `tests/unit/test_read_only_tools.py`

- [ ] **Step 1: Update README capability description**

```markdown
- Read-only workspace tools for file reads and code search
```

- [ ] **Step 2: Update `MendCode_开发方案.md` progress section**

```markdown
- Phase 2A 只读工具第一刀已完成：
  - `read_file`
  - `search_code`
  - 工具结果契约与路径边界
```

- [ ] **Step 3: Leave `MendCode_问题记录.md` unchanged unless a real implementation issue occurred**

```markdown
No edit is required here if implementation introduces no real engineering problem.
If a real issue emerges, add one concrete problem entry using the existing document template before final verification.
```

- [ ] **Step 4: Run focused verification**

Run: `python -m pytest tests/unit/test_tool_schemas.py tests/unit/test_tool_guard.py tests/unit/test_read_only_tools.py -v`
Expected: PASS

- [ ] **Step 5: Run full verification**

Run:

```bash
python -m pytest -q
ruff check .
python -m app.cli.main task run data/tasks/demo.json
```

Expected:

- pytest PASS
- ruff PASS
- demo task run still succeeds

- [ ] **Step 6: Commit**

```bash
git add README.md MendCode_开发方案.md MendCode_问题记录.md app/tools tests/unit
git commit -m "docs: record phase 2a read-only tools progress"
```
