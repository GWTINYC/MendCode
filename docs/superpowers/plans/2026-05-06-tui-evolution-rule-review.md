# TUI Evolution Rule Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first TUI-first self-evolution loop where natural-language TUI requests can list, view, accept, reject, and edit-accept rule candidates, and accepted rules are recalled into AgentLoop context.

**Architecture:** Extend the existing review queue with `target_kind=rule`, add an evolution rule store under `data/evolution/rules.jsonl`, expose rule review operations through ToolRegistry schema tools, and inject relevant accepted rules through ContextManager. Keep CLI out of the primary product path; all user-facing behavior is through model tool calls in the TUI.

**Tech Stack:** Python 3.12, Pydantic, ToolRegistry, PermissionPolicy, ContextManager, Textual scenario harness, JSONL local stores, pytest, ruff.

---

## Worktree Requirement

Implementation must start from a dedicated worktree:

```bash
cd /home/wxh/MendCode
git worktree add .worktrees/tui-evolution-rule-review -b tui-evolution-rule-review develop
cd .worktrees/tui-evolution-rule-review
```

Run the clean baseline before editing:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: both commands pass before feature work starts.

---

## File Structure

Create:

- `app/evolution/rules.py`
  - `EvolutionRuleStore`
  - `EvolutionRuleRuntime`
  - relevance scoring / top-3 recall
  - accept / reject / accept-with-edits orchestration
- `app/tools/evolution_tools.py`
  - Tool executors for TUI-facing schema tools.
- `tests/unit/test_evolution_rules.py`
  - Store, candidate transition, immutable evidence, recall ranking tests.
- `tests/unit/test_evolution_tools.py`
  - ToolRegistry executor behavior and compact payload tests.
- `tests/unit/test_context_evolution_rules.py`
  - ContextManager provider-context injection tests.
- `tests/scenarios/test_tui_evolution_rule_scenarios.py`
  - TUI natural-language review flow tests.

Modify:

- `app/evolution/models.py`
  - Add rule candidate / accepted rule models.
  - Extend `LessonCandidate` with `target_kind` and optional `rule_candidate`.
- `app/memory/review_queue.py`
  - Preserve existing JSONL behavior while accepting rule candidates.
- `app/memory/runtime.py`
  - Keep memory promotion behavior for memory candidates and reject memory promotion for rule candidates.
- `app/tools/arguments.py`
  - Add Pydantic args for rule tools.
- `app/tools/registry.py`
  - Register `evolution_rule_*` tools.
- `app/context/models.py`
  - Add context item kind for evolution rules and budget fields.
- `app/context/manager.py`
  - Recall accepted rules during `begin_turn()` and inject bounded context.
- `app/runtime/agent_loop.py`
  - Construct and pass `EvolutionRuleRuntime` / store to `ContextManager`.
- `README.md`
  - Document natural-language TUI rule review as the self-evolution path.
- `MendCode_开发方案.md`
  - Update current status and next steps.

Do not add a primary CLI command in this slice.

---

### Task 1: Add Rule Models And JSONL Store

**Files:**
- Modify: `app/evolution/models.py`
- Create: `app/evolution/rules.py`
- Test: `tests/unit/test_evolution_rules.py`

- [ ] **Step 1: Write failing model/store tests**

Create `tests/unit/test_evolution_rules.py` with these tests:

```python
from pathlib import Path

import pytest

from app.evolution.models import EvolutionRuleCandidate
from app.evolution.rules import EvolutionRuleStore


def _candidate(candidate_id: str = "rule-1") -> EvolutionRuleCandidate:
    return EvolutionRuleCandidate(
        candidate_id=candidate_id,
        rule_type="observation_required",
        rule_text="Do not state local repository facts without a successful observation.",
        scope="local facts",
        activation_hint="git status, directory listing, file content",
        source_report="data/analysis-reports/session.json",
        source_trace="data/traces/session.jsonl",
        evidence={"unsupported_claim": "unsupported_local_claim"},
        root_cause="tool_selection_gap",
    )


def test_rule_candidate_defaults_are_pending() -> None:
    candidate = _candidate()

    assert candidate.status == "pending"
    assert candidate.rule_type == "observation_required"


def test_rule_store_accepts_candidate_and_persists_rule(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    accepted = store.accept_candidate(_candidate())
    reloaded = EvolutionRuleStore(tmp_path / "data" / "evolution").list_rules()

    assert accepted.candidate_id == "rule-1"
    assert accepted.rule_type == "observation_required"
    assert accepted.status == "active"
    assert reloaded == [accepted]


def test_rule_store_accept_with_edits_only_changes_allowed_fields(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    accepted = store.accept_candidate(
        _candidate(),
        edits={
            "rule_text": "Answer Git status only after calling git.",
            "scope": "git status",
            "activation_hint": "git status",
        },
    )

    assert accepted.rule_text == "Answer Git status only after calling git."
    assert accepted.scope == "git status"
    assert accepted.activation_hint == "git status"
    assert accepted.source_report == "data/analysis-reports/session.json"
    assert accepted.source_trace == "data/traces/session.jsonl"


def test_rule_store_rejects_immutable_edits(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    with pytest.raises(ValueError, match="immutable"):
        store.accept_candidate(_candidate(), edits={"source_trace": "changed.jsonl"})


def test_rule_store_is_idempotent_for_same_candidate(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")

    first = store.accept_candidate(_candidate())
    second = store.accept_candidate(_candidate())

    assert second.rule_id == first.rule_id
    assert store.list_rules() == [first]
```

- [ ] **Step 2: Run tests to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_rules.py -q
```

Expected: import errors for `EvolutionRuleCandidate` and `EvolutionRuleStore`.

- [ ] **Step 3: Add rule models**

In `app/evolution/models.py`, add:

```python
from typing import Any

EvolutionRuleType = Literal[
    "tool_required",
    "observation_required",
    "tool_schema_hint",
    "answer_style",
]
EvolutionRuleStatus = Literal["active", "disabled"]
EvolutionRuleCandidateStatus = Literal["pending", "accepted", "rejected"]
EvolutionTargetKind = Literal["memory", "rule"]


class EvolutionRuleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=120)
    rule_type: EvolutionRuleType
    rule_text: str = Field(min_length=1, max_length=1200)
    scope: str = Field(default="", max_length=400)
    activation_hint: str = Field(default="", max_length=600)
    source_report: str | None = Field(default=None, max_length=240)
    source_trace: str | None = Field(default=None, max_length=240)
    evidence: dict[str, Any] = Field(default_factory=dict)
    root_cause: str | None = Field(default=None, max_length=240)
    status: EvolutionRuleCandidateStatus = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class EvolutionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    candidate_id: str
    rule_type: EvolutionRuleType
    rule_text: str = Field(min_length=1, max_length=1200)
    scope: str = Field(default="", max_length=400)
    activation_hint: str = Field(default="", max_length=600)
    evidence_ref: str | None = None
    source_report: str | None = None
    source_trace: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    status: EvolutionRuleStatus = "active"
```

Extend `LessonCandidate`:

```python
target_kind: EvolutionTargetKind = "memory"
rule_candidate: EvolutionRuleCandidate | None = None
```

Keep defaults backward-compatible so existing candidates validate as memory candidates.

- [ ] **Step 4: Add store implementation**

Create `app/evolution/rules.py`:

```python
from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from app.evolution.models import EvolutionRule, EvolutionRuleCandidate

EDITABLE_RULE_FIELDS = {"rule_text", "scope", "activation_hint"}


class EvolutionRuleStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "rules.jsonl"

    def list_rules(self) -> list[EvolutionRule]:
        rules: list[EvolutionRule] = []
        for line in self._raw_lines():
            if not line.strip():
                continue
            try:
                rules.append(EvolutionRule.model_validate_json(line))
            except ValidationError:
                continue
        return rules

    def accept_candidate(
        self,
        candidate: EvolutionRuleCandidate,
        *,
        edits: dict[str, str] | None = None,
    ) -> EvolutionRule:
        existing = self.rule_for_candidate(candidate.candidate_id)
        if existing is not None:
            return existing
        payload = candidate.model_dump()
        if edits:
            immutable = sorted(set(edits) - EDITABLE_RULE_FIELDS)
            if immutable:
                raise ValueError(f"immutable rule fields cannot be edited: {', '.join(immutable)}")
            payload.update(edits)
        now = datetime.now().astimezone()
        rule = EvolutionRule(
            rule_id=_rule_id(candidate.candidate_id),
            candidate_id=candidate.candidate_id,
            rule_type=payload["rule_type"],
            rule_text=payload["rule_text"],
            scope=payload.get("scope") or "",
            activation_hint=payload.get("activation_hint") or "",
            evidence_ref=f"rule_candidate:{candidate.candidate_id}",
            source_report=payload.get("source_report"),
            source_trace=payload.get("source_trace"),
            created_at=now,
            updated_at=now,
            status="active",
        )
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(rule.model_dump_json())
            handle.write("\n")
        return rule

    def rule_for_candidate(self, candidate_id: str) -> EvolutionRule | None:
        for rule in self.list_rules():
            if rule.candidate_id == candidate_id:
                return rule
        return None

    def _raw_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()


def _rule_id(candidate_id: str) -> str:
    digest = hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:16]
    return f"rule-{digest}"
```

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_rules.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/evolution/models.py app/evolution/rules.py tests/unit/test_evolution_rules.py
git commit -m "feat: add evolution rule store"
```

---

### Task 2: Add Rule Runtime, Candidate State, And Recall Ranking

**Files:**
- Modify: `app/evolution/rules.py`
- Modify: `app/memory/runtime.py`
- Test: `tests/unit/test_evolution_rules.py`

- [ ] **Step 1: Add failing runtime tests**

Append to `tests/unit/test_evolution_rules.py`:

```python
from app.evolution.models import LessonCandidate
from app.evolution.rules import EvolutionRuleRuntime
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def test_rule_runtime_accepts_rule_candidate_and_updates_queue(tmp_path: Path) -> None:
    memory = MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))
    runtime = EvolutionRuleRuntime(memory.review_queue, EvolutionRuleStore(tmp_path / "data" / "evolution"))
    lesson = LessonCandidate(
        id="candidate-1",
        kind="tool_policy_lesson",
        summary="Git status needs git tool",
        target_kind="rule",
        rule_candidate=_candidate("candidate-1"),
    )
    memory.enqueue_candidate(lesson)

    accepted = runtime.accept("candidate-1")
    listed = memory.list_candidates()

    assert accepted.candidate_id == "candidate-1"
    assert listed[0].status == "accepted"


def test_rule_runtime_accept_with_edits_preserves_evidence(tmp_path: Path) -> None:
    memory = MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))
    runtime = EvolutionRuleRuntime(memory.review_queue, EvolutionRuleStore(tmp_path / "data" / "evolution"))
    lesson = LessonCandidate(
        id="candidate-1",
        kind="tool_policy_lesson",
        summary="Git status needs git tool",
        target_kind="rule",
        rule_candidate=_candidate("candidate-1"),
    )
    memory.enqueue_candidate(lesson)

    accepted = runtime.accept_with_edits(
        "candidate-1",
        rule_text="回答 Git 状态前必须调用 git 工具。",
        scope="git status",
        activation_hint="git status",
    )

    assert accepted.rule_text == "回答 Git 状态前必须调用 git 工具。"
    assert accepted.source_trace == "data/traces/session.jsonl"


def test_rule_runtime_rejects_rule_candidate_without_writing_rule(tmp_path: Path) -> None:
    memory = MemoryRuntime(MemoryStore(tmp_path / "data" / "memory"))
    rule_store = EvolutionRuleStore(tmp_path / "data" / "evolution")
    runtime = EvolutionRuleRuntime(memory.review_queue, rule_store)
    lesson = LessonCandidate(
        id="candidate-1",
        kind="tool_policy_lesson",
        summary="Git status needs git tool",
        target_kind="rule",
        rule_candidate=_candidate("candidate-1"),
    )
    memory.enqueue_candidate(lesson)

    rejected = runtime.reject("candidate-1")

    assert rejected.status == "rejected"
    assert rule_store.list_rules() == []


def test_rule_runtime_recalls_relevant_top_three_rules(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")
    for index, hint in enumerate(["git status", "last sentence", "directory listing", "pytest"], start=1):
        store.accept_candidate(
            EvolutionRuleCandidate(
                candidate_id=f"rule-{index}",
                rule_type="tool_required",
                rule_text=f"Rule for {hint}",
                scope=hint,
                activation_hint=hint,
            )
        )
    runtime = EvolutionRuleRuntime(None, store)

    recalled = runtime.recall_for_turn("请查看 git status", max_rules=3, max_chars=500)

    assert len(recalled.rules) <= 3
    assert recalled.rules[0].scope == "git status"
    assert "Rule for git status" in recalled.context_block
```

- [ ] **Step 2: Run tests to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_rules.py -q
```

Expected: `EvolutionRuleRuntime` import failure.

- [ ] **Step 3: Implement runtime**

Add to `app/evolution/rules.py`:

```python
from pydantic import BaseModel, ConfigDict, Field

from app.evolution.models import LessonCandidate
from app.memory.review_queue import MemoryReviewQueue


class EvolutionRuleRecall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[EvolutionRule] = Field(default_factory=list)
    context_block: str = ""
    total_active_rules: int = 0
    truncated: bool = False


class EvolutionRuleRuntime:
    def __init__(
        self,
        review_queue: MemoryReviewQueue | None,
        rule_store: EvolutionRuleStore,
    ) -> None:
        self.review_queue = review_queue
        self.rule_store = rule_store

    def accept(self, candidate_id: str) -> EvolutionRule:
        candidate = self._rule_lesson(candidate_id)
        rule = self.rule_store.accept_candidate(candidate.rule_candidate)
        self.review_queue.update_status(candidate.id, "accepted")
        return rule

    def accept_with_edits(
        self,
        candidate_id: str,
        *,
        rule_text: str,
        scope: str,
        activation_hint: str,
    ) -> EvolutionRule:
        candidate = self._rule_lesson(candidate_id)
        rule = self.rule_store.accept_candidate(
            candidate.rule_candidate,
            edits={
                "rule_text": rule_text,
                "scope": scope,
                "activation_hint": activation_hint,
            },
        )
        self.review_queue.update_status(candidate.id, "accepted")
        return rule

    def reject(self, candidate_id: str) -> LessonCandidate:
        candidate = self._rule_lesson(candidate_id)
        return self.review_queue.update_status(candidate.id, "rejected")

    def list_candidates(self, *, status: str = "pending", limit: int = 20) -> list[LessonCandidate]:
        if self.review_queue is None:
            return []
        candidates = [
            candidate
            for candidate in self.review_queue.list_candidates()
            if candidate.target_kind == "rule" and candidate.rule_candidate is not None
        ]
        if status != "all":
            candidates = [candidate for candidate in candidates if candidate.status == status]
        return candidates[:limit]

    def candidate_for_id(self, candidate_id: str) -> LessonCandidate:
        return self._rule_lesson(candidate_id)

    def recall_for_turn(
        self,
        user_message: str,
        *,
        max_rules: int = 3,
        max_chars: int = 1200,
    ) -> EvolutionRuleRecall:
        active_rules = [rule for rule in self.rule_store.list_rules() if rule.status == "active"]
        ranked = sorted(
            active_rules,
            key=lambda rule: _rule_score(rule, user_message),
            reverse=True,
        )
        selected: list[EvolutionRule] = []
        lines = ["Accepted Evolution Rules:"]
        total_chars = len(lines[0])
        for rule in ranked:
            if len(selected) >= max_rules:
                break
            if _rule_score(rule, user_message) <= 0:
                continue
            line = f"- [{rule.rule_type}] {rule.rule_text}"
            if selected and total_chars + len(line) > max_chars:
                break
            selected.append(rule)
            lines.append(line)
            total_chars += len(line)
        return EvolutionRuleRecall(
            rules=selected,
            context_block="\n".join(lines) if selected else "",
            total_active_rules=len(active_rules),
            truncated=len(selected) < len([rule for rule in ranked if _rule_score(rule, user_message) > 0]),
        )

    def _rule_lesson(self, candidate_id: str) -> LessonCandidate:
        if self.review_queue is None:
            raise KeyError(f"unknown rule candidate: {candidate_id}")
        for candidate in self.review_queue.list_candidates():
            if candidate.id != candidate_id:
                continue
            if candidate.target_kind != "rule" or candidate.rule_candidate is None:
                raise ValueError(f"review candidate is not a rule candidate: {candidate_id}")
            if candidate.status == "accepted":
                raise ValueError(f"cannot modify accepted rule candidate: {candidate_id}")
            if candidate.status == "rejected":
                raise ValueError(f"cannot modify rejected rule candidate: {candidate_id}")
            return candidate
        raise KeyError(f"unknown rule candidate: {candidate_id}")


def _rule_score(rule: EvolutionRule, user_message: str) -> int:
    text = user_message.casefold()
    score = 0
    for weight, field in [
        (5, rule.scope),
        (4, rule.activation_hint),
        (2, rule.rule_text),
    ]:
        for token in _tokens(field):
            if token in text:
                score += weight
    if rule.rule_type == "tool_required" and any(term in text for term in ["git", "文件", "目录", "status"]):
        score += 2
    if rule.rule_type == "observation_required" and any(term in text for term in ["文件", "目录", "git", "状态"]):
        score += 2
    return score


def _tokens(value: str) -> set[str]:
    return {token for token in value.casefold().replace(",", " ").split() if len(token) >= 2}
```

- [ ] **Step 4: Guard MemoryRuntime memory promotion**

In `app/memory/runtime.py`, update `accept_candidate()`:

```python
if candidate.target_kind != "memory":
    raise ValueError(f"cannot promote {candidate.target_kind} candidate to memory: {candidate_id}")
```

Place this after `_candidate_for_id()` and before duplicate-memory checks.

- [ ] **Step 5: Run tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_rules.py tests/unit/test_memory_runtime.py tests/unit/test_memory_tools.py -q
```

Expected: tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/evolution/rules.py app/memory/runtime.py tests/unit/test_evolution_rules.py
git commit -m "feat: add evolution rule runtime"
```

---

### Task 3: Add TUI-Facing Schema Tools

**Files:**
- Modify: `app/tools/arguments.py`
- Create: `app/tools/evolution_tools.py`
- Modify: `app/tools/registry.py`
- Test: `tests/unit/test_evolution_tools.py`

- [ ] **Step 1: Write failing tool tests**

Create `tests/unit/test_evolution_tools.py`:

```python
from pathlib import Path

from app.config.settings import Settings
from app.evolution.models import EvolutionRuleCandidate, LessonCandidate
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolExecutionContext


def _settings(tmp_path: Path) -> Settings:
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


def _context(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_path=tmp_path,
        settings=_settings(tmp_path),
        memory_store=MemoryStore(tmp_path / "data" / "memory"),
    )


def _seed_rule_candidate(context: ToolExecutionContext, candidate_id: str = "rule-1") -> None:
    assert context.memory_store is not None
    MemoryRuntime(context.memory_store).enqueue_candidate(
        LessonCandidate(
            id=candidate_id,
            kind="tool_policy_lesson",
            summary="Git status must use a tool.",
            target_kind="rule",
            rule_candidate=EvolutionRuleCandidate(
                candidate_id=candidate_id,
                rule_type="tool_required",
                rule_text="查看 Git 状态前必须调用 git 工具。",
                scope="git status",
                activation_hint="git status",
                evidence={"missing_tools": ["git"]},
                root_cause="tool_selection_gap",
            ),
        )
    )


def test_evolution_rule_list_returns_compact_pending_candidates(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_list").execute({"status": "pending"}, context)

    assert result.status == "succeeded"
    assert result.payload["total_candidates"] == 1
    candidate = result.payload["candidates"][0]
    assert candidate["id"] == "rule-1"
    assert candidate["rule_type"] == "tool_required"
    assert "evidence" not in candidate


def test_evolution_rule_view_returns_bounded_evidence(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_view").execute({"candidate_id": "rule-1"}, context)

    assert result.status == "succeeded"
    assert result.payload["candidate"]["id"] == "rule-1"
    assert result.payload["candidate"]["evidence"]["missing_tools"] == ["git"]


def test_evolution_rule_accept_writes_rule(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_accept").execute({"candidate_id": "rule-1"}, context)

    assert result.status == "succeeded"
    assert result.payload["rule"]["candidate_id"] == "rule-1"
    assert (tmp_path / "data" / "evolution" / "rules.jsonl").exists()


def test_evolution_rule_accept_with_edits_preserves_evidence(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_accept_with_edits").execute(
        {
            "candidate_id": "rule-1",
            "rule_text": "回答 Git 状态前必须调用 git 工具。",
            "scope": "git status",
            "activation_hint": "git status",
        },
        context,
    )

    assert result.status == "succeeded"
    assert result.payload["rule"]["rule_text"] == "回答 Git 状态前必须调用 git 工具。"


def test_evolution_rule_reject_does_not_write_rule(tmp_path: Path) -> None:
    registry = default_tool_registry()
    context = _context(tmp_path)
    _seed_rule_candidate(context)

    result = registry.get("evolution_rule_reject").execute({"candidate_id": "rule-1"}, context)

    assert result.status == "succeeded"
    assert not (tmp_path / "data" / "evolution" / "rules.jsonl").exists()
```

- [ ] **Step 2: Run tests to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_tools.py -q
```

Expected: missing tool errors.

- [ ] **Step 3: Add args models**

In `app/tools/arguments.py`, add:

```python
class EvolutionRuleListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "accepted", "rejected", "all"] = "pending"
    limit: int = Field(default=20, ge=1, le=100)


class EvolutionRuleViewArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)


class EvolutionRuleActionArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)


class EvolutionRuleAcceptWithEditsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1)
    rule_text: str = Field(min_length=1, max_length=1200)
    scope: str = Field(default="", max_length=400)
    activation_hint: str = Field(default="", max_length=600)
```

- [ ] **Step 4: Add tool executors**

Create `app/tools/evolution_tools.py`:

```python
from app.evolution.rules import EvolutionRuleRuntime, EvolutionRuleStore
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore
from app.schemas.agent_action import Observation
from app.tools.arguments import (
    EvolutionRuleAcceptWithEditsArgs,
    EvolutionRuleActionArgs,
    EvolutionRuleListArgs,
    EvolutionRuleViewArgs,
)
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def evolution_rule_list(args: EvolutionRuleListArgs, context: ToolExecutionContext) -> Observation:
    runtime = _rule_runtime(context)
    candidates = runtime.list_candidates(status=args.status, limit=args.limit)
    return tool_observation(
        tool_name="evolution_rule_list",
        status="succeeded",
        summary=f"Found {len(candidates)} evolution rule candidates",
        payload={
            "status": args.status,
            "total_candidates": len(candidates),
            "candidates": [_compact_candidate(candidate) for candidate in candidates],
        },
    )


def evolution_rule_view(args: EvolutionRuleViewArgs, context: ToolExecutionContext) -> Observation:
    runtime = _rule_runtime(context)
    try:
        candidate = runtime.candidate_for_id(args.candidate_id)
    except (KeyError, ValueError) as exc:
        return _rejected("evolution_rule_view", args.candidate_id, exc)
    return tool_observation(
        tool_name="evolution_rule_view",
        status="succeeded",
        summary=f"Read evolution rule candidate {candidate.id}",
        payload={"candidate": _view_candidate(candidate)},
    )


def evolution_rule_accept(args: EvolutionRuleActionArgs, context: ToolExecutionContext) -> Observation:
    runtime = _rule_runtime(context)
    try:
        rule = runtime.accept(args.candidate_id)
    except (KeyError, ValueError) as exc:
        return _rejected("evolution_rule_accept", args.candidate_id, exc)
    return _accepted("evolution_rule_accept", args.candidate_id, rule.model_dump(mode="json"))


def evolution_rule_reject(args: EvolutionRuleActionArgs, context: ToolExecutionContext) -> Observation:
    runtime = _rule_runtime(context)
    try:
        candidate = runtime.reject(args.candidate_id)
    except (KeyError, ValueError) as exc:
        return _rejected("evolution_rule_reject", args.candidate_id, exc)
    return tool_observation(
        tool_name="evolution_rule_reject",
        status="succeeded",
        summary=f"Rejected evolution rule candidate {args.candidate_id}",
        payload={"candidate_id": candidate.id, "status": candidate.status},
    )


def evolution_rule_accept_with_edits(
    args: EvolutionRuleAcceptWithEditsArgs,
    context: ToolExecutionContext,
) -> Observation:
    runtime = _rule_runtime(context)
    try:
        rule = runtime.accept_with_edits(
            args.candidate_id,
            rule_text=args.rule_text,
            scope=args.scope,
            activation_hint=args.activation_hint,
        )
    except (KeyError, ValueError) as exc:
        return _rejected("evolution_rule_accept_with_edits", args.candidate_id, exc)
    return _accepted(
        "evolution_rule_accept_with_edits",
        args.candidate_id,
        rule.model_dump(mode="json"),
    )


def _rule_runtime(context: ToolExecutionContext) -> EvolutionRuleRuntime:
    store = context.memory_store
    if not isinstance(store, MemoryStore):
        store = MemoryStore(context.settings.data_dir / "memory")
    memory_runtime = MemoryRuntime(store)
    return EvolutionRuleRuntime(
        memory_runtime.review_queue,
        EvolutionRuleStore(context.settings.data_dir / "evolution"),
    )


def _compact_candidate(candidate) -> dict[str, object]:
    rule = candidate.rule_candidate
    return {
        "id": candidate.id,
        "status": candidate.status,
        "summary": candidate.summary,
        "rule_type": rule.rule_type,
        "rule_text": rule.rule_text[:300],
        "scope": rule.scope,
        "activation_hint": rule.activation_hint,
    }


def _view_candidate(candidate) -> dict[str, object]:
    payload = _compact_candidate(candidate)
    rule = candidate.rule_candidate
    payload.update(
        {
            "source_report": rule.source_report,
            "source_trace": rule.source_trace,
            "root_cause": rule.root_cause,
            "evidence": rule.evidence,
        }
    )
    return payload


def _accepted(tool_name: str, candidate_id: str, rule: dict[str, object]) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="succeeded",
        summary=f"Accepted evolution rule candidate {candidate_id}",
        payload={"candidate_id": candidate_id, "rule": rule},
    )


def _rejected(tool_name: str, candidate_id: str, exc: Exception) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="rejected",
        summary="Unable to operate on evolution rule candidate",
        payload={"candidate_id": candidate_id},
        error_message=str(exc),
    )
```

- [ ] **Step 5: Register tools**

In `app/tools/registry.py`, import args/executors and add `ToolSpec`s:

```python
ToolSpec(
    name="evolution_rule_list",
    description="List pending evolution rule candidates for TUI review.",
    args_model=EvolutionRuleListArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=evolution_rule_list,
)
ToolSpec(
    name="evolution_rule_view",
    description="View one evolution rule candidate with bounded evidence.",
    args_model=EvolutionRuleViewArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=evolution_rule_view,
)
ToolSpec(
    name="evolution_rule_accept",
    description="Accept an evolution rule candidate and persist an active rule.",
    args_model=EvolutionRuleActionArgs,
    risk_level=ToolRisk.DANGEROUS,
    executor=evolution_rule_accept,
)
ToolSpec(
    name="evolution_rule_reject",
    description="Reject an evolution rule candidate without changing active rules.",
    args_model=EvolutionRuleActionArgs,
    risk_level=ToolRisk.DANGEROUS,
    executor=evolution_rule_reject,
)
ToolSpec(
    name="evolution_rule_accept_with_edits",
    description="Accept an evolution rule candidate with edited rule text, scope, and activation hint.",
    args_model=EvolutionRuleAcceptWithEditsArgs,
    risk_level=ToolRisk.DANGEROUS,
    executor=evolution_rule_accept_with_edits,
)
```

- [ ] **Step 6: Run tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_evolution_tools.py tests/unit/test_tool_registry.py tests/unit/test_tool_schemas.py -q
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/tools/arguments.py app/tools/evolution_tools.py app/tools/registry.py tests/unit/test_evolution_tools.py
git commit -m "feat: expose evolution rule review tools"
```

---

### Task 4: Inject Accepted Rules Into ContextManager

**Files:**
- Modify: `app/context/models.py`
- Modify: `app/context/manager.py`
- Modify: `app/runtime/agent_loop.py`
- Test: `tests/unit/test_context_evolution_rules.py`
- Test: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: Write context tests**

Create `tests/unit/test_context_evolution_rules.py`:

```python
import json
from pathlib import Path

from app.context.manager import ContextManager
from app.evolution.models import EvolutionRuleCandidate
from app.evolution.rules import EvolutionRuleRuntime, EvolutionRuleStore
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def test_context_manager_injects_relevant_accepted_rules(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")
    store.accept_candidate(
        EvolutionRuleCandidate(
            candidate_id="rule-git",
            rule_type="tool_required",
            rule_text="回答 Git 状态前必须调用 git 工具。",
            scope="git status",
            activation_hint="git status",
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(tmp_path / "data" / "memory")),
        evolution_rule_runtime=EvolutionRuleRuntime(None, store),
    )

    bundle = manager.begin_turn(user_message="请查看 git status", repo_path=tmp_path)
    payload = json.loads(bundle.provider_context)

    assert payload["evolution_rules"][0]["rule_type"] == "tool_required"
    assert "Git 状态" in payload["evolution_rules"][0]["rule_text"]


def test_context_manager_omits_irrelevant_rules(tmp_path: Path) -> None:
    store = EvolutionRuleStore(tmp_path / "data" / "evolution")
    store.accept_candidate(
        EvolutionRuleCandidate(
            candidate_id="rule-last-line",
            rule_type="answer_style",
            rule_text="用户问最后一句时只回答最后一句。",
            scope="最后一句",
            activation_hint="last sentence",
        )
    )
    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(tmp_path / "data" / "memory")),
        evolution_rule_runtime=EvolutionRuleRuntime(None, store),
    )

    bundle = manager.begin_turn(user_message="请查看 git status", repo_path=tmp_path)
    payload = json.loads(bundle.provider_context)

    assert payload["evolution_rules"] == []


def test_context_manager_rule_recall_failure_becomes_warning(tmp_path: Path) -> None:
    class FailingRuleRuntime:
        def recall_for_turn(self, *_args, **_kwargs):
            raise RuntimeError("rule store unavailable")

    manager = ContextManager(
        memory_runtime=MemoryRuntime(MemoryStore(tmp_path / "data" / "memory")),
        evolution_rule_runtime=FailingRuleRuntime(),
    )

    bundle = manager.begin_turn(user_message="git status", repo_path=tmp_path)

    assert any(warning.code == "evolution_rule_recall_failed" for warning in bundle.warnings)
```

- [ ] **Step 2: Run tests to verify red**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_evolution_rules.py -q
```

Expected: `ContextManager` does not accept `evolution_rule_runtime`.

- [ ] **Step 3: Extend context models**

In `app/context/models.py`, add:

```python
"evolution_rule",
```

to `ContextItemKind`, and add budget fields:

```python
max_evolution_rules: int = Field(default=3, ge=0)
max_evolution_rule_chars: int = Field(default=1200, ge=0)
```

- [ ] **Step 4: Extend ContextManager**

In `app/context/manager.py`:

- Add constructor parameter:

```python
evolution_rule_runtime: object | None = None
```

- Store `_evolution_rules: list[dict[str, object]] = []`.
- In `begin_turn()`, call:

```python
if self.evolution_rule_runtime is not None and self.budget.max_evolution_rules > 0:
    try:
        recall = self.evolution_rule_runtime.recall_for_turn(
            user_message,
            max_rules=self.budget.max_evolution_rules,
            max_chars=self.budget.max_evolution_rule_chars,
        )
        self._evolution_rules = [
            {
                "rule_id": rule.rule_id,
                "rule_type": rule.rule_type,
                "rule_text": rule.rule_text,
                "scope": rule.scope,
                "activation_hint": rule.activation_hint,
            }
            for rule in recall.rules
        ]
    except Exception as exc:
        self._warnings.append(
            ContextWarning(
                code="evolution_rule_recall_failed",
                message=str(exc),
                source="evolution_rule_runtime",
            )
        )
```

- Add `"evolution_rules": self._evolution_rules` to `_provider_context_json()`.
- Add `ContextItem(kind="evolution_rule", ...)` entries in `_context_items()`.

- [ ] **Step 5: Wire AgentLoop**

In `app/runtime/agent_loop.py`, import:

```python
from app.evolution.rules import EvolutionRuleRuntime, EvolutionRuleStore
```

Before constructing `ContextManager`:

```python
evolution_rule_runtime = EvolutionRuleRuntime(
    None,
    EvolutionRuleStore(settings.data_dir / "evolution"),
)
```

Pass it:

```python
context_manager = ContextManager(
    memory_runtime=memory_runtime,
    evolution_rule_runtime=evolution_rule_runtime,
    base_context=loop_input.provider_context,
)
```

Do not pass a review queue here; runtime recall only needs accepted rules.

- [ ] **Step 6: Run context and agent-loop tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_context_evolution_rules.py tests/unit/test_context_manager.py tests/unit/test_agent_loop.py -q
```

Expected: tests pass.

- [ ] **Step 7: Commit**

```bash
git add app/context/models.py app/context/manager.py app/runtime/agent_loop.py tests/unit/test_context_evolution_rules.py
git commit -m "feat: recall accepted evolution rules"
```

---

### Task 5: Add TUI Natural-Language Scenario Coverage

**Files:**
- Create: `tests/scenarios/test_tui_evolution_rule_scenarios.py`
- Modify if needed: `tests/scenarios/tui_scenario_runner.py`

- [ ] **Step 1: Write TUI scenario tests**

Create `tests/scenarios/test_tui_evolution_rule_scenarios.py`:

```python
import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_tui_lists_pending_evolution_rules(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="evolution rule list",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["有哪些待确认的规则？"],
            tool_steps=[
                ScenarioToolStep(
                    action="evolution_rule_list",
                    status="succeeded",
                    summary="Found 1 evolution rule candidates",
                    payload={
                        "status": "pending",
                        "total_candidates": 1,
                        "candidates": [
                            {
                                "id": "rule-1",
                                "rule_type": "observation_required",
                                "rule_text": "回答本地事实前必须有成功 observation。",
                                "scope": "local facts",
                                "activation_hint": "git status",
                            }
                        ],
                    },
                    args={"status": "pending"},
                )
            ],
            final_summary="有 1 条待确认规则：回答本地事实前必须有成功 observation。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_visible_answer_contains(transcript, "待确认规则")
    assert_visible_answer_contains(transcript, "observation")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=800)
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_tui_accepts_rule_candidate(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="evolution rule accept",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["接受第一条规则"],
            tool_steps=[
                ScenarioToolStep(
                    action="evolution_rule_accept",
                    status="succeeded",
                    summary="Accepted evolution rule candidate rule-1",
                    payload={
                        "candidate_id": "rule-1",
                        "rule": {
                            "candidate_id": "rule-1",
                            "rule_type": "tool_required",
                            "rule_text": "回答 Git 状态前必须调用 git 工具。",
                        },
                    },
                    args={"candidate_id": "rule-1"},
                )
            ],
            final_summary="已接受第一条规则：回答 Git 状态前必须调用 git 工具。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_visible_answer_contains(transcript, "已接受")
    assert_visible_answer_contains(transcript, "Git")
    assert_no_raw_trace_or_large_json_dump(transcript)


async def test_tui_accepts_rule_candidate_with_edits(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="evolution rule accept with edits",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["接受第一条，但改成：回答 Git 状态前必须调用 git 工具。"],
            tool_steps=[
                ScenarioToolStep(
                    action="evolution_rule_accept_with_edits",
                    status="succeeded",
                    summary="Accepted evolution rule candidate rule-1",
                    payload={
                        "candidate_id": "rule-1",
                        "rule": {
                            "candidate_id": "rule-1",
                            "rule_type": "tool_required",
                            "rule_text": "回答 Git 状态前必须调用 git 工具。",
                            "scope": "git status",
                            "activation_hint": "git status",
                        },
                    },
                    args={
                        "candidate_id": "rule-1",
                        "rule_text": "回答 Git 状态前必须调用 git 工具。",
                        "scope": "git status",
                        "activation_hint": "git status",
                    },
                )
            ],
            final_summary="已按你的修改接受规则：回答 Git 状态前必须调用 git 工具。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_visible_answer_contains(transcript, "已按你的修改")
    assert_visible_answer_contains(transcript, "Git")
    assert_no_raw_trace_or_large_json_dump(transcript)
```

- [ ] **Step 2: Run scenario tests to verify red if tools are missing from harness**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/scenarios/test_tui_evolution_rule_scenarios.py -q
```

Expected after Task 3: tests should pass. If they fail because the scenario harness filters unknown tool names, update `tests/scenarios/tui_scenario_runner.py` to allow all registered ToolRegistry names.

- [ ] **Step 3: Commit**

```bash
git add tests/scenarios/test_tui_evolution_rule_scenarios.py tests/scenarios/tui_scenario_runner.py
git commit -m "test: cover tui evolution rule review"
```

---

### Task 6: Update Documentation

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`

- [x] **Step 1: Update README**

In the self-evolution section, add:

```markdown
第一版自进化规则审查以 TUI 自然语言为主入口。用户可以在对话里询问“有哪些待确认的规则”、 “接受第一条规则”、 “接受第一条，但改成……”。模型会调用 `evolution_rule_list`、`evolution_rule_accept`、`evolution_rule_accept_with_edits` 等 schema tools 完成审查动作。

被接受的规则写入 `data/evolution/rules.jsonl`。后续 AgentLoop 会按当前用户问题相关性召回最多 3 条 active rules 注入 provider context；pending / rejected candidate 不会影响模型行为。
```

- [x] **Step 2: Update development plan**

In `MendCode_开发方案.md`, update the Context / Evolution Runtime section:

```markdown
- [x] TUI-first evolution rule review：`evolution_rule_list/view/accept/reject/accept_with_edits` 已通过 ToolRegistry 暴露，用户可通过自然语言审查规则候选。
- [x] Accepted rules 写入 `data/evolution/rules.jsonl`，运行时按相关性召回 top 3 注入 provider context。
- [ ] 下一阶段：从 `SessionAnalysisReport` 自动生成 rule candidate，并进入同一 review loop。
```

- [ ] **Step 3: Commit docs**

```bash
git add README.md MendCode_开发方案.md
git commit -m "docs: document tui evolution rule review"
```

---

### Task 7: Final Verification And Merge

**Files:**
- No planned source edits.

- [ ] **Step 1: Run focused tests**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest \
  tests/unit/test_evolution_rules.py \
  tests/unit/test_evolution_tools.py \
  tests/unit/test_context_evolution_rules.py \
  tests/scenarios/test_tui_evolution_rule_scenarios.py \
  -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full non-e2e suite**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
```

Expected: all tests pass.

- [ ] **Step 3: Run ruff**

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: all checks pass.

- [ ] **Step 4: Manual smoke**

Run a small Python smoke from the worktree:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python - <<'PY'
from pathlib import Path
from app.evolution.models import EvolutionRuleCandidate
from app.evolution.rules import EvolutionRuleRuntime, EvolutionRuleStore

root = Path('/tmp/mendcode-rule-smoke')
store = EvolutionRuleStore(root / 'data' / 'evolution')
store.accept_candidate(EvolutionRuleCandidate(
    candidate_id='git-rule',
    rule_type='tool_required',
    rule_text='回答 Git 状态前必须调用 git 工具。',
    scope='git status',
    activation_hint='git status',
))
recall = EvolutionRuleRuntime(None, store).recall_for_turn('查看 git status')
print(recall.context_block)
PY
```

Expected output contains:

```text
Accepted Evolution Rules:
- [tool_required] 回答 Git 状态前必须调用 git 工具。
```

- [ ] **Step 5: Merge back to develop**

```bash
cd /home/wxh/MendCode
git merge --ff-only tui-evolution-rule-review
git worktree remove .worktrees/tui-evolution-rule-review
git branch -d tui-evolution-rule-review
```

Expected: feature branch is fast-forward merged and worktree is removed.

---

## Spec Coverage Self-Review

- TUI-first natural language review: Task 5 covers list, accept, and edit-accept scenario flows.
- Schema tools: Task 3 adds `evolution_rule_list/view/accept/reject/accept_with_edits`.
- Rule candidate and accepted rule model: Task 1.
- Existing review queue concept extended with `target_kind=rule`: Tasks 1 and 2.
- Accepted rules persisted to `data/evolution/rules.jsonl`: Task 1.
- Evidence immutable during edit-accept: Tasks 1 and 2.
- Relevant recall top 3 and budgeted context injection: Tasks 2 and 4.
- Pending/rejected candidates do not affect Agent behavior: Tasks 2 and 4.
- Write operations are high-risk ToolRegistry entries: Task 3.
- Documentation states TUI-first and not CLI-first: Task 6.
- Full verification and worktree merge: Task 7.
