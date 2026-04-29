# Context Compaction v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ContextManager` actively control provider context size by compacting observations, bounding memory recall, tracking compaction metrics, and using file summaries for repeated or large file reads.

**Architecture:** Keep AgentLoop orchestration unchanged and move compaction policy into `app/context`. `ContextManager` will own compact runtime context construction; `app.agent.prompt_context` will continue to format OpenAI messages but will consume already-compact runtime context. `MemoryRuntime` remains the file-summary access point.

**Tech Stack:** Python 3.12, Pydantic v2, pytest, existing `ContextManager`, `MemoryRuntime`, `AgentObservationRecord`, `FileSummary`, JSON provider context, Textual scenario tests.

---

## File Structure

Create:

- `app/context/compaction.py`: pure compaction helpers for observations, memory hits, text excerpts, and file-summary references.

Modify:

- `app/context/models.py`: expand `ContextBudget`, `ContextMetrics`, `ContextItemKind`, and `ContextItem` for compaction.
- `app/context/metrics.py`: keep read-file repetition metrics and add compaction delta helpers if needed.
- `app/context/manager.py`: build compact provider context with observation summaries, memory recall budget, file-summary references, and compaction metrics.
- `app/memory/runtime.py`: expose file summary access if additional metadata is needed; avoid changing storage semantics.
- `app/runtime/agent_loop.py`: pass enough workspace context into `ContextManager`; only touch this if `ContextManager` needs `repo_path` after `begin_turn`.
- `app/tui/log_summarizer.py`: ensure new compaction fields remain compact in conversation logs if they appear in result summaries.
- `tests/unit/test_context_manager.py`: add compaction tests.
- `tests/unit/test_prompt_context.py`: assert provider messages do not re-expand compact runtime context.
- `tests/unit/test_memory_runtime.py` or `tests/unit/test_file_summary_cache.py`: add file-summary interaction tests only if `MemoryRuntime` behavior changes.
- `tests/scenarios/test_tui_file_question_scenarios.py` or `tests/scenarios/test_tui_repository_inspection_scenarios.py`: add one scenario-level no-large-dump assertion for compact context.
- `MendCode_开发方案.md`: record actual compaction capabilities and remaining gaps after implementation.

Do not modify provider adapters unless a failing test proves the existing `AgentProviderStepInput.context: str | None` contract cannot carry the compact context.

---

## Task 1: Expand Context Budget and Metrics

**Files:**

- Modify: `app/context/models.py`
- Modify: `tests/unit/test_context_manager.py`

- [ ] **Step 1: Write failing tests for budget and metric fields**

Append to `tests/unit/test_context_manager.py`:

```python
def test_context_budget_exposes_compaction_limits() -> None:
    budget = ContextBudget(
        max_memory_items=3,
        max_context_chars=5000,
        max_memory_chars=900,
        max_observation_chars=1200,
        max_file_summary_chars=800,
        max_observation_items=4,
    )

    assert budget.max_context_chars == 5000
    assert budget.max_memory_chars == 900
    assert budget.max_observation_chars == 1200
    assert budget.max_file_summary_chars == 800
    assert budget.max_observation_items == 4


def test_context_metrics_exposes_compaction_counters() -> None:
    metrics = ContextMetrics(
        context_chars=100,
        raw_context_chars=300,
        compacted_context_chars=100,
        compacted_item_count=2,
        file_summary_hit_count=1,
        observation_chars_saved=200,
    )

    assert metrics.raw_context_chars == 300
    assert metrics.compacted_context_chars == 100
    assert metrics.compacted_item_count == 2
    assert metrics.file_summary_hit_count == 1
    assert metrics.observation_chars_saved == 200
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py::test_context_budget_exposes_compaction_limits tests/unit/test_context_manager.py::test_context_metrics_exposes_compaction_counters -q
```

Expected: fail with validation errors for unknown fields.

- [ ] **Step 3: Extend strict context models**

Modify `app/context/models.py`:

```python
ContextItemKind = Literal[
    "base_context",
    "memory_recall",
    "context_warning",
    "context_metrics",
    "observation",
    "file_summary",
    "compaction_notice",
]


class ContextBudget(StrictContextModel):
    max_memory_items: int = Field(default=5, ge=0)
    max_context_chars: int = Field(default=16000, ge=1000)
    max_memory_chars: int = Field(default=4000, ge=0)
    max_observation_chars: int = Field(default=8000, ge=0)
    max_file_summary_chars: int = Field(default=3000, ge=0)
    max_observation_items: int = Field(default=12, ge=0)
    max_item_excerpt_chars: int = Field(default=1200, ge=100)


class ContextMetrics(StrictContextModel):
    context_chars: int = Field(default=0, ge=0)
    raw_context_chars: int = Field(default=0, ge=0)
    compacted_context_chars: int = Field(default=0, ge=0)
    memory_recall_hits: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    read_file_count: int = Field(default=0, ge=0)
    repeated_read_file_count: int = Field(default=0, ge=0)
    compacted_item_count: int = Field(default=0, ge=0)
    file_summary_hit_count: int = Field(default=0, ge=0)
    observation_chars_saved: int = Field(default=0, ge=0)
```

Keep `StrictContextModel` unchanged. Do not relax strict mode.

- [ ] **Step 4: Run model tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py::test_context_budget_exposes_compaction_limits tests/unit/test_context_manager.py::test_context_metrics_exposes_compaction_counters tests/unit/test_context_manager.py::test_context_models_reject_scalar_coercion -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/context/models.py tests/unit/test_context_manager.py
git commit -m "expand context compaction models"
```

---

## Task 2: Add Observation Compaction Helpers

**Files:**

- Create: `app/context/compaction.py`
- Modify: `tests/unit/test_context_manager.py`

- [ ] **Step 1: Write failing tests for compact observation payloads**

Append to `tests/unit/test_context_manager.py`:

```python
from app.context.compaction import compact_observation_record


def test_compact_observation_record_truncates_read_file_content() -> None:
    record = AgentObservationRecord(
        action=ToolCallAction(
            type="tool_call",
            action="read_file",
            reason="inspect",
            args={"path": "README.md"},
        ),
        tool_invocation=ToolInvocation(
            id="call_read",
            name="read_file",
            args={"path": "README.md"},
            source="openai_tool_call",
        ),
        observation=Observation(
            status="succeeded",
            summary="Read README.md",
            payload={
                "relative_path": "README.md",
                "content": "x" * 5000,
                "truncated": False,
            },
        ),
    )

    item = compact_observation_record(record, max_chars=300)

    assert item.kind == "observation"
    assert item.title == "read_file: succeeded"
    assert item.metadata["tool_name"] == "read_file"
    assert item.metadata["relative_path"] == "README.md"
    assert item.metadata["content_length"] == 5000
    assert item.metadata["content_truncated"] is True
    assert len(item.content) <= 320
    assert "x" * 1000 not in item.model_dump_json()


def test_compact_observation_record_samples_search_matches() -> None:
    matches = [
        {"relative_path": f"file_{index}.py", "line_number": index, "line": "def target(): pass"}
        for index in range(40)
    ]
    record = AgentObservationRecord(
        action=ToolCallAction(
            type="tool_call",
            action="rg",
            reason="search",
            args={"pattern": "target"},
        ),
        observation=Observation(
            status="succeeded",
            summary="Found matches",
            payload={"pattern": "target", "matches": matches, "total_matches": 40},
        ),
    )

    item = compact_observation_record(record, max_chars=500, max_collection_items=5)

    assert item.metadata["tool_name"] == "rg"
    assert item.metadata["matches_count"] == 40
    assert item.metadata["matches_truncated"] is True
    assert len(item.metadata["matches_sample"]) == 5
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py::test_compact_observation_record_truncates_read_file_content tests/unit/test_context_manager.py::test_compact_observation_record_samples_search_matches -q
```

Expected: import failure for `app.context.compaction`.

- [ ] **Step 3: Implement compaction helper**

Create `app/context/compaction.py`:

```python
from typing import Any

from app.agent.provider import AgentObservationRecord
from app.context.models import ContextItem


def compact_observation_record(
    record: AgentObservationRecord,
    *,
    max_chars: int,
    max_collection_items: int = 8,
) -> ContextItem:
    tool_name = _tool_name(record)
    metadata: dict[str, Any] = {
        "tool_name": tool_name,
        "status": record.observation.status,
    }
    payload = record.observation.payload
    content_parts = [record.observation.summary]
    if record.observation.error_message:
        content_parts.append(_excerpt(record.observation.error_message, max_chars=max_chars))

    for key in [
        "relative_path",
        "file_path",
        "path",
        "command",
        "pattern",
        "total_entries",
        "total_matches",
        "exit_code",
        "status",
        "truncated",
    ]:
        if key in payload:
            metadata[key] = payload[key]

    if isinstance(payload.get("content"), str):
        content = str(payload["content"])
        metadata["content_length"] = len(content)
        metadata["content_truncated"] = len(content) > max_chars
        content_parts.append(_excerpt(content, max_chars=max_chars))

    for key, sample_key in [("entries", "entries_sample"), ("matches", "matches_sample")]:
        values = payload.get(key)
        if isinstance(values, list):
            metadata[f"{key}_count"] = len(values)
            metadata[f"{key}_truncated"] = len(values) > max_collection_items
            metadata[sample_key] = [
                _compact_mapping(item, max_chars=240)
                for item in values[:max_collection_items]
                if isinstance(item, dict)
            ]

    text = "\\n".join(part for part in content_parts if part)
    return ContextItem(
        kind="observation",
        title=f"{tool_name or 'tool'}: {record.observation.status}",
        content=_excerpt(text, max_chars=max_chars),
        metadata=metadata,
    )


def compact_memory_hit(hit: object, *, max_chars: int) -> dict[str, object]:
    dump = hit.model_dump(mode="json", exclude_none=True)
    if isinstance(dump.get("content_excerpt"), str):
        dump["content_excerpt"] = _excerpt(str(dump["content_excerpt"]), max_chars=max_chars)
    return dump


def _tool_name(record: AgentObservationRecord) -> str | None:
    if record.tool_invocation is not None:
        return record.tool_invocation.name
    if record.action is not None:
        return getattr(record.action, "action", None)
    payload_tool = record.observation.payload.get("tool_name") or record.observation.payload.get("tool")
    return str(payload_tool) if isinstance(payload_tool, str) else None


def _compact_mapping(value: dict[str, object], *, max_chars: int) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str):
            compact[str(key)] = _excerpt(item, max_chars=max_chars)
        elif item is None or isinstance(item, bool | int | float):
            compact[str(key)] = item
        else:
            compact[str(key)] = _excerpt(str(item), max_chars=max_chars)
    return compact


def _excerpt(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"
```

- [ ] **Step 4: Run compaction tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py::test_compact_observation_record_truncates_read_file_content tests/unit/test_context_manager.py::test_compact_observation_record_samples_search_matches -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/context/compaction.py tests/unit/test_context_manager.py
git commit -m "add context observation compaction"
```

---

## Task 3: Wire Compaction Into ContextManager Provider Context

**Files:**

- Modify: `app/context/manager.py`
- Modify: `app/context/metrics.py`
- Modify: `tests/unit/test_context_manager.py`

- [ ] **Step 1: Write failing tests for provider context compaction**

Append to `tests/unit/test_context_manager.py`:

```python
def test_context_manager_provider_context_uses_compact_observation_items(tmp_path: Path) -> None:
    manager = ContextManager(
        memory_runtime=_memory_runtime(tmp_path),
        budget=ContextBudget(max_observation_chars=600, max_item_excerpt_chars=200),
    )
    manager.begin_turn(user_message="read large file", repo_path=tmp_path)
    manager.record_observation(
        AgentObservationRecord(
            action=ToolCallAction(
                type="tool_call",
                action="read_file",
                reason="inspect",
                args={"path": "README.md"},
            ),
            observation=Observation(
                status="succeeded",
                summary="Read README.md",
                payload={"relative_path": "README.md", "content": "x" * 5000},
            ),
        )
    )

    payload = json.loads(manager.build_provider_context().provider_context)

    assert "observations" in payload
    assert payload["observations"][0]["metadata"]["content_length"] == 5000
    assert "x" * 1000 not in json.dumps(payload, ensure_ascii=False)
    assert payload["context_metrics"]["compacted_item_count"] >= 1
    assert payload["context_metrics"]["observation_chars_saved"] > 0


def test_context_manager_limits_memory_recall_chars(tmp_path: Path) -> None:
    store = MemoryStore(tmp_path / "memory")
    store.append(
        MemoryRecord(
            kind="project_fact",
            title="long pytest note",
            content="pytest " + ("x" * 5000),
            source="test",
            tags=["pytest"],
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(store),
        budget=ContextBudget(max_memory_items=3, max_memory_chars=200),
    )

    payload = json.loads(
        manager.begin_turn(user_message="pytest", repo_path=tmp_path).provider_context
    )

    assert payload["memory_recall"][0]["title"] == "long pytest note"
    assert len(payload["memory_recall"][0]["content_excerpt"]) <= 220
    assert "x" * 1000 not in json.dumps(payload, ensure_ascii=False)
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py::test_context_manager_provider_context_uses_compact_observation_items tests/unit/test_context_manager.py::test_context_manager_limits_memory_recall_chars -q
```

Expected: fail because provider context does not include compact `observations` and memory is not budgeted.

- [ ] **Step 3: Update ContextManager to include compact observations and budgeted memory**

Modify `app/context/manager.py`:

- Import compaction helpers:

```python
from app.context.compaction import compact_memory_hit, compact_observation_record
```

- Store compact observation items in `_context_items()`:

```python
        observation_items = [
            compact_observation_record(
                observation,
                max_chars=self.budget.max_item_excerpt_chars,
            )
            for observation in self._observations[-self.budget.max_observation_items :]
        ]
        items.extend(observation_items)
```

- In `_provider_context_json()`, add compact observations and budgeted memory:

```python
        memory_recall = [
            compact_memory_hit(hit, max_chars=self.budget.max_memory_chars)
            for hit in self._memory_recall
        ]
        observation_items = [
            compact_observation_record(
                observation,
                max_chars=self.budget.max_item_excerpt_chars,
            )
            for observation in self._observations[-self.budget.max_observation_items :]
        ]
        payload = {
            "base_context": self._parsed_base_context(),
            "memory_recall": memory_recall,
            "observations": [
                item.model_dump(mode="json", exclude_none=True)
                for item in observation_items
            ],
            "context_metrics": metrics.model_dump(mode="json"),
        }
```

- Add private metric calculation:

```python
    def _raw_observation_chars(self) -> int:
        return sum(len(record.observation.model_dump_json()) for record in self._observations)

    def _compact_observation_chars(self) -> int:
        return sum(
            len(
                compact_observation_record(
                    observation,
                    max_chars=self.budget.max_item_excerpt_chars,
                ).model_dump_json()
            )
            for observation in self._observations[-self.budget.max_observation_items :]
        )
```

- In `build_provider_context()`, after `metrics = merge_context_metrics(...)`, update:

```python
        raw_observation_chars = self._raw_observation_chars()
        compact_observation_chars = self._compact_observation_chars()
        metrics.raw_context_chars = raw_observation_chars
        metrics.compacted_context_chars = compact_observation_chars
        metrics.compacted_item_count = sum(
            1
            for item in items
            if item.kind in {"observation", "memory_recall", "file_summary", "compaction_notice"}
        )
        metrics.observation_chars_saved = max(0, raw_observation_chars - compact_observation_chars)
```

Keep the current fixed-point `context_chars` calculation.

- [ ] **Step 4: Run context manager tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/context/manager.py app/context/metrics.py tests/unit/test_context_manager.py
git commit -m "wire compact observations into context manager"
```

---

## Task 4: Add File Summary References for Repeated Large Reads

**Files:**

- Modify: `app/context/manager.py`
- Modify: `tests/unit/test_context_manager.py`

- [ ] **Step 1: Write failing test for file-summary reference**

Append to `tests/unit/test_context_manager.py`:

```python
def test_context_manager_adds_file_summary_for_repeated_read_file(tmp_path: Path) -> None:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    (repo_path / "README.md").write_text(
        "MendCode\\n\\n" + "\\n".join(f"line {index}" for index in range(200)),
        encoding="utf-8",
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(tmp_path / "memory")),
        budget=ContextBudget(max_file_summary_chars=400),
    )
    manager.begin_turn(user_message="read repeatedly", repo_path=repo_path)

    for index in range(2):
        manager.record_observation(
            AgentObservationRecord(
                action=ToolCallAction(
                    type="tool_call",
                    action="read_file",
                    reason="inspect",
                    args={"path": "README.md"},
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Read README.md",
                    payload={
                        "relative_path": "README.md",
                        "content": "large content " * 500,
                    },
                ),
            )
        )

    payload = json.loads(manager.build_provider_context().provider_context)

    assert payload["context_metrics"]["file_summary_hit_count"] == 1
    summaries = [item for item in payload["file_summaries"] if item["metadata"]["path"] == "README.md"]
    assert summaries
    assert len(summaries[0]["content"]) <= 430
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py::test_context_manager_adds_file_summary_for_repeated_read_file -q
```

Expected: fail because `file_summaries` is not in provider context.

- [ ] **Step 3: Store repo path and add repeated-read summaries**

Modify `app/context/manager.py`:

- Add `self._repo_path: Path | None = None` in `__init__`.
- Set it in `begin_turn()`.
- Add helper:

```python
    def _repeated_read_paths(self) -> list[str]:
        seen: set[str] = set()
        repeated: list[str] = []
        for observation in self._observations:
            if not _is_read_file_observation_like(observation):
                continue
            path = _read_file_path_like(observation)
            if path is None:
                continue
            if path in seen and path not in repeated:
                repeated.append(path)
            seen.add(path)
        return repeated
```

Use local helpers or import safe public helpers from `app.context.metrics` if you expose them.

- Add:

```python
    def _file_summary_items(self) -> list[ContextItem]:
        if self._repo_path is None:
            return []
        items: list[ContextItem] = []
        for path in self._repeated_read_paths():
            try:
                summary = self.memory_runtime.get_file_summary(self._repo_path, path)
            except (OSError, ValueError):
                continue
            items.append(
                ContextItem(
                    kind="file_summary",
                    title=f"File summary: {summary.path}",
                    content=_excerpt(summary.summary, self.budget.max_file_summary_chars),
                    metadata={
                        "path": summary.path,
                        "content_sha256": summary.content_sha256,
                        "line_count": summary.line_count,
                        "size_bytes": summary.size_bytes,
                        "symbols": summary.symbols[:20],
                    },
                )
            )
        return items
```

- Add `file_summaries` to provider payload:

```python
        file_summary_items = self._file_summary_items()
        payload["file_summaries"] = [
            item.model_dump(mode="json", exclude_none=True)
            for item in file_summary_items
        ]
```

- Include file summary items in `items`.
- Set `metrics.file_summary_hit_count = len(file_summary_items)`.

- [ ] **Step 4: Run context manager tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/context/manager.py tests/unit/test_context_manager.py
git commit -m "add file summaries to compact context"
```

---

## Task 5: Align Prompt Context and Scenario Coverage

**Files:**

- Modify: `tests/unit/test_prompt_context.py`
- Modify: `tests/scenarios/test_tui_file_question_scenarios.py` or `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Modify: `MendCode_开发方案.md`

- [ ] **Step 1: Add prompt-context regression for compact runtime context**

Append to `tests/unit/test_prompt_context.py`:

```python
def test_provider_messages_preserve_compact_runtime_context_without_reexpanding_content() -> None:
    large_content = "x" * 5000
    compact_runtime_context = {
        "observations": [
            {
                "kind": "observation",
                "title": "read_file: succeeded",
                "content": "x" * 200 + "...[truncated]",
                "metadata": {
                    "tool_name": "read_file",
                    "relative_path": "README.md",
                    "content_length": len(large_content),
                    "content_truncated": True,
                },
            }
        ],
        "context_metrics": {
            "raw_context_chars": len(large_content),
            "compacted_context_chars": 300,
            "observation_chars_saved": 4700,
        },
    }

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="inspect",
            verification_commands=[],
            step_index=2,
            remaining_steps=4,
            observations=[],
            context=json.dumps(compact_runtime_context),
        ),
        limits=PromptContextLimits(max_text_chars=1000, max_observations=5),
    )

    content = messages[1].content

    assert "content_length" in content
    assert "observation_chars_saved" in content
    assert large_content not in content
```

- [ ] **Step 2: Run prompt-context test**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_prompt_context.py::test_provider_messages_preserve_compact_runtime_context_without_reexpanding_content -q
```

Expected: PASS or fail with a clear reason. If it fails because current `_sanitize_context_value()` expands compact content, fix `app/agent/prompt_context.py` by preserving compact metadata and still trimming strings through existing limits.

- [ ] **Step 3: Add scenario-level assertion for no large context dump**

In the scenario file that already covers file questions, add a compact assertion to an existing file-read case:

```python
assert_no_raw_trace_or_large_json_dump(transcript)
assert "content_length" in json.dumps(transcript.jsonl_records, ensure_ascii=False)
assert "x" * 1000 not in json.dumps(transcript.jsonl_records, ensure_ascii=False)
```

If the existing fake runner does not provide a large read-file payload, add a focused scenario with `ScenarioToolStep(action="read_file", payload={"relative_path": "README.md", "content": "x" * 5000})` and assert the compact conversation log stores `content_length` instead of full content.

- [ ] **Step 4: Update development docs**

Edit `MendCode_开发方案.md`:

- In `3.8 Context / Evolution Runtime`, add completed bullets:

```markdown
- [x] `ContextManager` 对 observation、memory recall 和 file summary 做第一版 compaction。
- [x] compact context 记录 raw / compacted 字符量、压缩 item 数、file summary 命中数和 observation 字符节省量。
```

- Update current gaps:

```markdown
- [ ] Context compaction 仍是启发式字符预算，尚未接入真实 tokenizer 和模型窗口。
- [ ] file summary 只覆盖重复读取场景，尚未形成 repo map 或跨轮缓存策略。
```

Do not update README unless user-facing commands change.

- [ ] **Step 5: Run scenario and prompt tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py tests/unit/test_prompt_context.py tests/scenarios/test_tui_file_question_scenarios.py tests/scenarios/test_tui_repository_inspection_scenarios.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/agent/prompt_context.py tests/unit/test_prompt_context.py tests/scenarios MendCode_开发方案.md
git commit -m "cover compact context in prompt and scenarios"
```

If `app/agent/prompt_context.py` did not change, omit it from `git add`.

---

## Task 6: Verification and Final Review

**Files:**

- No code files unless verification finds issues.

- [ ] **Step 1: Run focused context verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_manager.py tests/unit/test_prompt_context.py tests/unit/test_memory_runtime.py tests/unit/test_file_summary_cache.py tests/unit/test_agent_loop.py tests/unit/test_tui_log_summarizer.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full non-e2e regression**

Run:

```bash
env -u MENDCODE_PROVIDER -u MENDCODE_MODEL -u MENDCODE_BASE_URL -u MENDCODE_API_KEY PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
```

Expected: PASS.

- [ ] **Step 3: Run ruff**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: PASS.

- [ ] **Step 4: Optional live PTY check**

Only run this when OpenAI-compatible provider env is configured:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected with provider env: PASS. Without provider env: fail clearly with missing variables; record as not run, not as code failure.

- [ ] **Step 5: Final review checklist**

Review the implementation for:

- Provider context no longer includes full repeated `read_file` contents.
- Context summary and conversation log remain compact.
- File summary paths cannot escape repo boundaries because `MemoryRuntime.get_file_summary()` delegates to existing `build_file_summary()`.
- Memory recall remains bounded by `max_memory_items` and `max_memory_chars`.
- Existing OpenAI native tool-result message chain still works.
- No benchmark metric is claimed as achieved unless a report was generated.

- [ ] **Step 6: Commit any verification fixes**

If verification required changes:

```bash
git add <changed files>
git commit -m "fix context compaction verification issues"
```

If no changes were needed, do not create an empty commit.

---

## Self-Review Checklist

- Spec coverage:
  - Context budget expansion is covered by Task 1.
  - Observation compaction is covered by Tasks 2 and 3.
  - Memory recall character bounding is covered by Task 3.
  - Repeated-read file summary references are covered by Task 4.
  - Prompt/scenario coverage and docs are covered by Task 5.
  - Final regression is covered by Task 6.

- Scope control:
  - This plan does not implement SKILL.md.
  - This plan does not add TUI review queue UI.
  - This plan does not claim token reduction metrics.
  - This plan keeps provider adapters unchanged unless tests prove they must change.

- Type consistency:
  - `ContextBudget` and `ContextMetrics` remain strict Pydantic models.
  - `ContextManager.build_provider_context()` continues returning `ContextBundle`.
  - `MemoryRuntime.get_file_summary(repo_path, path)` remains the file-summary access point.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-30-context-compaction-v1.md`. Two execution options:

1. **Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
