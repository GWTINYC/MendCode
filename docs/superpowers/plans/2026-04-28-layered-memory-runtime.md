# Layered Memory Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first production slice of Layered Memory, Memory Recall tools, file summary cache, and trace-derived failure lessons so MendCode can preserve useful project/task context without bloating prompts.

**Architecture:** Keep memory as a local JSONL-backed runtime subsystem under `app/memory/`, with structured records and deterministic search. Expose memory only through `ToolRegistry` schema tools so the model recalls and writes memory through the same permission and observation path as all other local actions. Trace analysis stays read-only by default and produces reviewable `failure_lesson` candidates instead of silently rewriting prompts or code.

**Tech Stack:** Python 3.12, Pydantic, JSONL local store, ToolRegistry, AgentLoop ToolExecutionContext, pytest, ruff.

---

## Scope

This plan implements the first memory/evolution slice only:

- Layered Memory record model and local store.
- File summary cache keyed by path and content hash.
- `memory_search`, `memory_write`, `file_summary_read`, `file_summary_refresh`, and `trace_analyze` schema tools.
- Runtime context wiring so tools can use the same store in TUI, CLI, and tests.
- Trace analyzer that converts failed runs into structured `failure_lesson` candidates.
- Basic metrics fields needed to measure repeated reads and memory recall usage later.

This plan intentionally does **not** implement the full SKILL.md system. Skill discovery and `/debug` / `/review` / `/repo-map` flows should be a follow-up plan after memory recall and trace lessons are stable.

## File Map

- Create: `app/memory/__init__.py`
  - Public exports for memory models, store, and summary helpers.
- Create: `app/memory/models.py`
  - Pydantic models: `MemoryKind`, `MemoryRecord`, `MemorySearchResult`, `FileSummary`.
- Create: `app/memory/store.py`
  - JSONL-backed `MemoryStore` with append, search, list, and atomic rewrite for updates.
- Create: `app/memory/file_summary.py`
  - Builds deterministic summaries and cache records for repo-relative text files.
- Create: `app/runtime/trace_analyzer.py`
  - Parses JSONL trace/conversation events and produces `failure_lesson` memory candidates.
- Create: `app/tools/memory_tools.py`
  - Tool executors for memory and trace analysis.
- Modify: `app/tools/arguments.py`
  - Add argument models for new memory tools.
- Modify: `app/tools/structured.py`
  - Add `memory_store` to `ToolExecutionContext`; add `memory` alias/profile.
- Modify: `app/tools/registry.py`
  - Register new memory and trace tools.
- Modify: `app/runtime/agent_loop.py`
  - Instantiate/pass `MemoryStore` into `ToolExecutionContext`.
- Modify: `app/tui/log_summarizer.py`
  - Compact memory/file-summary/trace-analyze observations.
- Modify: `README.md`
  - Mention local layered memory first slice.
- Modify: `MendCode_开发方案.md`
  - Update current capability and next tasks.
- Modify: `MendCode_问题记录.md`
  - Add memory safety and staleness constraints.

## Task 1: Memory Models and JSONL Store

**Files:**
- Create: `app/memory/__init__.py`
- Create: `app/memory/models.py`
- Create: `app/memory/store.py`
- Test: `tests/unit/test_memory_store.py`

- [ ] **Step 1: Write failing tests for append/search/list**

Create `tests/unit/test_memory_store.py`:

```python
from pathlib import Path

from app.memory.models import MemoryRecord
from app.memory.store import MemoryStore


def test_memory_store_appends_and_searches_records(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    record = MemoryRecord(
        kind="project_fact",
        title="pytest command",
        content="Use python -m pytest -q for full verification.",
        source="test",
        tags=["verification", "pytest"],
    )

    written = store.append(record)
    results = store.search(query="pytest", kinds={"project_fact"}, limit=5)

    assert written.id
    assert len(results) == 1
    assert results[0].record.title == "pytest command"
    assert results[0].score > 0
    assert (tmp_path / "memory" / "memories.jsonl").exists()


def test_memory_store_filters_by_kind_and_tag(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="tool registry",
            content="ToolRegistry owns tool schema and risk.",
            source="test",
            tags=["tools"],
        )
    )
    store.append(
        MemoryRecord(
            kind="failure_lesson",
            title="provider plain text",
            content="Provider must return final_response after tool observations.",
            source="test",
            tags=["provider"],
        )
    )

    results = store.search(query="provider", kinds={"failure_lesson"}, tags={"provider"})

    assert [result.record.kind for result in results] == ["failure_lesson"]
    assert results[0].record.title == "provider plain text"


def test_memory_store_update_rewrites_matching_record(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    original = store.append(
        MemoryRecord(
            kind="task_state",
            title="current task",
            content="Implement memory store.",
            source="test",
            tags=["task"],
        )
    )

    updated = store.update(
        original.id,
        content="Implement memory store and tools.",
        tags=["task", "tools"],
    )
    records = store.list_records()

    assert updated.content == "Implement memory store and tools."
    assert records[0].tags == ["task", "tools"]
    assert len(records) == 1
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_memory_store.py -q
```

Expected: import failure for `app.memory`.

- [ ] **Step 3: Implement memory models**

Create `app/memory/models.py`:

```python
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

MemoryKind = Literal[
    "project_fact",
    "task_state",
    "file_summary",
    "failure_lesson",
    "trace_insight",
]


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: MemoryKind
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=12000)
    source: str = Field(min_length=1, max_length=240)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for tag in tags:
            value = tag.strip().casefold()
            if value and value not in normalized:
                normalized.append(value)
        return normalized


class MemorySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: MemoryRecord
    score: int = Field(ge=0)
    matched_terms: list[str] = Field(default_factory=list)


class FileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content_sha256: str
    mtime_ns: int
    size_bytes: int
    line_count: int
    summary: str
    symbols: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Implement JSONL store**

Create `app/memory/store.py`:

```python
import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from app.memory.models import MemoryKind, MemoryRecord, MemorySearchResult


class MemoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "memories.jsonl"

    def append(self, record: MemoryRecord) -> MemoryRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")
        return record

    def list_records(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        records: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(MemoryRecord.model_validate_json(line))
            except ValidationError:
                continue
        return records

    def search(
        self,
        *,
        query: str,
        kinds: set[MemoryKind] | None = None,
        tags: set[str] | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        terms = _query_terms(query)
        normalized_tags = {tag.casefold() for tag in tags or set()}
        results: list[MemorySearchResult] = []
        for record in self.list_records():
            if kinds is not None and record.kind not in kinds:
                continue
            if normalized_tags and not normalized_tags.intersection(record.tags):
                continue
            score, matched = _score_record(record, terms)
            if score > 0 or not terms:
                results.append(MemorySearchResult(record=record, score=score, matched_terms=matched))
        results.sort(key=lambda result: (result.score, result.record.updated_at), reverse=True)
        return results[:limit]

    def update(self, record_id: str, **changes: object) -> MemoryRecord:
        records = self.list_records()
        updated_record: MemoryRecord | None = None
        rewritten: list[MemoryRecord] = []
        for record in records:
            if record.id != record_id:
                rewritten.append(record)
                continue
            payload = record.model_dump()
            payload.update(changes)
            payload["updated_at"] = datetime.now().astimezone()
            updated_record = MemoryRecord.model_validate(payload)
            rewritten.append(updated_record)
        if updated_record is None:
            raise KeyError(f"unknown memory id: {record_id}")
        self._rewrite(rewritten)
        return updated_record

    def _rewrite(self, records: Iterable[MemoryRecord]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".jsonl.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(record.model_dump_json())
                handle.write("\n")
        temp_path.replace(self.path)


def _query_terms(query: str) -> list[str]:
    return [term for term in query.casefold().replace("_", " ").split() if term]


def _score_record(record: MemoryRecord, terms: list[str]) -> tuple[int, list[str]]:
    haystack = " ".join([record.title, record.content, record.kind, " ".join(record.tags)]).casefold()
    matched = [term for term in terms if term in haystack]
    score = len(matched)
    if any(term in record.title.casefold() for term in terms):
        score += 2
    if any(term in record.tags for term in terms):
        score += 2
    return score, matched
```

Create `app/memory/__init__.py`:

```python
from app.memory.models import FileSummary, MemoryKind, MemoryRecord, MemorySearchResult
from app.memory.store import MemoryStore

__all__ = [
    "FileSummary",
    "MemoryKind",
    "MemoryRecord",
    "MemorySearchResult",
    "MemoryStore",
]
```

- [ ] **Step 5: Run tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_memory_store.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/memory tests/unit/test_memory_store.py
```

Expected: all pass.

Commit:

```bash
git add app/memory tests/unit/test_memory_store.py
git commit -m "add layered memory store"
```

## Task 2: File Summary Cache

**Files:**
- Create: `app/memory/file_summary.py`
- Test: `tests/unit/test_file_summary_cache.py`

- [ ] **Step 1: Write failing file summary tests**

Create `tests/unit/test_file_summary_cache.py`:

```python
from pathlib import Path

from app.memory.file_summary import build_file_summary, summary_record_for_file


def test_build_file_summary_extracts_stable_metadata(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "app.py"
    path.write_text("def run():\n    return 1\n\nclass Worker:\n    pass\n", encoding="utf-8")

    summary = build_file_summary(repo, "app.py")

    assert summary.path == "app.py"
    assert summary.line_count == 5
    assert "def run" in summary.summary
    assert "class Worker" in summary.summary
    assert summary.symbols == ["run", "Worker"]


def test_summary_record_for_file_creates_file_summary_memory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# Demo\n\nHello MendCode.\n", encoding="utf-8")

    record = summary_record_for_file(repo, "README.md")

    assert record.kind == "file_summary"
    assert record.title == "File summary: README.md"
    assert record.metadata["path"] == "README.md"
    assert record.metadata["content_sha256"]
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_file_summary_cache.py -q
```

Expected: import failure for `app.memory.file_summary`.

- [ ] **Step 3: Implement file summary helper**

Create `app/memory/file_summary.py`:

```python
import hashlib
import re
from pathlib import Path

from app.memory.models import FileSummary, MemoryRecord

_SYMBOL_RE = re.compile(r"^(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", re.MULTILINE)


def build_file_summary(repo_path: Path, relative_path: str, *, max_chars: int = 1200) -> FileSummary:
    file_path = _resolve_repo_file(repo_path, relative_path)
    content = file_path.read_text(encoding="utf-8")
    stat = file_path.stat()
    symbols = _extract_symbols(content)
    summary = _summary_text(content, symbols=symbols, max_chars=max_chars)
    return FileSummary(
        path=file_path.relative_to(repo_path).as_posix(),
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        mtime_ns=stat.st_mtime_ns,
        size_bytes=stat.st_size,
        line_count=len(content.splitlines()),
        summary=summary,
        symbols=symbols,
    )


def summary_record_for_file(repo_path: Path, relative_path: str) -> MemoryRecord:
    summary = build_file_summary(repo_path, relative_path)
    return MemoryRecord(
        kind="file_summary",
        title=f"File summary: {summary.path}",
        content=summary.summary,
        source=f"file:{summary.path}",
        tags=["file", summary.path],
        metadata=summary.model_dump(mode="json"),
    )


def _resolve_repo_file(repo_path: Path, relative_path: str) -> Path:
    path = (repo_path / relative_path).resolve()
    repo = repo_path.resolve()
    try:
        path.relative_to(repo)
    except ValueError as exc:
        raise ValueError("file summary path must stay inside repo") from exc
    if not path.is_file():
        raise FileNotFoundError(relative_path)
    return path


def _extract_symbols(content: str) -> list[str]:
    symbols: list[str] = []
    for match in _SYMBOL_RE.finditer(content):
        name = match.group(1)
        if name not in symbols:
            symbols.append(name)
    return symbols


def _summary_text(content: str, *, symbols: list[str], max_chars: int) -> str:
    lines = [line.rstrip() for line in content.splitlines() if line.strip()]
    head = "\n".join(lines[:20])
    symbol_text = f"Symbols: {', '.join(symbols)}\n" if symbols else ""
    text = symbol_text + head
    return text[:max_chars] + ("...[truncated]" if len(text) > max_chars else "")
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_file_summary_cache.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/memory tests/unit/test_file_summary_cache.py
```

Expected: all pass.

Commit:

```bash
git add app/memory/file_summary.py tests/unit/test_file_summary_cache.py
git commit -m "add file summary cache records"
```

## Task 3: Memory Schema Tools

**Files:**
- Modify: `app/tools/arguments.py`
- Modify: `app/tools/structured.py`
- Create: `app/tools/memory_tools.py`
- Modify: `app/tools/registry.py`
- Test: `tests/unit/test_memory_tools.py`
- Test: `tests/unit/test_tool_registry.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/unit/test_memory_tools.py`:

```python
from pathlib import Path

from app.config.settings import Settings
from app.memory.store import MemoryStore
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolExecutionContext


def settings_for(tmp_path: Path) -> Settings:
    return Settings(
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
    )


def context_for(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        memory_store=MemoryStore(tmp_path / "data" / "memory"),
    )


def test_memory_write_and_search_roundtrip(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = context_for(tmp_path)

    write_result = registry.get("memory_write").execute(
        {
            "kind": "project_fact",
            "title": "pytest command",
            "content": "Use python -m pytest -q for full verification.",
            "tags": ["verification"],
        },
        context,
    )
    search_result = registry.get("memory_search").execute(
        {"query": "pytest", "kinds": ["project_fact"], "limit": 5},
        context,
    )

    assert write_result.status == "succeeded"
    assert search_result.payload["total_matches"] == 1
    assert search_result.payload["matches"][0]["title"] == "pytest command"


def test_file_summary_refresh_and_read(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 1\n", encoding="utf-8")
    registry = default_tool_registry()
    context = context_for(tmp_path)

    refresh = registry.get("file_summary_refresh").execute({"path": "app.py"}, context)
    read = registry.get("file_summary_read").execute({"path": "app.py"}, context)

    assert refresh.status == "succeeded"
    assert read.status == "succeeded"
    assert read.payload["path"] == "app.py"
    assert "run" in read.payload["symbols"]
```

Add to `tests/unit/test_tool_registry.py`:

```python
def test_registry_contains_memory_tools() -> None:
    registry = default_tool_registry()
    names = set(registry.names(allowed_tools={"memory"}))

    assert {
        "memory_search",
        "memory_write",
        "file_summary_read",
        "file_summary_refresh",
        "trace_analyze",
    } <= names
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_memory_tools.py tests/unit/test_tool_registry.py::test_registry_contains_memory_tools -q
```

Expected: unknown tool/model failures.

- [ ] **Step 3: Add argument models**

In `app/tools/arguments.py`, add:

```python
class MemorySearchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = ""
    kinds: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    limit: int = Field(default=10, ge=1, le=25)


class MemoryWriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=12000)
    tags: list[str] = Field(default_factory=list)
    source: str = "agent"
    metadata: dict[str, object] = Field(default_factory=dict)


class FileSummaryReadArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class FileSummaryRefreshArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str


class TraceAnalyzeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    trace_path: str
    write_memory: bool = False
```

- [ ] **Step 4: Extend ToolExecutionContext and aliases**

In `app/tools/structured.py`, import `MemoryStore` under `TYPE_CHECKING` or use `Any`, then add to `ToolExecutionContext`:

```python
memory_store: Any | None = None
```

Add alias:

```python
"memory": (
    "memory_search",
    "memory_write",
    "file_summary_read",
    "file_summary_refresh",
    "trace_analyze",
),
```

Add `"memory"` to `coding_agent` and `full_coding_agent`, but do not add `memory_write` to `read_only_agent`. Add only `memory_search` and `file_summary_read` to read-only chat if later needed by TUI.

- [ ] **Step 5: Implement memory tools**

Create `app/tools/memory_tools.py`:

```python
from pathlib import Path

from app.memory.file_summary import build_file_summary, summary_record_for_file
from app.memory.models import MemoryKind, MemoryRecord
from app.memory.store import MemoryStore
from app.runtime.trace_analyzer import analyze_trace
from app.schemas.agent_action import Observation
from app.tools.arguments import (
    FileSummaryReadArgs,
    FileSummaryRefreshArgs,
    MemorySearchArgs,
    MemoryWriteArgs,
    TraceAnalyzeArgs,
)
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def memory_search(args: MemorySearchArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    kinds = set(args.kinds) if args.kinds else None
    results = store.search(
        query=args.query,
        kinds=kinds,  # type: ignore[arg-type]
        tags=set(args.tags) if args.tags else None,
        limit=args.limit,
    )
    matches = [
        {
            "id": result.record.id,
            "kind": result.record.kind,
            "title": result.record.title,
            "content_excerpt": result.record.content[:1200],
            "tags": result.record.tags,
            "score": result.score,
        }
        for result in results
    ]
    return tool_observation(
        tool_name="memory_search",
        status="succeeded",
        summary=f"Found {len(matches)} memory records",
        payload={"total_matches": len(matches), "matches": matches},
    )


def memory_write(args: MemoryWriteArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    record = store.append(
        MemoryRecord(
            kind=args.kind,  # type: ignore[arg-type]
            title=args.title,
            content=args.content,
            source=args.source,
            tags=args.tags,
            metadata=args.metadata,
        )
    )
    return tool_observation(
        tool_name="memory_write",
        status="succeeded",
        summary="Wrote memory record",
        payload={"id": record.id, "kind": record.kind, "title": record.title},
    )


def file_summary_refresh(args: FileSummaryRefreshArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    record = store.append(summary_record_for_file(context.workspace_path, args.path))
    summary = record.metadata
    return tool_observation(
        tool_name="file_summary_refresh",
        status="succeeded",
        summary=f"Refreshed file summary for {args.path}",
        payload={"id": record.id, **summary},
    )


def file_summary_read(args: FileSummaryReadArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    results = store.search(query=args.path, kinds={"file_summary"}, limit=1)
    if results:
        record = results[0].record
        return tool_observation(
            tool_name="file_summary_read",
            status="succeeded",
            summary=f"Read cached file summary for {args.path}",
            payload={**record.metadata, "summary": record.content},
        )
    summary = build_file_summary(context.workspace_path, args.path)
    return tool_observation(
        tool_name="file_summary_read",
        status="succeeded",
        summary=f"Built file summary for {args.path}",
        payload=summary.model_dump(mode="json"),
    )


def trace_analyze(args: TraceAnalyzeArgs, context: ToolExecutionContext) -> Observation:
    store = _memory_store(context)
    insight = analyze_trace(Path(args.trace_path))
    memory_id = None
    if args.write_memory and insight is not None:
        memory_id = store.append(insight).id
    payload = {"memory_id": memory_id, "insight": insight.model_dump(mode="json") if insight else None}
    return tool_observation(
        tool_name="trace_analyze",
        status="succeeded" if insight else "rejected",
        summary="Analyzed trace" if insight else "No trace insight found",
        payload=payload,
    )


def _memory_store(context: ToolExecutionContext) -> MemoryStore:
    if isinstance(context.memory_store, MemoryStore):
        return context.memory_store
    return MemoryStore(context.settings.data_dir / "memory")
```

- [ ] **Step 6: Register tools**

In `app/tools/registry.py`, import new args and executors, then add:

```python
ToolSpec(
    name="memory_search",
    description="Search local layered memory records by query, kind, and tag.",
    args_model=MemorySearchArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=memory_search,
),
ToolSpec(
    name="memory_write",
    description="Write a local layered memory record for future recall.",
    args_model=MemoryWriteArgs,
    risk_level=ToolRisk.WRITE_WORKTREE,
    executor=memory_write,
),
ToolSpec(
    name="file_summary_read",
    description="Read or build a compact summary for a repo-relative file.",
    args_model=FileSummaryReadArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=file_summary_read,
),
ToolSpec(
    name="file_summary_refresh",
    description="Refresh and store a compact summary for a repo-relative file.",
    args_model=FileSummaryRefreshArgs,
    risk_level=ToolRisk.WRITE_WORKTREE,
    executor=file_summary_refresh,
),
ToolSpec(
    name="trace_analyze",
    description="Analyze a MendCode JSONL trace and optionally write a failure lesson memory.",
    args_model=TraceAnalyzeArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=trace_analyze,
),
```

- [ ] **Step 7: Run tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_memory_tools.py tests/unit/test_tool_registry.py::test_registry_contains_memory_tools -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/memory app/tools tests/unit/test_memory_tools.py tests/unit/test_tool_registry.py
```

Expected: all pass.

Commit:

```bash
git add app/memory app/tools tests/unit/test_memory_tools.py tests/unit/test_tool_registry.py
git commit -m "add memory recall tools"
```

## Task 4: Runtime Memory Context Wiring

**Files:**
- Modify: `app/runtime/agent_loop.py`
- Modify: `app/tui/log_summarizer.py`
- Test: `tests/unit/test_agent_loop.py`
- Test: `tests/unit/test_tui_log_summarizer.py`

- [ ] **Step 1: Write failing AgentLoop memory tool test**

Add to `tests/unit/test_agent_loop.py`:

```python
def test_agent_loop_executes_memory_search_with_runtime_store(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    memory_store = MemoryStore(settings.data_dir / "memory")
    memory_store.append(
        MemoryRecord(
            kind="project_fact",
            title="test command",
            content="Use python -m pytest -q.",
            source="test",
            tags=["verification"],
        )
    )
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_memory",
                    name="memory_search",
                    args={"query": "pytest", "limit": 5},
                    source="openai_tool_call",
                )
            ],
            {
                "type": "final_response",
                "status": "completed",
                "summary": "Memory recalled pytest command.",
            },
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(repo_path=tmp_path, problem_statement="recall pytest", provider=provider),
        settings,
    )

    assert result.status == "completed"
    assert result.steps[0].action.action == "memory_search"
    assert result.steps[0].observation.payload["total_matches"] == 1
```

- [ ] **Step 2: Write failing compact log test**

Add to `tests/unit/test_tui_log_summarizer.py`:

```python
def test_compact_agent_loop_result_summarizes_memory_matches() -> None:
    result = AgentLoopResult(
        run_id="agent-memory",
        status="completed",
        summary="done",
        trace_path="/tmp/trace.jsonl",
        steps=[
            AgentStep(
                index=1,
                action=ToolCallAction(
                    type="tool_call",
                    action="memory_search",
                    reason="recall",
                    args={"query": "pytest"},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Found 1 memory records",
                    payload={
                        "total_matches": 1,
                        "matches": [
                            {
                                "id": "m1",
                                "title": "pytest command",
                                "content_excerpt": "Use python -m pytest -q.",
                            }
                        ],
                    },
                ),
            )
        ],
    )

    compact = compact_agent_loop_result(result)

    assert compact["steps"][0]["payload"]["total_matches"] == 1
    assert compact["steps"][0]["payload"]["matches_count"] == 1
```

- [ ] **Step 3: Run tests and verify failures**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py::test_agent_loop_executes_memory_search_with_runtime_store tests/unit/test_tui_log_summarizer.py::test_compact_agent_loop_result_summarizes_memory_matches -q
```

Expected: context lacks memory store or compact payload lacks memory match sampling.

- [ ] **Step 4: Wire MemoryStore into runtime context**

In `app/runtime/agent_loop.py`, create one store per run:

```python
from app.memory.store import MemoryStore

memory_store = MemoryStore(settings.data_dir / "memory")
```

Pass it when constructing `ToolExecutionContext` in native tool execution path:

```python
memory_store=memory_store,
```

- [ ] **Step 5: Extend log summarizer compact keys**

In `app/tui/log_summarizer.py`, ensure `_compact_payload()` preserves:

```python
"memory_id",
"kind",
"title",
"path",
"content_sha256",
"line_count",
"size_bytes",
```

Keep `matches` collection sampling through the existing `matches_count` / `matches_sample` mechanism.

- [ ] **Step 6: Run tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py::test_agent_loop_executes_memory_search_with_runtime_store tests/unit/test_tui_log_summarizer.py::test_compact_agent_loop_result_summarizes_memory_matches -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/runtime/agent_loop.py app/tui/log_summarizer.py tests/unit/test_agent_loop.py tests/unit/test_tui_log_summarizer.py
```

Expected: all pass.

Commit:

```bash
git add app/runtime/agent_loop.py app/tui/log_summarizer.py tests/unit/test_agent_loop.py tests/unit/test_tui_log_summarizer.py
git commit -m "wire memory store into agent runtime"
```

## Task 5: Trace Analyzer for Failure Lessons

**Files:**
- Create: `app/runtime/trace_analyzer.py`
- Test: `tests/unit/test_trace_analyzer.py`

- [ ] **Step 1: Write failing trace analyzer tests**

Create `tests/unit/test_trace_analyzer.py`:

```python
import json
from pathlib import Path

from app.runtime.trace_analyzer import analyze_trace


def write_trace(path: Path, events: list[dict[str, object]]) -> None:
    path.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n",
        encoding="utf-8",
    )


def test_analyze_trace_creates_failure_lesson_for_provider_failure(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.step",
                "message": "Handled action",
                "payload": {
                    "action": {"type": "final_response", "status": "failed"},
                    "observation": {
                        "status": "failed",
                        "summary": "Provider failed",
                        "error_message": "Provider returned plain text without tool call",
                    },
                },
            }
        ],
    )

    lesson = analyze_trace(trace)

    assert lesson is not None
    assert lesson.kind == "failure_lesson"
    assert "Provider failed" in lesson.title
    assert lesson.metadata["category"] == "provider_protocol"


def test_analyze_trace_returns_none_for_successful_trace(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    write_trace(
        trace,
        [
            {
                "event_type": "agent.run.completed",
                "message": "completed",
                "payload": {"status": "completed", "summary": "ok"},
            }
        ],
    )

    assert analyze_trace(trace) is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_trace_analyzer.py -q
```

Expected: import failure.

- [ ] **Step 3: Implement trace analyzer**

Create `app/runtime/trace_analyzer.py`:

```python
import json
from pathlib import Path
from typing import Any

from app.memory.models import MemoryRecord


def analyze_trace(trace_path: Path) -> MemoryRecord | None:
    if not trace_path.exists():
        raise FileNotFoundError(trace_path)
    failed_events = [_failure_payload(event) for event in _read_events(trace_path)]
    failed_events = [event for event in failed_events if event is not None]
    if not failed_events:
        return None
    first = failed_events[0]
    category = _category_for(first)
    summary = str(first.get("summary") or "Unknown failure")
    error_message = str(first.get("error_message") or "")
    return MemoryRecord(
        kind="failure_lesson",
        title=f"{summary} ({category})",
        content=_lesson_content(summary=summary, error_message=error_message, category=category),
        source=f"trace:{trace_path}",
        tags=["trace", "failure", category],
        metadata={
            "category": category,
            "trace_path": str(trace_path),
            "summary": summary,
            "error_message": error_message,
        },
    )


def _read_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _failure_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    observation = payload.get("observation")
    if isinstance(observation, dict) and observation.get("status") in {"failed", "rejected"}:
        return {
            "summary": observation.get("summary"),
            "error_message": observation.get("error_message"),
            "action": payload.get("action"),
        }
    if payload.get("status") == "failed":
        return {"summary": payload.get("summary"), "error_message": payload.get("error_message")}
    return None


def _category_for(payload: dict[str, Any]) -> str:
    text = " ".join(str(payload.get(key) or "") for key in ["summary", "error_message"]).casefold()
    if "provider" in text or "tool call" in text:
        return "provider_protocol"
    if "permission" in text or "confirmation" in text:
        return "permission"
    if "repeated" in text:
        return "tool_repetition"
    if "verification" in text or "run_command" in text:
        return "verification"
    return "runtime_failure"


def _lesson_content(*, summary: str, error_message: str, category: str) -> str:
    return "\n".join(
        [
            f"Category: {category}",
            f"Summary: {summary}",
            f"Error: {error_message or 'none'}",
            "Constraint: future runs should use tool evidence and preserve structured observations.",
        ]
    )
```

- [ ] **Step 4: Run tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_trace_analyzer.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/runtime/trace_analyzer.py tests/unit/test_trace_analyzer.py
```

Expected: all pass.

Commit:

```bash
git add app/runtime/trace_analyzer.py tests/unit/test_trace_analyzer.py
git commit -m "add trace failure analyzer"
```

## Task 6: TUI Scenario Coverage for Memory Recall

**Files:**
- Modify: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Modify: `tests/e2e/test_tui_pty_live.py`

- [ ] **Step 1: Add deterministic scenario for memory recall**

Add a scenario test:

```python
async def test_memory_recall_question_uses_memory_search(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="memory recall",
            repo_files={"README.md": "Demo\n"},
            user_inputs=["之前记录的 pytest 命令是什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="memory_search",
                    status="succeeded",
                    summary="Found 1 memory records",
                    payload={
                        "total_matches": 1,
                        "matches": [
                            {
                                "id": "m1",
                                "kind": "project_fact",
                                "title": "pytest command",
                                "content_excerpt": "Use python -m pytest -q.",
                                "tags": ["verification"],
                                "score": 3,
                            }
                        ],
                    },
                    args={"query": "pytest", "limit": 5},
                )
            ],
            final_summary="之前记录的 pytest 命令是 python -m pytest -q。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_evidence_from_observation(transcript, "memory_search")
    assert_visible_answer_contains(transcript, "python -m pytest -q")
    assert_answer_is_concise(transcript, max_lines=8, max_chars=500)
```

- [ ] **Step 2: Add PTY live test for memory availability**

Add a focused live test that asks for available tools and asserts memory tools are absent from read-only chat until explicitly enabled:

```python
def test_live_tui_read_only_tool_surface_does_not_expose_memory_write(live_repo: Path) -> None:
    result = run_live_tui_question(live_repo, "现在你能用哪些工具", timeout_seconds=90)

    assert_no_provider_failure_or_trace_exposed(result)
    assert_conversation_has_tool_evidence(result, "session_status")
    assert "memory_write" not in _latest_agent_message(result)
```

- [ ] **Step 3: Run scenario tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/scenarios/test_tui_repository_inspection_scenarios.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py::test_live_tui_read_only_tool_surface_does_not_expose_memory_write -q
```

Expected: scenario passes; PTY passes when provider env is configured.

- [ ] **Step 4: Commit**

```bash
git add tests/scenarios/test_tui_repository_inspection_scenarios.py tests/e2e/test_tui_pty_live.py
git commit -m "cover memory recall tui scenarios"
```

## Task 7: Documentation and Final Regression

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_问题记录.md`

- [ ] **Step 1: Update README**

Add to current status:

```markdown
- Layered Memory 第一阶段包括本地 JSONL memory store、`memory_search` / `memory_write`、文件摘要缓存和 trace failure lesson 分析。
```

- [ ] **Step 2: Update development plan**

Add a `3.7 Layered Memory` section:

```markdown
### 3.7 Layered Memory

已完成：

- [x] 本地 JSONL `MemoryStore`
- [x] `project_fact`、`task_state`、`file_summary`、`failure_lesson`、`trace_insight` 记录类型
- [x] `memory_search` / `memory_write`
- [x] `file_summary_read` / `file_summary_refresh`
- [x] `trace_analyze`

当前不足：

- [ ] memory recall 尚未自动进入每轮 prompt，需要由模型显式 tool call
- [ ] memory 去重和过期策略较基础
- [ ] Skill System 尚未接入 memory
```

- [ ] **Step 3: Update problem record**

Add:

```markdown
### 问题：记忆过期和错误沉淀会污染后续推理

状态：基础约束已建立

现象：

本地 memory 能减少重复读取，但如果没有 source、metadata、更新时间和显式检索证据，旧事实可能被模型当成当前事实。

根因：

长期记忆和当前工作区事实的生命周期不同，必须区分记忆召回、工具实时读取和 trace 归因候选。

处理：

MemoryRecord 保存 kind、source、tags、metadata、created_at、updated_at；文件摘要绑定 path、mtime 和 content hash；trace insight 默认只生成候选 lesson。

后续约束：

- 最终回答当前仓库事实时，memory 只能作为线索，关键事实仍应通过文件/git/search 工具确认。
- 写入 failure_lesson 前必须保留 trace_path 或来源。
- 文件摘要 hash 不匹配时必须刷新，不能继续复用旧摘要。
```

- [ ] **Step 4: Run full verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected: all pass. If PTY provider env is missing, record exact missing variables and do not claim PTY success.

- [ ] **Step 5: Commit**

```bash
git add README.md MendCode_开发方案.md MendCode_问题记录.md
git commit -m "document layered memory runtime"
```

## Final Self-Review Checklist

- [ ] Memory records are structured, local, and source-attributed.
- [ ] Memory tools are registered through `ToolRegistry`, not called as hidden side effects.
- [ ] Read-only chat does not expose `memory_write` by default.
- [ ] File summaries are tied to content hash and path.
- [ ] Trace analyzer produces reviewable lessons, not automatic prompt rewrites.
- [ ] Conversation logs compact memory observations.
- [ ] Full pytest, ruff, and PTY live commands have been run after the final commit.
