# Context Memory Evolution Runtime Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first main-path framework for context management, memory recall/review candidates, and trace-driven lesson candidate generation.

**Architecture:** Add `ContextManager`, `MemoryRuntime`, and `EvolutionRuntime` as focused runtime boundaries, then wire them into `app.runtime.agent_loop.run_agent_loop_turn`. Preserve the current provider message shape while moving ownership of memory recall and context metrics out of AgentLoop.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing MendCode AgentLoop, ToolRegistry, MemoryStore, JSONL trace, Textual TUI scenario tests.

---

## File Structure

Create:

- `app/context/__init__.py` exports context runtime models and manager.
- `app/context/models.py` defines `ContextItem`, `ContextBudget`, `ContextMetrics`, `ContextWarning`, and `ContextBundle`.
- `app/context/metrics.py` contains observation metric helpers, especially repeated `read_file` detection.
- `app/context/manager.py` owns turn context construction, memory recall calls, observation recording, and JSON provider context generation.
- `app/memory/recall.py` defines compact memory recall result models.
- `app/memory/review_queue.py` persists reviewable lesson candidates in `data/memory/review_queue.jsonl`.
- `app/memory/runtime.py` wraps `MemoryStore`, recall, duplicate-aware writes, file summary access, and review queue operations.
- `app/evolution/__init__.py` exports evolution models and runtime.
- `app/evolution/models.py` defines lesson candidate, evolution input, and evolution result models.
- `app/evolution/lesson_builder.py` contains deterministic signal extraction from turn status, observations, and context metrics.
- `app/evolution/runtime.py` calls the lesson builder and writes candidates to `MemoryRuntime`.
- `tests/unit/test_context_manager.py`
- `tests/unit/test_memory_runtime.py`
- `tests/unit/test_evolution_runtime.py`

Modify:

- `app/runtime/agent_loop.py` to instantiate and use the new runtime layers.
- `app/agent/loop.py` to add optional `context_summary` and `evolution_summary` fields to `AgentLoopResult`.
- `app/runtime/turn.py` to mirror the same summary fields for runtime-facing results.
- `tests/unit/test_agent_loop.py` to assert main-path context/evolution behavior.
- `MendCode_开发方案.md` after implementation to reflect the new module boundaries and remaining gaps.
- `MendCode_问题记录.md` only if the implementation exposes a new recurring risk.

Do not modify provider adapters unless a test proves that the existing `context: str | None` contract cannot carry the new `ContextBundle`.

---

## Task 1: Context Models, Metrics, and Manager

**Files:**

- Create: `app/context/__init__.py`
- Create: `app/context/models.py`
- Create: `app/context/metrics.py`
- Create: `app/context/manager.py`
- Test: `tests/unit/test_context_manager.py`

- [ ] **Step 1: Write failing tests for context bundle creation and observation metrics**

Create `tests/unit/test_context_manager.py`:

```python
import json
from pathlib import Path

from app.agent.provider import AgentObservationRecord
from app.context.manager import ContextManager
from app.context.models import ContextBudget
from app.memory.models import MemoryRecord
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.schemas.agent_action import Observation, ToolCallAction
from app.tools.structured import ToolInvocation


def _memory_runtime(tmp_path: Path) -> MemoryRuntime:
    return MemoryRuntime(MemoryStore(tmp_path / "memory"))


def test_context_manager_builds_provider_context_with_memory_recall(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="pytest command",
            content="Use python -m pytest -q for verification.",
            source="test",
            tags=["pytest"],
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(store),
        base_context='{"session":"demo"}',
        budget=ContextBudget(max_memory_items=3),
    )

    bundle = manager.begin_turn(
        user_message="之前记录的 pytest 命令是什么",
        repo_path=tmp_path,
    )

    payload = json.loads(bundle.provider_context)
    assert payload["base_context"] == {"session": "demo"}
    assert payload["memory_recall"][0]["title"] == "pytest command"
    assert bundle.metrics.memory_recall_hits == 1
    assert bundle.metrics.context_chars == len(bundle.provider_context)


def test_context_manager_records_read_file_repetition(tmp_path: Path) -> None:
    manager = ContextManager(memory_runtime=_memory_runtime(tmp_path))
    manager.begin_turn(user_message="read twice", repo_path=tmp_path)

    for index in range(2):
        manager.record_observation(
            AgentObservationRecord(
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect",
                    args={"path": "README.md"},
                ),
                tool_invocation=ToolInvocation(
                    id=f"call_{index}",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read README.md",
                    payload={"relative_path": "README.md", "content": "demo"},
                ),
            )
        )

    bundle = manager.build_provider_context()

    assert bundle.metrics.observation_count == 2
    assert bundle.metrics.read_file_count == 2
    assert bundle.metrics.repeated_read_file_count == 1
    assert json.loads(bundle.provider_context)["context_metrics"]["repeated_read_file_count"] == 1
```

- [ ] **Step 2: Run context tests and verify they fail because modules do not exist**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py -q
```

Expected: import failure for `app.context`.

- [ ] **Step 3: Add context models**

Create `app/context/models.py`:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


ContextItemKind = Literal[
    "user_message",
    "memory",
    "observation",
    "file_summary",
    "session_summary",
    "skill_hint",
]


class ContextItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ContextItemKind
    content: str
    source: str
    priority: int = Field(default=0)
    estimated_chars: int = Field(default=0, ge=0)
    metadata: dict[str, object] = Field(default_factory=dict)


class ContextBudget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_items: int = Field(default=24, ge=1)
    max_chars: int = Field(default=16000, ge=1000)
    max_memory_items: int = Field(default=5, ge=0)
    max_observation_chars: int = Field(default=8000, ge=0)
    max_file_summary_chars: int = Field(default=4000, ge=0)


class ContextMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_chars: int = Field(default=0, ge=0)
    memory_recall_hits: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    read_file_count: int = Field(default=0, ge=0)
    repeated_read_file_count: int = Field(default=0, ge=0)
    compacted_item_count: int = Field(default=0, ge=0)


class ContextWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    message: str


class ContextBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_context: str
    memory_hits: list[dict[str, object]] = Field(default_factory=list)
    compacted_items: list[ContextItem] = Field(default_factory=list)
    metrics: ContextMetrics = Field(default_factory=ContextMetrics)
    warnings: list[ContextWarning] = Field(default_factory=list)
```

Create `app/context/__init__.py`:

```python
from app.context.manager import ContextManager
from app.context.models import (
    ContextBudget,
    ContextBundle,
    ContextItem,
    ContextMetrics,
    ContextWarning,
)

__all__ = [
    "ContextBudget",
    "ContextBundle",
    "ContextItem",
    "ContextManager",
    "ContextMetrics",
    "ContextWarning",
]
```

- [ ] **Step 4: Add context metric helpers**

Create `app/context/metrics.py`:

```python
from app.agent.provider import AgentObservationRecord
from app.context.models import ContextMetrics


def metrics_for_observations(records: list[AgentObservationRecord]) -> ContextMetrics:
    read_paths: list[str] = []
    for record in records:
        tool_name = _tool_name(record)
        if tool_name != "read_file":
            continue
        path = _read_file_path(record)
        if path is not None:
            read_paths.append(path)
    return ContextMetrics(
        observation_count=len(records),
        read_file_count=len(read_paths),
        repeated_read_file_count=len(read_paths) - len(set(read_paths)),
    )


def merge_context_metrics(
    *,
    base: ContextMetrics,
    observation_metrics: ContextMetrics,
    context_chars: int,
    memory_recall_hits: int,
    compacted_item_count: int,
) -> ContextMetrics:
    return base.model_copy(
        update={
            "context_chars": context_chars,
            "memory_recall_hits": memory_recall_hits,
            "observation_count": observation_metrics.observation_count,
            "read_file_count": observation_metrics.read_file_count,
            "repeated_read_file_count": observation_metrics.repeated_read_file_count,
            "compacted_item_count": compacted_item_count,
        }
    )


def _tool_name(record: AgentObservationRecord) -> str | None:
    if record.tool_invocation is not None:
        return record.tool_invocation.name
    if record.action is not None:
        return getattr(record.action, "action", None)
    return None


def _read_file_path(record: AgentObservationRecord) -> str | None:
    payload = record.observation.payload
    for key in ("relative_path", "path", "file_path"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    if record.tool_invocation is not None:
        value = record.tool_invocation.args.get("path")
        if isinstance(value, str):
            return value
    if record.action is not None:
        args = getattr(record.action, "args", {})
        if isinstance(args, dict):
            value = args.get("path") or args.get("relative_path")
            if isinstance(value, str):
                return value
    return None
```

- [ ] **Step 5: Add ContextManager**

Create `app/context/manager.py`:

```python
import json
from pathlib import Path

from app.agent.provider import AgentObservationRecord
from app.context.metrics import merge_context_metrics, metrics_for_observations
from app.context.models import ContextBudget, ContextBundle, ContextMetrics, ContextWarning
from app.memory.runtime import MemoryRuntime


class ContextManager:
    def __init__(
        self,
        *,
        memory_runtime: MemoryRuntime,
        base_context: str | None = None,
        budget: ContextBudget | None = None,
    ) -> None:
        self.memory_runtime = memory_runtime
        self.base_context = base_context
        self.budget = budget or ContextBudget()
        self._user_message = ""
        self._repo_path: Path | None = None
        self._memory_hits: list[dict[str, object]] = []
        self._observations: list[AgentObservationRecord] = []
        self._warnings: list[ContextWarning] = []
        self._latest_bundle = ContextBundle(provider_context="{}")

    @property
    def metrics(self) -> ContextMetrics:
        return self._latest_bundle.metrics

    @property
    def warnings(self) -> list[ContextWarning]:
        return list(self._warnings)

    def begin_turn(self, *, user_message: str, repo_path: Path) -> ContextBundle:
        self._user_message = user_message
        self._repo_path = repo_path
        self._observations = []
        self._warnings = []
        try:
            recall = self.memory_runtime.recall_for_turn(
                user_message=user_message,
                repo_state={"repo_path": str(repo_path)},
                max_items=self.budget.max_memory_items,
            )
            self._memory_hits = [hit.model_dump(mode="json") for hit in recall.hits]
        except Exception as exc:
            self._memory_hits = []
            self._warnings.append(
                ContextWarning(source="memory_recall", message=str(exc))
            )
        return self.build_provider_context()

    def record_observation(self, record: AgentObservationRecord) -> None:
        self._observations.append(record)
        self._latest_bundle = self.build_provider_context()

    def build_provider_context(self) -> ContextBundle:
        payload = self._payload()
        provider_context = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        observation_metrics = metrics_for_observations(self._observations)
        metrics = merge_context_metrics(
            base=ContextMetrics(),
            observation_metrics=observation_metrics,
            context_chars=len(provider_context),
            memory_recall_hits=len(self._memory_hits),
            compacted_item_count=0,
        )
        payload["context_metrics"] = metrics.model_dump(mode="json")
        provider_context = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        metrics = metrics.model_copy(update={"context_chars": len(provider_context)})
        self._latest_bundle = ContextBundle(
            provider_context=provider_context,
            memory_hits=self._memory_hits,
            compacted_items=[],
            metrics=metrics,
            warnings=self._warnings,
        )
        return self._latest_bundle

    def _payload(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.base_context:
            try:
                payload["base_context"] = json.loads(self.base_context)
            except json.JSONDecodeError:
                payload["base_context"] = self.base_context
        payload["memory_recall"] = self._memory_hits
        if self._warnings:
            payload["context_warnings"] = [
                warning.model_dump(mode="json") for warning in self._warnings
            ]
        return payload
```

- [ ] **Step 6: Run context tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py -q
```

Expected: PASS.

Commit:

```bash
git add app/context tests/unit/test_context_manager.py
git commit -m "add context runtime manager"
```

---

## Task 2: MemoryRuntime and Review Queue

**Files:**

- Create: `app/memory/recall.py`
- Create: `app/memory/review_queue.py`
- Create: `app/memory/runtime.py`
- Modify: `app/memory/__init__.py`
- Test: `tests/unit/test_memory_runtime.py`

- [ ] **Step 1: Write failing tests for recall and review queue**

Create `tests/unit/test_memory_runtime.py`:

```python
from pathlib import Path

from app.evolution.models import LessonCandidate
from app.memory.models import MemoryRecord
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def _runtime(tmp_path: Path) -> MemoryRuntime:
    return MemoryRuntime(MemoryStore(tmp_path / "memory"))


def test_memory_runtime_recalls_compact_hits(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.store.append(
        MemoryRecord(
            kind="project_fact",
            title="pytest command",
            content="Use python -m pytest -q for checks.",
            source="test",
            tags=["pytest"],
        )
    )

    result = runtime.recall_for_turn(
        user_message="pytest 怎么运行",
        repo_state={"repo_path": str(tmp_path)},
        max_items=2,
    )

    assert result.total_matches == 1
    assert result.hits[0].title == "pytest command"
    assert result.hits[0].content_excerpt == "Use python -m pytest -q for checks."
    assert result.returned_chars > 0


def test_memory_runtime_review_queue_append_list_accept_reject(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="Use read_file tail_lines for final-line questions.",
        evidence={"tool": "read_file", "path": "README.md"},
        source_trace_path="trace.jsonl",
        suggested_memory_kind="failure_lesson",
        confidence=0.8,
    )

    enqueued = runtime.enqueue_candidate(candidate)
    listed = runtime.list_candidates()

    assert enqueued.candidate_id == candidate.id
    assert listed[0].summary == candidate.summary

    accepted = runtime.accept_candidate(candidate.id)
    assert accepted.kind == "failure_lesson"
    assert accepted.title == candidate.summary
    assert runtime.list_candidates()[0].status == "accepted"

    second = LessonCandidate(
        kind="tool_policy_lesson",
        summary="Rejected tool calls should be reviewed.",
        evidence={"status": "rejected"},
        source_trace_path="trace.jsonl",
        suggested_memory_kind="trace_insight",
        confidence=0.7,
    )
    runtime.enqueue_candidate(second)
    runtime.reject_candidate(second.id)

    statuses = {candidate.id: candidate.status for candidate in runtime.list_candidates()}
    assert statuses[second.id] == "rejected"
```

- [ ] **Step 2: Run memory runtime tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_memory_runtime.py -q
```

Expected: import failure for `app.memory.runtime` or `app.evolution.models`.

- [ ] **Step 3: Add recall models**

Create `app/memory/recall.py`:

```python
from pydantic import BaseModel, ConfigDict, Field

from app.memory.models import MemoryKind


class MemoryRecallHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MemoryKind
    title: str
    content_excerpt: str
    tags: list[str] = Field(default_factory=list)
    score: int = Field(ge=0)
    source: str


class MemoryRecallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    kinds: list[MemoryKind] = Field(default_factory=list)
    hits: list[MemoryRecallHit] = Field(default_factory=list)
    total_matches: int = Field(default=0, ge=0)
    returned_chars: int = Field(default=0, ge=0)
    truncated: bool = False
```

- [ ] **Step 4: Add provisional evolution candidate model needed by review queue**

Create `app/evolution/models.py` with only model definitions required by this task:

```python
from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.memory.models import MemoryKind

LessonCandidateKind = Literal[
    "failure_lesson",
    "tool_policy_lesson",
    "context_lesson",
    "test_fix_lesson",
]
LessonCandidateStatus = Literal["pending", "accepted", "rejected"]


class LessonCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: LessonCandidateKind
    summary: str = Field(min_length=1, max_length=240)
    evidence: dict[str, object] = Field(default_factory=dict)
    source_trace_path: str | None = None
    suggested_memory_kind: MemoryKind = "failure_lesson"
    suggested_skill: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: LessonCandidateStatus = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class EvolutionTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    final_response: str | None = None
    turn_status: str
    tool_steps: list[dict[str, object]] = Field(default_factory=list)
    trace_path: str | None = None
    verification_results: list[dict[str, object]] = Field(default_factory=list)
    context_metrics: dict[str, object] = Field(default_factory=dict)


class EvolutionTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_candidates: list[LessonCandidate] = Field(default_factory=list)
    skipped_reason: str | None = None
    signals: list[str] = Field(default_factory=list)
```

Create `app/evolution/__init__.py`:

```python
from app.evolution.models import EvolutionTurnInput, EvolutionTurnResult, LessonCandidate

__all__ = ["EvolutionTurnInput", "EvolutionTurnResult", "LessonCandidate"]
```

- [ ] **Step 5: Add review queue persistence**

Create `app/memory/review_queue.py`:

```python
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from app.evolution.models import LessonCandidate, LessonCandidateStatus


class MemoryReviewQueue:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "review_queue.jsonl"

    def append(self, candidate: LessonCandidate) -> LessonCandidate:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(candidate.model_dump_json())
            handle.write("\n")
        return candidate

    def list_candidates(self) -> list[LessonCandidate]:
        if not self.path.exists():
            return []
        candidates: list[LessonCandidate] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                candidates.append(LessonCandidate.model_validate_json(line))
            except ValidationError:
                continue
        return candidates

    def update_status(
        self,
        candidate_id: str,
        status: LessonCandidateStatus,
    ) -> LessonCandidate:
        updated: LessonCandidate | None = None
        lines: list[str] = []
        for candidate in self.list_candidates():
            if candidate.id == candidate_id:
                candidate = candidate.model_copy(
                    update={
                        "status": status,
                        "updated_at": datetime.now().astimezone(),
                    }
                )
                updated = candidate
            lines.append(candidate.model_dump_json())
        if updated is None:
            raise KeyError(f"unknown lesson candidate: {candidate_id}")
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return updated
```

- [ ] **Step 6: Add MemoryRuntime**

Create `app/memory/runtime.py`:

```python
from app.evolution.models import LessonCandidate
from app.memory.file_summary import build_file_summary
from app.memory.models import FileSummary, MemoryKind, MemoryRecord
from app.memory.recall import MemoryRecallHit, MemoryRecallResult
from app.memory.review_queue import MemoryReviewQueue
from app.memory.store import MemoryStore


class ReviewQueueResult:
    def __init__(self, candidate_id: str, status: str) -> None:
        self.candidate_id = candidate_id
        self.status = status


class MemoryRuntime:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.review_queue = MemoryReviewQueue(store.root)

    def recall_for_turn(
        self,
        *,
        user_message: str,
        repo_state: dict[str, object],
        max_items: int = 5,
    ) -> MemoryRecallResult:
        del repo_state
        kinds: set[MemoryKind] = {"project_fact", "task_state", "failure_lesson", "trace_insight"}
        results = self.store.search(query=user_message, kinds=kinds, limit=max_items)
        hits = [
            MemoryRecallHit(
                id=result.record.id,
                kind=result.record.kind,
                title=result.record.title,
                content_excerpt=result.record.content[:1200],
                tags=result.record.tags,
                score=result.score,
                source=result.record.source,
            )
            for result in results
        ]
        returned_chars = sum(len(hit.content_excerpt) + len(hit.title) for hit in hits)
        return MemoryRecallResult(
            query=user_message,
            kinds=sorted(kinds),
            hits=hits,
            total_matches=len(hits),
            returned_chars=returned_chars,
            truncated=len(results) >= max_items,
        )

    def get_file_summary(self, repo_path, path: str) -> FileSummary:
        return build_file_summary(repo_path, path)

    def enqueue_candidate(self, candidate: LessonCandidate) -> ReviewQueueResult:
        written = self.review_queue.append(candidate)
        return ReviewQueueResult(candidate_id=written.id, status=written.status)

    def list_candidates(self) -> list[LessonCandidate]:
        return self.review_queue.list_candidates()

    def accept_candidate(self, candidate_id: str) -> MemoryRecord:
        candidate = self.review_queue.update_status(candidate_id, "accepted")
        record = MemoryRecord(
            kind=candidate.suggested_memory_kind,
            title=candidate.summary,
            content=_candidate_content(candidate),
            source=f"lesson_candidate:{candidate.id}",
            tags=["lesson", candidate.kind],
            metadata={
                "candidate_id": candidate.id,
                "candidate_kind": candidate.kind,
                "source_trace_path": candidate.source_trace_path,
                "confidence": candidate.confidence,
                "evidence": candidate.evidence,
            },
        )
        return self.store.append(record)

    def reject_candidate(self, candidate_id: str) -> ReviewQueueResult:
        candidate = self.review_queue.update_status(candidate_id, "rejected")
        return ReviewQueueResult(candidate_id=candidate.id, status=candidate.status)


def _candidate_content(candidate: LessonCandidate) -> str:
    lines = [candidate.summary]
    if candidate.source_trace_path:
        lines.append(f"Trace: {candidate.source_trace_path}")
    if candidate.evidence:
        lines.append(f"Evidence: {candidate.evidence}")
    return "\n".join(lines)
```

Modify `app/memory/__init__.py` to export runtime objects if the file is currently empty:

```python
from app.memory.runtime import MemoryRuntime

__all__ = ["MemoryRuntime"]
```

- [ ] **Step 7: Run memory tests and context regression**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_memory_runtime.py tests/unit/test_context_manager.py -q
```

Expected: PASS.

Commit:

```bash
git add app/memory app/evolution tests/unit/test_memory_runtime.py
git commit -m "add memory runtime review queue"
```

---

## Task 3: EvolutionRuntime and Lesson Builder

**Files:**

- Create: `app/evolution/lesson_builder.py`
- Create: `app/evolution/runtime.py`
- Modify: `app/evolution/__init__.py`
- Test: `tests/unit/test_evolution_runtime.py`

- [ ] **Step 1: Write failing tests for evolution signals**

Create `tests/unit/test_evolution_runtime.py`:

```python
from app.evolution.models import EvolutionTurnInput
from app.evolution.runtime import EvolutionRuntime
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def test_evolution_runtime_generates_failure_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="修复测试",
            turn_status="failed",
            final_response="Provider failed",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={},
        )
    )

    assert result.signals == ["turn_failed"]
    assert result.generated_candidates[0].kind == "failure_lesson"
    assert memory_runtime.list_candidates()[0].summary.startswith("Turn failed")


def test_evolution_runtime_generates_rejected_tool_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="查看状态",
            turn_status="failed",
            final_response="tool rejected",
            trace_path="trace.jsonl",
            tool_steps=[
                {
                    "index": 1,
                    "action": {"type": "tool_call", "action": "apply_patch"},
                    "observation": {
                        "status": "rejected",
                        "summary": "tool is not allowed",
                        "error_message": "tool is not allowed in this turn",
                    },
                }
            ],
            context_metrics={},
        )
    )

    assert "tool_rejected" in result.signals
    assert result.generated_candidates[0].kind == "tool_policy_lesson"


def test_evolution_runtime_generates_repeated_read_candidate(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="读文件",
            turn_status="completed",
            final_response="done",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={"repeated_read_file_count": 2, "read_file_count": 4},
        )
    )

    assert "repeated_read_file" in result.signals
    assert result.generated_candidates[0].kind == "context_lesson"


def test_evolution_runtime_skips_ordinary_success(tmp_path) -> None:
    memory_runtime = MemoryRuntime(MemoryStore(tmp_path / "memory"))
    runtime = EvolutionRuntime(memory_runtime)

    result = runtime.after_turn(
        EvolutionTurnInput(
            user_message="列目录",
            turn_status="completed",
            final_response="done",
            trace_path="trace.jsonl",
            tool_steps=[],
            context_metrics={"repeated_read_file_count": 0},
        )
    )

    assert result.generated_candidates == []
    assert result.skipped_reason == "no evolution signals"
    assert memory_runtime.list_candidates() == []
```

- [ ] **Step 2: Run evolution tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_runtime.py -q
```

Expected: import failure for `app.evolution.runtime`.

- [ ] **Step 3: Add deterministic lesson builder**

Create `app/evolution/lesson_builder.py`:

```python
from app.evolution.models import EvolutionTurnInput, LessonCandidate


def build_lesson_candidates(turn: EvolutionTurnInput) -> tuple[list[str], list[LessonCandidate]]:
    signals: list[str] = []
    candidates: list[LessonCandidate] = []

    if turn.turn_status != "completed":
        signals.append("turn_failed")
        candidates.append(
            LessonCandidate(
                kind="failure_lesson",
                summary=f"Turn failed while handling: {turn.user_message[:120]}",
                evidence={
                    "turn_status": turn.turn_status,
                    "final_response": turn.final_response,
                },
                source_trace_path=turn.trace_path,
                suggested_memory_kind="failure_lesson",
                confidence=0.6,
            )
        )

    rejected_steps = [_step for _step in turn.tool_steps if _observation_status(_step) == "rejected"]
    if rejected_steps:
        signals.append("tool_rejected")
        candidates.append(
            LessonCandidate(
                kind="tool_policy_lesson",
                summary="A tool call was rejected during the turn.",
                evidence={"rejected_steps": rejected_steps[:3]},
                source_trace_path=turn.trace_path,
                suggested_memory_kind="trace_insight",
                confidence=0.7,
            )
        )

    repeated_reads = _int_metric(turn.context_metrics, "repeated_read_file_count")
    if repeated_reads > 0:
        signals.append("repeated_read_file")
        candidates.append(
            LessonCandidate(
                kind="context_lesson",
                summary="The turn repeated read_file calls for the same path.",
                evidence={
                    "repeated_read_file_count": repeated_reads,
                    "read_file_count": _int_metric(turn.context_metrics, "read_file_count"),
                },
                source_trace_path=turn.trace_path,
                suggested_memory_kind="failure_lesson",
                confidence=0.65,
            )
        )

    if _verification_failed_then_passed(turn.tool_steps):
        signals.append("verification_recovered")
        candidates.append(
            LessonCandidate(
                kind="test_fix_lesson",
                summary="A verification failure was followed by a later successful verification.",
                evidence={"verification_steps": _verification_steps(turn.tool_steps)},
                source_trace_path=turn.trace_path,
                suggested_memory_kind="failure_lesson",
                suggested_skill="test-fix",
                confidence=0.75,
            )
        )

    return signals, candidates


def _observation_status(step: dict[str, object]) -> str | None:
    observation = step.get("observation")
    if isinstance(observation, dict):
        status = observation.get("status")
        if isinstance(status, str):
            return status
    return None


def _int_metric(metrics: dict[str, object], key: str) -> int:
    value = metrics.get(key)
    return value if isinstance(value, int) else 0


def _verification_steps(steps: list[dict[str, object]]) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for step in steps:
        action = step.get("action")
        if not isinstance(action, dict) or action.get("action") != "run_command":
            continue
        observation = step.get("observation")
        if isinstance(observation, dict):
            results.append({"action": action, "observation": observation})
    return results


def _verification_failed_then_passed(steps: list[dict[str, object]]) -> bool:
    statuses: list[str] = []
    for step in _verification_steps(steps):
        observation = step["observation"]
        if isinstance(observation, dict):
            status = observation.get("status")
            if isinstance(status, str):
                statuses.append(status)
    return "failed" in statuses and statuses[-1:] == ["succeeded"]
```

- [ ] **Step 4: Add EvolutionRuntime**

Create `app/evolution/runtime.py`:

```python
from app.evolution.lesson_builder import build_lesson_candidates
from app.evolution.models import EvolutionTurnInput, EvolutionTurnResult
from app.memory.runtime import MemoryRuntime


class EvolutionRuntime:
    def __init__(self, memory_runtime: MemoryRuntime) -> None:
        self.memory_runtime = memory_runtime

    def after_turn(self, turn: EvolutionTurnInput) -> EvolutionTurnResult:
        signals, candidates = build_lesson_candidates(turn)
        if not candidates:
            return EvolutionTurnResult(
                generated_candidates=[],
                skipped_reason="no evolution signals",
                signals=signals,
            )
        written = []
        for candidate in candidates:
            self.memory_runtime.enqueue_candidate(candidate)
            written.append(candidate)
        return EvolutionTurnResult(
            generated_candidates=written,
            skipped_reason=None,
            signals=signals,
        )
```

Modify `app/evolution/__init__.py`:

```python
from app.evolution.models import EvolutionTurnInput, EvolutionTurnResult, LessonCandidate
from app.evolution.runtime import EvolutionRuntime

__all__ = [
    "EvolutionRuntime",
    "EvolutionTurnInput",
    "EvolutionTurnResult",
    "LessonCandidate",
]
```

- [ ] **Step 5: Run evolution and memory tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_runtime.py tests/unit/test_memory_runtime.py -q
```

Expected: PASS.

Commit:

```bash
git add app/evolution tests/unit/test_evolution_runtime.py
git commit -m "add evolution runtime lesson candidates"
```

---

## Task 4: Wire Framework Into AgentLoop Main Path

**Files:**

- Modify: `app/agent/loop.py`
- Modify: `app/runtime/turn.py`
- Modify: `app/runtime/agent_loop.py`
- Modify: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: Write failing AgentLoop integration tests**

Append to `tests/unit/test_agent_loop.py`:

```python
def test_agent_loop_result_includes_context_summary_from_context_manager(tmp_path: Path) -> None:
    settings = settings_for(tmp_path)
    MemoryStore(settings.data_dir / "memory").append(
        MemoryRecord(
            kind="project_fact",
            title="pytest command",
            content="Use python -m pytest -q.",
            source="test",
            tags=["pytest"],
        )
    )
    provider = NativeToolProvider(
        [
            {"type": "final_response", "status": "completed", "summary": "done"},
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="之前记录的 pytest 命令是什么",
            provider=provider,
        ),
        settings,
    )

    assert result.status == "completed"
    assert result.context_summary is not None
    assert result.context_summary["metrics"]["memory_recall_hits"] == 1
    assert "pytest command" in provider.calls[0].context


def test_agent_loop_generates_evolution_candidate_for_repeated_read_file(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="repeat read",
            provider=RepeatingReadProvider(),
            allowed_tools={"read_file"},
            step_budget=5,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    candidates_path = tmp_path / "data" / "memory" / "review_queue.jsonl"
    assert result.evolution_summary is not None
    assert "repeated_read_file" in result.evolution_summary["signals"]
    assert candidates_path.exists()
    assert "repeated read_file" in candidates_path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run integration tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py::test_agent_loop_result_includes_context_summary_from_context_manager tests/unit/test_agent_loop.py::test_agent_loop_generates_evolution_candidate_for_repeated_read_file -q
```

Expected: failure because `AgentLoopResult` has no `context_summary` or `evolution_summary`.

- [ ] **Step 3: Add summary fields to result models**

Modify `app/agent/loop.py` `AgentLoopResult`:

```python
class AgentLoopResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: AgentLoopStatus
    summary: str
    trace_path: str | None
    workspace_path: str | None = None
    steps: list[AgentStep] = Field(default_factory=list)
    context_summary: dict[str, object] | None = None
    evolution_summary: dict[str, object] | None = None
```

Modify `app/runtime/turn.py` `RuntimeTurnResult`:

```python
class RuntimeTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: RuntimeStatus
    summary: str
    trace_path: str | None
    workspace_path: str | None = None
    steps: list[RuntimeToolStep] = Field(default_factory=list)
    context_summary: dict[str, object] | None = None
    evolution_summary: dict[str, object] | None = None
```

- [ ] **Step 4: Replace AgentLoop direct memory recall with ContextManager**

Modify imports at the top of `app/runtime/agent_loop.py`:

```python
import json
import subprocess
from uuid import uuid4

from app.context.manager import ContextManager
from app.evolution.models import EvolutionTurnInput
from app.evolution.runtime import EvolutionRuntime
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
```

Keep `json` only if still used elsewhere after deleting `_runtime_context_payload`.

Replace:

```python
memory_store = MemoryStore(settings.data_dir / "memory")

def provider_context() -> str:
    return json.dumps(
        _runtime_context_payload(
            base_context=loop_input.provider_context,
            problem_statement=loop_input.problem_statement,
            memory_store=memory_store,
        ),
        ensure_ascii=False,
        sort_keys=True,
    )
```

with:

```python
memory_store = MemoryStore(settings.data_dir / "memory")
memory_runtime = MemoryRuntime(memory_store)
context_manager = ContextManager(
    memory_runtime=memory_runtime,
    base_context=loop_input.provider_context,
)
context_manager.begin_turn(
    user_message=loop_input.problem_statement,
    repo_path=workspace_path,
)
evolution_runtime = EvolutionRuntime(memory_runtime)

def provider_context() -> str:
    return context_manager.build_provider_context().provider_context
```

In `record_handled_action`, after appending `observation_history`, add:

```python
        context_manager.record_observation(observation_history[-1])
```

At the end of `run_agent_loop_turn`, before recording `agent.run.completed`, build evolution input:

```python
    context_bundle = context_manager.build_provider_context()
    evolution_result = evolution_runtime.after_turn(
        EvolutionTurnInput(
            user_message=loop_input.problem_statement,
            final_response=summary,
            turn_status=status,
            tool_steps=[step.model_dump(mode="json") for step in steps],
            trace_path=str(trace_path),
            verification_results=[],
            context_metrics=context_bundle.metrics.model_dump(mode="json"),
        )
    )
    context_summary = {
        "metrics": context_bundle.metrics.model_dump(mode="json"),
        "memory_recall_hits": len(context_bundle.memory_hits),
        "warnings": [warning.model_dump(mode="json") for warning in context_bundle.warnings],
    }
    evolution_summary = {
        "generated_candidate_count": len(evolution_result.generated_candidates),
        "signals": evolution_result.signals,
        "skipped_reason": evolution_result.skipped_reason,
    }
```

Then change the completed trace payload:

```python
            payload={
                "status": status,
                "summary": summary,
                "step_count": len(steps),
                "context_summary": context_summary,
                "evolution_summary": evolution_summary,
            },
```

And return:

```python
    return AgentLoopResult(
        run_id=run_id,
        status=status,
        summary=summary,
        trace_path=str(trace_path),
        workspace_path=str(workspace_path),
        steps=steps,
        context_summary=context_summary,
        evolution_summary=evolution_summary,
    )
```

Delete `_runtime_context_payload()` from `app/runtime/agent_loop.py` once no tests import it. If `json` becomes unused, remove the import.

- [ ] **Step 5: Preserve pre-start workspace failure behavior**

In the early `prepare_worktree` failure return, include empty summaries so result shape is stable:

```python
                context_summary=None,
                evolution_summary=None,
```

Expected: existing tests still accept the result because the new fields are optional.

- [ ] **Step 6: Run targeted AgentLoop tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py::test_agent_loop_injects_memory_recall_context_before_first_tool_call tests/unit/test_agent_loop.py::test_agent_loop_result_includes_context_summary_from_context_manager tests/unit/test_agent_loop.py::test_agent_loop_generates_evolution_candidate_for_repeated_read_file -q
```

Expected: PASS.

- [ ] **Step 7: Run framework unit tests and commit**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py tests/unit/test_memory_runtime.py tests/unit/test_evolution_runtime.py tests/unit/test_agent_loop.py -q
```

Expected: PASS.

Commit:

```bash
git add app/agent/loop.py app/runtime/turn.py app/runtime/agent_loop.py tests/unit/test_agent_loop.py
git commit -m "wire capability framework into agent loop"
```

---

## Task 5: Scenario Assertion, Docs, and Full Verification

**Files:**

- Modify: `tests/scenarios/test_tui_repository_inspection_scenarios.py` or another existing scenario file that already checks memory recall.
- Modify: `MendCode_开发方案.md`
- Optional modify: `MendCode_问题记录.md`

- [ ] **Step 1: Inspect existing scenario helper before editing**

Run:

```bash
sed -n '1,260p' tests/scenarios/test_tui_repository_inspection_scenarios.py
sed -n '1,260p' tests/scenarios/tui_scenario_runner.py
```

Expected: identify where conversation compact payload or turn result can assert context summary without showing trace paths to the user.

- [ ] **Step 2: Add one scenario-level assertion for context/evolution evidence**

If `test_memory_recall_question_uses_memory_search` already exists, extend it to assert a compact context metric appears in stored events. Use this pattern and adapt only the local variable names to the existing helper output:

```python
assert any(
    event.get("type") == "turn_result"
    and isinstance(event.get("payload"), dict)
    and (
        event["payload"].get("context_summary")
        or event["payload"].get("context_metrics")
    )
    for event in result.events
)
```

If the scenario runner does not expose events, add the assertion to the closest unit test for conversation log summarization instead:

```python
assert compact["context_summary"]["metrics"]["memory_recall_hits"] >= 0
```

Do not expose `trace_path` in the visible TUI chat transcript.

- [ ] **Step 3: Run the touched scenario test**

Run the exact test file touched in Step 2:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/scenarios/test_tui_repository_inspection_scenarios.py -q
```

Expected: PASS.

- [ ] **Step 4: Update development docs**

Edit `MendCode_开发方案.md`:

- In `3.1 AgentLoop`, mark that AgentLoop now routes runtime context through `ContextManager`.
- In `3.7 Layered Memory`, mark `MemoryRuntime` and review queue as completed first framework pieces.
- Add a new short subsection under current capability state for `Context / Evolution Runtime`:

```markdown
### 3.x Context / Evolution Runtime

已完成：

- [x] `ContextManager` 统一构建 provider context，并记录 memory recall、observation、read_file 和重复 read_file 指标。
- [x] `MemoryRuntime` 包装 `MemoryStore`，提供自动 recall 和 review queue 入口。
- [x] `EvolutionRuntime` 在 turn 结束后根据失败、rejected tool 和重复读取生成 lesson candidate。

当前不足：

- [ ] Context budget 仍以字符估算为主，尚未接入真实 tokenizer。
- [ ] review queue 还没有 TUI 审查入口。
- [ ] lesson candidate 不会自动更新 SKILL、prompt 或长期 memory。
```

Do not update README unless user-facing commands changed. Do not update global roadmap unless phase priorities changed.

- [ ] **Step 5: Run focused verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py tests/unit/test_memory_runtime.py tests/unit/test_evolution_runtime.py tests/unit/test_agent_loop.py tests/unit/test_prompt_context.py tests/unit/test_memory_tools.py tests/unit/test_trace_analyzer.py -q
```

Expected: PASS.

- [ ] **Step 6: Run lint**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/context app/memory app/evolution app/runtime/agent_loop.py app/agent/loop.py app/runtime/turn.py tests/unit/test_context_manager.py tests/unit/test_memory_runtime.py tests/unit/test_evolution_runtime.py tests/unit/test_agent_loop.py
```

Expected: PASS.

- [ ] **Step 7: Commit docs and scenario changes**

Commit:

```bash
git add tests/scenarios MendCode_开发方案.md MendCode_问题记录.md
git commit -m "document capability framework integration"
```

If `MendCode_问题记录.md` was not changed, omit it from `git add`.

- [ ] **Step 8: Final non-e2e regression before merge**

Run on the feature branch:

```bash
env -u MENDCODE_PROVIDER -u MENDCODE_MODEL -u MENDCODE_BASE_URL -u MENDCODE_API_KEY PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: both PASS.

Only run `tests/e2e/test_tui_pty_live.py` when a real OpenAI-compatible provider is configured:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected with provider env: PASS. Expected without provider env: fail clearly with missing environment variables; do not treat missing provider env as code failure.

Commit any fixes found by verification before merging.

---

## Self-Review Checklist

- Spec coverage:
  - `ContextManager` main-path provider context ownership is covered by Tasks 1 and 4.
  - `MemoryRuntime` recall and review queue are covered by Task 2.
  - `EvolutionRuntime.after_turn()` and candidate writing are covered by Tasks 3 and 4.
  - Context metrics are covered by Tasks 1 and 4.
  - Conservative long-term memory writes are covered by Task 2 because candidates enter review queue and `accept_candidate()` is explicit.
  - Documentation updates are covered by Task 5.

- Type consistency:
  - `ContextManager.begin_turn()` returns `ContextBundle`.
  - `MemoryRuntime.recall_for_turn()` returns `MemoryRecallResult`.
  - `EvolutionRuntime.after_turn()` accepts `EvolutionTurnInput` and returns `EvolutionTurnResult`.
  - `AgentLoopResult.context_summary` and `evolution_summary` are plain dictionaries to avoid forcing downstream models to import new context/evolution types.

- Scope control:
  - This plan does not implement SKILL.md execution.
  - This plan does not add TUI review UI.
  - This plan does not claim benchmark metrics.
  - This plan preserves the existing provider `context: str | None` contract.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-29-context-memory-evolution-runtime-framework.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
