# Tool Pool Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first post-schema-tool-call tool expansion slice: session introspection, tool groups/profiles, repeated call detection, background process tools, and a minimal LSP tool.

**Architecture:** Keep `ToolRegistry` as the only model-visible tool source and add focused helper modules instead of expanding `app/tools/registry.py` into a large file. AgentLoop remains the Harness: it builds richer `ToolExecutionContext`, enforces repeated-call policy before execution, dispatches process/LSP/session tools through the registry, and records compact observations for prompt, trace, and conversation logs.

**Tech Stack:** Python 3.12, Pydantic, OpenAI-compatible schema tool calls, subprocess/PTY process management, JSON-RPC LSP over stdio, pytest, pexpect PTY tests, ruff.

---

## Source Spec

- Design: `docs/superpowers/specs/2026-04-28-tool-pool-expansion-design.md`
- Existing registry: `app/tools/registry.py`
- Existing argument models: `app/tools/arguments.py`
- Existing ToolPool: `app/tools/structured.py`
- Existing AgentLoop runtime: `app/runtime/agent_loop.py`
- Compatibility action helpers: `app/agent/loop.py`

## File Map

- Create: `app/runtime/tool_repetition.py`
  - Owns normalized tool-call fingerprints and repeated-call decisions.
- Create: `app/runtime/process_registry.py`
  - Owns background subprocess lifecycle and bounded log reads.
- Create: `app/runtime/lsp_client.py`
  - Owns minimal JSON-RPC LSP client and unavailable-server behavior.
- Create: `app/tools/session_status.py`
  - Builds `session_status` observation from `ToolExecutionContext`.
- Create: `app/tools/process_tools.py`
  - Pydantic executors for `process_start`, `process_poll`, `process_write`, `process_stop`, `process_list`.
- Create: `app/tools/lsp_tool.py`
  - Pydantic executor for `lsp`.
- Modify: `app/tools/arguments.py`
  - Add `SessionStatusArgs`, process args, and `LspArgs`.
- Modify: `app/tools/structured.py`
  - Add tool groups/profiles and enrich `ToolExecutionContext`.
- Modify: `app/tools/registry.py`
  - Register new tools and delegate executors to new modules.
- Modify: `app/agent/loop.py`
  - Pass richer context to tool executors; keep compatibility wrappers working.
- Modify: `app/runtime/agent_loop.py`
  - Add repeated-call detection and pass `run_id`, trace path, permission mode, recent steps, and process registry in context.
- Modify: `app/tui/app.py`
  - Include new read-only tools where appropriate and render process/LSP/session summaries compactly.
- Test: `tests/unit/test_tool_registry.py`
- Test: `tests/unit/test_agent_loop.py`
- Test: `tests/unit/test_tool_repetition.py`
- Test: `tests/unit/test_process_registry.py`
- Test: `tests/unit/test_lsp_tool.py`
- Test: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Test: `tests/e2e/test_tui_pty_live.py`
- Modify docs after implementation: `README.md`, `MendCode_开发方案.md`, `MendCode_问题记录.md`

## Task 1: Session Status and Tool Groups

**Files:**
- Modify: `app/tools/arguments.py`
- Modify: `app/tools/structured.py`
- Create: `app/tools/session_status.py`
- Modify: `app/tools/registry.py`
- Test: `tests/unit/test_tool_registry.py`
- Test: `tests/scenarios/test_tui_repository_inspection_scenarios.py`

- [ ] **Step 1: Write failing registry tests for group expansion**

Add these tests to `tests/unit/test_tool_registry.py`:

```python
def test_registry_expands_tool_groups() -> None:
    registry = default_tool_registry()

    names = set(registry.names(allowed_tools={"fs_read", "introspection"}))

    assert {"read_file", "list_dir", "glob_file_search", "rg", "search_code"} <= names
    assert {"tool_search", "session_status"} <= names
    assert "write_file" not in names


def test_registry_expands_tool_profiles_then_applies_permission() -> None:
    registry = default_tool_registry()

    pool = registry.tool_pool(permission_mode="read-only", allowed_tools={"coding_agent"})
    names = set(pool.names())

    assert "read_file" in names
    assert "session_status" in names
    assert "lsp" in names
    assert "write_file" not in names
    assert "run_shell_command" not in names


def test_registry_rejects_unknown_tool_group() -> None:
    registry = default_tool_registry()

    with pytest.raises(KeyError, match="unknown allowed tool: unknown_group"):
        registry.names(allowed_tools={"unknown_group"})
```

- [ ] **Step 2: Run the group tests and verify they fail**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_registry.py::test_registry_expands_tool_groups tests/unit/test_tool_registry.py::test_registry_expands_tool_profiles_then_applies_permission tests/unit/test_tool_registry.py::test_registry_rejects_unknown_tool_group -q
```

Expected: at least the first two tests fail because groups/profiles and `session_status` do not exist.

- [ ] **Step 3: Add `SessionStatusArgs`**

In `app/tools/arguments.py`, add:

```python
class SessionStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    include_tools: bool = True
    include_recent_steps: bool = True
```

- [ ] **Step 4: Enrich `ToolExecutionContext`**

In `app/tools/structured.py`, extend `ToolExecutionContext` with these optional fields:

```python
class ToolExecutionContext(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    workspace_path: Path
    settings: Settings
    verification_commands: list[str] = Field(default_factory=list)
    available_tools: set[str] | None = None
    permission_mode: str | None = None
    allowed_tools: set[str] | None = None
    denied_tools: set[str] = Field(default_factory=set)
    run_id: str | None = None
    trace_path: str | None = None
    recent_steps: list[dict[str, object]] = Field(default_factory=list)
    pending_confirmation: dict[str, object] | None = None
```

Keep all fields optional except the existing three so current tests and compatibility code keep working.

- [ ] **Step 5: Add tool groups and profiles**

In `app/tools/structured.py`, replace `_TOOL_ALIASES` with an alias/group map that includes the existing aliases plus groups and profiles:

```python
_TOOL_ALIASES: dict[str, tuple[str, ...]] = {
    "status": ("repo_status",),
    "project": ("detect_project",),
    "diff": ("show_diff",),
    "read": ("read_file",),
    "ls": ("list_dir",),
    "list": ("list_dir",),
    "glob": ("glob_file_search",),
    "grep": ("rg", "search_code"),
    "search": ("search_code",),
    "shell": ("run_shell_command",),
    "bash": ("run_shell_command",),
    "patch": ("apply_patch",),
    "write": ("write_file",),
    "edit": ("edit_file",),
    "todo": ("todo_write",),
    "tools": ("tool_search",),
    "fs_read": ("read_file", "list_dir", "glob_file_search", "rg", "search_code"),
    "fs_write": ("apply_patch", "write_file", "edit_file"),
    "git_read": ("repo_status", "git", "show_diff"),
    "runtime": ("run_shell_command", "run_command"),
    "planning": ("todo_write",),
    "introspection": ("tool_search", "session_status"),
    "process": (
        "process_start",
        "process_poll",
        "process_write",
        "process_stop",
        "process_list",
    ),
    "lsp_tools": ("lsp",),
    "read_only_agent": (
        "read_file",
        "list_dir",
        "glob_file_search",
        "rg",
        "search_code",
        "repo_status",
        "git",
        "show_diff",
        "tool_search",
        "session_status",
        "lsp",
    ),
    "coding_agent": (
        "read_file",
        "list_dir",
        "glob_file_search",
        "rg",
        "search_code",
        "apply_patch",
        "write_file",
        "edit_file",
        "repo_status",
        "git",
        "show_diff",
        "run_shell_command",
        "run_command",
        "todo_write",
        "tool_search",
        "session_status",
        "process_start",
        "process_poll",
        "process_write",
        "process_stop",
        "process_list",
        "lsp",
    ),
    "repair_agent": ("coding_agent",),
    "simple_chat_tool_agent": (
        "read_file",
        "list_dir",
        "glob_file_search",
        "rg",
        "search_code",
        "repo_status",
        "git",
        "show_diff",
        "tool_search",
        "session_status",
    ),
}
```

Then update `_normalize_allowed_tools()` to expand nested aliases recursively:

```python
def _expand_allowed_tool_name(self, raw_name: str, seen: set[str]) -> set[str]:
    validate_tool_name(raw_name)
    if raw_name in seen:
        return set()
    seen.add(raw_name)
    aliases = _TOOL_ALIASES.get(raw_name)
    if aliases is None:
        if raw_name not in self._specs:
            raise KeyError(f"unknown allowed tool: {raw_name}")
        return {raw_name}
    expanded: set[str] = set()
    for alias in aliases:
        expanded.update(self._expand_allowed_tool_name(alias, seen))
    return expanded
```

and make `_normalize_allowed_tools()` call this helper for every raw name.

- [ ] **Step 6: Implement `session_status` executor**

Create `app/tools/session_status.py`:

```python
from app.schemas.agent_action import Observation
from app.tools.arguments import SessionStatusArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def session_status(args: SessionStatusArgs, context: ToolExecutionContext) -> Observation:
    payload: dict[str, object] = {
        "repo_path": str(context.settings.project_root),
        "workspace_path": str(context.workspace_path),
        "permission_mode": context.permission_mode,
        "verification_commands": context.verification_commands,
        "pending_confirmation": context.pending_confirmation,
        "last_trace_path": context.trace_path,
        "run_id": context.run_id,
    }
    if args.include_tools:
        payload["allowed_tools"] = sorted(context.allowed_tools or [])
        payload["available_tools"] = sorted(context.available_tools or [])
        payload["denied_tools"] = sorted(context.denied_tools)
    if args.include_recent_steps:
        payload["recent_steps"] = context.recent_steps[-10:]
    return tool_observation(
        tool_name="session_status",
        status="succeeded",
        summary="Read session status",
        payload=payload,
    )
```

- [ ] **Step 7: Register `session_status`**

In `app/tools/registry.py`:

1. Import `SessionStatusArgs`.
2. Import `session_status`.
3. Add this `ToolSpec` before `tool_search`:

```python
ToolSpec(
    name="session_status",
    description="Read current run, permission, visible tools, verification, and recent tool-step state.",
    args_model=SessionStatusArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=session_status,
),
```

- [ ] **Step 8: Pass richer context from compatibility helper**

In `app/agent/loop.py`, update `_tool_execution_context()` signature and return value:

```python
def _tool_execution_context(
    *,
    repo_path: Path,
    settings: Settings,
    verification_commands: list[str],
    available_tools: set[str] | None = None,
    permission_mode: PermissionMode | None = None,
    allowed_tools: set[str] | None = None,
    run_id: str | None = None,
    trace_path: str | None = None,
    recent_steps: list[dict[str, object]] | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        workspace_path=repo_path,
        settings=settings,
        verification_commands=verification_commands,
        available_tools=available_tools,
        permission_mode=permission_mode,
        allowed_tools=allowed_tools,
        run_id=run_id,
        trace_path=trace_path,
        recent_steps=recent_steps or [],
    )
```

Update `_execute_tool_invocation()` calls to pass `permission_mode` and `allowed_tools` where available.

- [ ] **Step 9: Run focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_registry.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/tools app/agent/loop.py tests/unit/test_tool_registry.py
```

Expected: all pass.

- [ ] **Step 10: Add scenario for tool visibility**

Add a test to `tests/scenarios/test_tui_repository_inspection_scenarios.py`:

```python
async def test_tool_visibility_question_uses_session_status(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="tool visibility",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["现在你能用哪些工具"],
            tool_steps=[
                ScenarioToolStep(
                    action="session_status",
                    status="succeeded",
                    summary="Read session status",
                    payload={
                        "permission_mode": "guided",
                        "available_tools": ["read_file", "list_dir", "session_status"],
                        "verification_commands": [],
                    },
                    args={"include_tools": True},
                )
            ],
            final_summary="当前可用工具包括 read_file、list_dir、session_status。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "session_status")
    assert_visible_answer_contains(transcript, "read_file")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)
```

- [ ] **Step 11: Commit Task 1**

Run:

```bash
git add app/tools/arguments.py app/tools/structured.py app/tools/session_status.py app/tools/registry.py app/agent/loop.py tests/unit/test_tool_registry.py tests/scenarios/test_tui_repository_inspection_scenarios.py
git commit -m "add session status tool and tool groups"
```

## Task 2: Repeated Tool-Call Detection

**Files:**
- Create: `app/runtime/tool_repetition.py`
- Modify: `app/runtime/agent_loop.py`
- Test: `tests/unit/test_tool_repetition.py`
- Test: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: Write failing unit tests for fingerprints**

Create `tests/unit/test_tool_repetition.py`:

```python
from pathlib import Path

from app.runtime.tool_repetition import RepetitionTracker, tool_call_fingerprint
from app.schemas.agent_action import Observation
from app.tools.structured import ToolInvocation


def invocation(name: str, args: dict[str, object]) -> ToolInvocation:
    return ToolInvocation(id="call", name=name, args=args, source="openai_tool_call")


def test_read_file_fingerprint_normalizes_path_and_args(tmp_path: Path) -> None:
    workspace = tmp_path.resolve()

    left = tool_call_fingerprint(
        invocation("read_file", {"path": "./README.md", "max_chars": 12000}),
        workspace,
    )
    right = tool_call_fingerprint(
        invocation("read_file", {"max_chars": 12000, "path": "README.md"}),
        workspace,
    )

    assert left == right


def test_repetition_tracker_rejects_third_equivalent_call(tmp_path: Path) -> None:
    tracker = RepetitionTracker(max_equivalent_calls=2)
    call = invocation("read_file", {"path": "README.md"})

    assert tracker.rejection_for(call, tmp_path, next_step_index=1) is None
    tracker.record(call, tmp_path, step_index=1, observation=Observation(status="succeeded", summary="Read", payload={}))
    assert tracker.rejection_for(call, tmp_path, next_step_index=2) is None
    tracker.record(call, tmp_path, step_index=2, observation=Observation(status="succeeded", summary="Read", payload={}))

    rejected = tracker.rejection_for(call, tmp_path, next_step_index=3)

    assert rejected is not None
    assert rejected.status == "rejected"
    assert rejected.payload["repeat_count"] == 3
    assert rejected.payload["previous_step"] == 2


def test_repetition_tracker_allows_different_line_ranges(tmp_path: Path) -> None:
    tracker = RepetitionTracker(max_equivalent_calls=2)
    first = invocation("read_file", {"path": "README.md", "start_line": 1, "end_line": 5})
    second = invocation("read_file", {"path": "README.md", "start_line": 6, "end_line": 10})

    tracker.record(first, tmp_path, step_index=1, observation=Observation(status="succeeded", summary="Read", payload={}))

    assert tracker.rejection_for(second, tmp_path, next_step_index=2) is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_repetition.py -q
```

Expected: import failure because `app.runtime.tool_repetition` does not exist.

- [ ] **Step 3: Implement `tool_repetition.py`**

Create `app/runtime/tool_repetition.py`:

```python
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.agent_action import Observation
from app.tools.structured import ToolInvocation

REPEAT_GUARDED_TOOLS = {
    "read_file",
    "list_dir",
    "glob_file_search",
    "rg",
    "search_code",
    "git",
    "repo_status",
    "show_diff",
    "detect_project",
    "session_status",
}


def _normalize_path(value: str, workspace_path: Path) -> str:
    candidate = Path(value)
    resolved = candidate if candidate.is_absolute() else workspace_path / candidate
    try:
        return str(resolved.resolve().relative_to(workspace_path.resolve()))
    except ValueError:
        return str(value)


def _normalize_args(args: dict[str, Any], workspace_path: Path) -> dict[str, Any]:
    normalized = dict(args)
    for key in ("path", "relative_path"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = _normalize_path(value, workspace_path)
    return normalized


def tool_call_fingerprint(invocation: ToolInvocation, workspace_path: Path) -> str:
    normalized = _normalize_args(invocation.args, workspace_path)
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{invocation.name}:{workspace_path.resolve()}:{encoded}"


@dataclass
class _SeenCall:
    count: int
    last_step_index: int


class RepetitionTracker:
    def __init__(self, *, max_equivalent_calls: int = 2) -> None:
        self.max_equivalent_calls = max_equivalent_calls
        self._seen: dict[str, _SeenCall] = {}

    def rejection_for(
        self,
        invocation: ToolInvocation,
        workspace_path: Path,
        *,
        next_step_index: int,
    ) -> Observation | None:
        if invocation.name not in REPEAT_GUARDED_TOOLS:
            return None
        fingerprint = tool_call_fingerprint(invocation, workspace_path)
        seen = self._seen.get(fingerprint)
        if seen is None or seen.count < self.max_equivalent_calls:
            return None
        return Observation(
            status="rejected",
            summary="Repeated equivalent tool call",
            payload={
                "tool_name": invocation.name,
                "repeat_count": seen.count + 1,
                "previous_step": seen.last_step_index,
                "current_step": next_step_index,
                "suggestion": "Use the previous observation or call final_response.",
            },
            error_message="equivalent tool call repeated too many times",
        )

    def record(
        self,
        invocation: ToolInvocation,
        workspace_path: Path,
        *,
        step_index: int,
        observation: Observation,
    ) -> None:
        if invocation.name not in REPEAT_GUARDED_TOOLS:
            return
        if observation.status not in {"succeeded", "rejected"}:
            return
        fingerprint = tool_call_fingerprint(invocation, workspace_path)
        seen = self._seen.get(fingerprint)
        if seen is None:
            self._seen[fingerprint] = _SeenCall(count=1, last_step_index=step_index)
            return
        seen.count += 1
        seen.last_step_index = step_index
```

- [ ] **Step 4: Integrate tracker in provider tool-call loop**

In `app/runtime/agent_loop.py`:

1. Import `RepetitionTracker`.
2. Instantiate after `observation_history`:

```python
repetition_tracker = RepetitionTracker()
```

3. Before `_handle_tool_invocation()`, check for rejection:

```python
repeat_observation = repetition_tracker.rejection_for(
    invocation,
    workspace_path,
    next_step_index=index,
)
if repeat_observation is not None:
    handled = _handled_tool_rejection(index, invocation, repeat_observation)
else:
    handled = _handle_tool_invocation(...)
```

Do not stop the loop for repeated-call rejection. Record a normal tool-call-like step and let the provider see the rejection by adding this helper:

```python
def _handled_tool_rejection(index: int, invocation: ToolInvocation, observation: Observation) -> _HandledAction:
    return _HandledAction(
        stop=False,
        status="running",
        summary=observation.summary,
        step=AgentStep(
            index=index,
            action=ToolCallAction(
                type="tool_call",
                action=invocation.name,
                reason="rejected repeated equivalent tool call",
                args=invocation.args,
            ),
            observation=observation,
        ),
    )
```

Import `ToolCallAction` from `app.schemas.agent_action`.

4. After `record_handled_action()`, call:

```python
repetition_tracker.record(
    invocation,
    workspace_path,
    step_index=handled.step.index,
    observation=handled.step.observation,
)
```

- [ ] **Step 5: Add AgentLoop regression**

Add to `tests/unit/test_agent_loop.py`:

```python
class RepeatingReadProvider:
    def __init__(self) -> None:
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        if len(self.calls) <= 3:
            return ProviderResponse(
                status="succeeded",
                tool_invocations=[
                    ToolInvocation(
                        id=f"call_read_{len(self.calls)}",
                        name="read_file",
                        args={"path": "README.md"},
                        source="openai_tool_call",
                    )
                ],
            )
        return ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": "failed",
                    "summary": "stopped after repeated call rejection",
                }
            ],
        )


def test_agent_loop_returns_repeated_tool_rejection_to_provider(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    provider = RepeatingReadProvider()

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="read repeatedly",
            provider=provider,
            allowed_tools={"read_file"},
            step_budget=5,
        ),
        settings_for(tmp_path),
    )

    assert len(provider.calls) == 4
    assert result.steps[2].observation.status == "rejected"
    assert result.steps[2].observation.summary == "Repeated equivalent tool call"
    assert provider.calls[3].observations[-1].observation.error_message == (
        "equivalent tool call repeated too many times"
    )
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_repetition.py tests/unit/test_agent_loop.py::test_agent_loop_returns_repeated_tool_rejection_to_provider -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/runtime/tool_repetition.py app/runtime/agent_loop.py tests/unit/test_tool_repetition.py tests/unit/test_agent_loop.py
```

Expected: pass.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add app/runtime/tool_repetition.py app/runtime/agent_loop.py tests/unit/test_tool_repetition.py tests/unit/test_agent_loop.py
git commit -m "detect repeated schema tool calls"
```

## Task 3: Background Process Tools

**Files:**
- Create: `app/runtime/process_registry.py`
- Create: `app/tools/process_tools.py`
- Modify: `app/tools/arguments.py`
- Modify: `app/tools/registry.py`
- Modify: `app/tools/structured.py`
- Test: `tests/unit/test_process_registry.py`
- Test: `tests/unit/test_tool_registry.py`

- [ ] **Step 1: Write failing process registry tests**

Create `tests/unit/test_process_registry.py`:

```python
import sys
import time
from pathlib import Path

from app.runtime.process_registry import ProcessRegistry


def test_process_registry_starts_and_polls_output(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")

    started = registry.start(
        command=f"{sys.executable} -c \"print('hello')\"",
        cwd=tmp_path,
        name="hello",
        pty=False,
    )
    time.sleep(0.5)
    polled = registry.poll(started.process_id, max_chars=2000)

    assert polled.status in {"running", "exited"}
    assert "hello" in polled.stdout_excerpt


def test_process_registry_stops_running_process(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")
    started = registry.start(
        command=f"{sys.executable} -c \"import time; time.sleep(30)\"",
        cwd=tmp_path,
        name="sleep",
        pty=False,
    )

    stopped = registry.stop(started.process_id, signal="term")

    assert stopped.status in {"stopped", "exited"}


def test_process_registry_rejects_unknown_process(tmp_path: Path) -> None:
    registry = ProcessRegistry(log_dir=tmp_path / "processes")

    result = registry.poll("missing", max_chars=2000)

    assert result.status == "missing"
    assert result.error_message == "unknown process_id: missing"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_process_registry.py -q
```

Expected: import failure.

- [ ] **Step 3: Add process argument models**

In `app/tools/arguments.py`, add:

```python
class ProcessStartArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: str = Field(min_length=1)
    cwd: str = "."
    name: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    pty: bool = False
    background: bool = True


class ProcessPollArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1)
    offset: int | None = Field(default=None, ge=0)
    max_chars: int = Field(default=12000, ge=0)


class ProcessWriteArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1)
    input: str


class ProcessStopArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_id: str = Field(min_length=1)
    signal: Literal["term", "kill"] = "term"
```

- [ ] **Step 4: Implement process registry**

Create `app/runtime/process_registry.py`:

```python
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class ProcessSnapshot:
    process_id: str
    command: str
    cwd: str
    status: str
    exit_code: int | None
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_offset: int
    stderr_offset: int
    stdout_log_path: str
    stderr_log_path: str
    error_message: str | None = None


@dataclass
class _ProcessEntry:
    process_id: str
    command: str
    cwd: Path
    process: subprocess.Popen[str]
    stdout_log_path: Path
    stderr_log_path: Path
    started_at: float
    stopped: bool = False


class ProcessRegistry:
    def __init__(self, *, log_dir: Path) -> None:
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._entries: dict[str, _ProcessEntry] = {}

    def start(self, *, command: str, cwd: Path, name: str | None = None, pty: bool = False) -> ProcessSnapshot:
        process_id = f"proc-{uuid4().hex[:12]}"
        safe_name = name or process_id
        stdout_log = self.log_dir / f"{process_id}-{safe_name}.stdout.log"
        stderr_log = self.log_dir / f"{process_id}-{safe_name}.stderr.log"
        stdout_handle = stdout_log.open("w", encoding="utf-8")
        stderr_handle = stderr_log.open("w", encoding="utf-8")
        process = subprocess.Popen(
            command,
            cwd=cwd,
            shell=True,
            text=True,
            stdout=stdout_handle,
            stderr=stderr_handle,
            stdin=subprocess.PIPE,
        )
        stdout_handle.close()
        stderr_handle.close()
        entry = _ProcessEntry(
            process_id=process_id,
            command=command,
            cwd=cwd,
            process=process,
            stdout_log_path=stdout_log,
            stderr_log_path=stderr_log,
            started_at=time.time(),
        )
        self._entries[process_id] = entry
        return self._snapshot(entry, max_chars=2000)

    def poll(self, process_id: str, *, max_chars: int, offset: int | None = None) -> ProcessSnapshot:
        entry = self._entries.get(process_id)
        if entry is None:
            return self._missing(process_id)
        return self._snapshot(entry, max_chars=max_chars, offset=offset)

    def list(self) -> list[ProcessSnapshot]:
        return [self._snapshot(entry, max_chars=1000) for entry in self._entries.values()]

    def write(self, process_id: str, input_text: str) -> ProcessSnapshot:
        entry = self._entries.get(process_id)
        if entry is None:
            return self._missing(process_id)
        if entry.process.stdin is None:
            return self._snapshot(entry, max_chars=2000, error_message="process stdin is unavailable")
        entry.process.stdin.write(input_text)
        entry.process.stdin.flush()
        return self._snapshot(entry, max_chars=2000)

    def stop(self, process_id: str, *, signal: str) -> ProcessSnapshot:
        entry = self._entries.get(process_id)
        if entry is None:
            return self._missing(process_id)
        if entry.process.poll() is None:
            if signal == "kill":
                entry.process.kill()
            else:
                entry.process.terminate()
            try:
                entry.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                entry.process.kill()
                entry.process.wait(timeout=5)
            entry.stopped = True
        return self._snapshot(entry, max_chars=2000)

    def _snapshot(
        self,
        entry: _ProcessEntry,
        *,
        max_chars: int,
        offset: int | None = None,
        error_message: str | None = None,
    ) -> ProcessSnapshot:
        exit_code = entry.process.poll()
        if entry.stopped:
            status = "stopped"
        elif exit_code is None:
            status = "running"
        else:
            status = "exited"
        stdout_excerpt, stdout_offset = _read_excerpt(entry.stdout_log_path, max_chars=max_chars, offset=offset)
        stderr_excerpt, stderr_offset = _read_excerpt(entry.stderr_log_path, max_chars=max_chars, offset=offset)
        return ProcessSnapshot(
            process_id=entry.process_id,
            command=entry.command,
            cwd=str(entry.cwd),
            status=status,
            exit_code=exit_code,
            stdout_excerpt=stdout_excerpt,
            stderr_excerpt=stderr_excerpt,
            stdout_offset=stdout_offset,
            stderr_offset=stderr_offset,
            stdout_log_path=str(entry.stdout_log_path),
            stderr_log_path=str(entry.stderr_log_path),
            error_message=error_message,
        )

    def _missing(self, process_id: str) -> ProcessSnapshot:
        return ProcessSnapshot(
            process_id=process_id,
            command="",
            cwd="",
            status="missing",
            exit_code=None,
            stdout_excerpt="",
            stderr_excerpt="",
            stdout_offset=0,
            stderr_offset=0,
            stdout_log_path="",
            stderr_log_path="",
            error_message=f"unknown process_id: {process_id}",
        )


def _read_excerpt(path: Path, *, max_chars: int, offset: int | None) -> tuple[str, int]:
    if not path.exists():
        return "", 0
    text = path.read_text(encoding="utf-8", errors="replace")
    start = offset or 0
    excerpt = text[start : start + max_chars]
    return excerpt, start + len(excerpt)
```

- [ ] **Step 5: Add process registry to `ToolExecutionContext`**

In `app/tools/structured.py`, add:

```python
process_registry: Any | None = None
```

The file already imports `Any`; if not, import it from `typing`.

- [ ] **Step 6: Implement process tool executors**

Create `app/tools/process_tools.py`:

```python
from pathlib import Path

from app.runtime.process_registry import ProcessRegistry, ProcessSnapshot
from app.schemas.agent_action import Observation
from app.tools.arguments import (
    EmptyToolArgs,
    ProcessPollArgs,
    ProcessStartArgs,
    ProcessStopArgs,
    ProcessWriteArgs,
)
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext
from app.workspace.shell_policy import ShellPolicy


def _registry(context: ToolExecutionContext) -> ProcessRegistry:
    if context.process_registry is not None:
        return context.process_registry
    return ProcessRegistry(log_dir=context.settings.data_dir / "processes")


def _snapshot_observation(tool_name: str, snapshot: ProcessSnapshot) -> Observation:
    status = "rejected" if snapshot.status == "missing" else "succeeded"
    return tool_observation(
        tool_name=tool_name,
        status=status,
        summary=f"{tool_name}: {snapshot.status}",
        payload=snapshot.__dict__,
        error_message=snapshot.error_message,
        stdout_excerpt=snapshot.stdout_excerpt,
        stderr_excerpt=snapshot.stderr_excerpt,
    )


def process_start(args: ProcessStartArgs, context: ToolExecutionContext) -> Observation:
    cwd = (context.workspace_path / args.cwd).resolve()
    try:
        cwd.relative_to(context.workspace_path.resolve())
    except ValueError:
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Unable to start process",
            payload={"cwd": args.cwd},
            error_message="cwd escapes workspace root",
        )
    policy = ShellPolicy(
        allowed_root=context.workspace_path,
        timeout_seconds=context.settings.verification_timeout_seconds,
    )
    decision = policy.evaluate(args.command, cwd=cwd)
    if not decision.allowed:
        return tool_observation(
            tool_name="process_start",
            status="rejected",
            summary="Process command requires confirmation or is denied",
            payload={
                "command": args.command,
                "cwd": str(cwd),
                "risk_level": decision.risk_level,
                "reason": decision.reason,
            },
            error_message=decision.reason,
        )
    snapshot = _registry(context).start(command=args.command, cwd=cwd, name=args.name, pty=args.pty)
    return _snapshot_observation("process_start", snapshot)


def process_poll(args: ProcessPollArgs, context: ToolExecutionContext) -> Observation:
    snapshot = _registry(context).poll(args.process_id, max_chars=args.max_chars, offset=args.offset)
    return _snapshot_observation("process_poll", snapshot)


def process_write(args: ProcessWriteArgs, context: ToolExecutionContext) -> Observation:
    snapshot = _registry(context).write(args.process_id, args.input)
    return _snapshot_observation("process_write", snapshot)


def process_stop(args: ProcessStopArgs, context: ToolExecutionContext) -> Observation:
    snapshot = _registry(context).stop(args.process_id, signal=args.signal)
    return _snapshot_observation("process_stop", snapshot)


def process_list(args: EmptyToolArgs, context: ToolExecutionContext) -> Observation:
    snapshots = [snapshot.__dict__ for snapshot in _registry(context).list()]
    return tool_observation(
        tool_name="process_list",
        status="succeeded",
        summary=f"Listed {len(snapshots)} processes",
        payload={"processes": snapshots, "process_count": len(snapshots)},
    )
```

- [ ] **Step 7: Register process tools**

In `app/tools/registry.py`, import process args and executors, then add these specs:

```python
ToolSpec(
    name="process_start",
    description="Start a background process through shell policy and return process metadata.",
    args_model=ProcessStartArgs,
    risk_level=ToolRisk.SHELL_RESTRICTED,
    executor=process_start,
),
ToolSpec(
    name="process_poll",
    description="Poll a background process and return incremental stdout/stderr excerpts.",
    args_model=ProcessPollArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=process_poll,
),
ToolSpec(
    name="process_write",
    description="Write input to a background process owned by this session.",
    args_model=ProcessWriteArgs,
    risk_level=ToolRisk.SHELL_RESTRICTED,
    executor=process_write,
),
ToolSpec(
    name="process_stop",
    description="Stop a background process owned by this session.",
    args_model=ProcessStopArgs,
    risk_level=ToolRisk.SHELL_RESTRICTED,
    executor=process_stop,
),
ToolSpec(
    name="process_list",
    description="List background processes known to this session.",
    args_model=EmptyToolArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=process_list,
),
```

- [ ] **Step 8: Pass a per-run process registry in AgentLoop**

In `app/runtime/agent_loop.py`:

1. Import `ProcessRegistry`.
2. After `run_id`, create:

```python
process_registry = ProcessRegistry(log_dir=settings.data_dir / "processes" / run_id)
```

3. Extend `app/agent/loop.py` `_handle_tool_invocation()` and `_execute_tool_invocation()` with `process_registry: Any | None = None`, pass it into `_tool_execution_context(process_registry=process_registry)`, then update every `_handle_tool_invocation()` call site in `app/runtime/agent_loop.py` to pass the per-run registry.

- [ ] **Step 9: Run focused process tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_process_registry.py tests/unit/test_tool_registry.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/runtime/process_registry.py app/tools/process_tools.py app/tools/arguments.py app/tools/registry.py app/tools/structured.py tests/unit/test_process_registry.py
```

Expected: pass.

- [ ] **Step 10: Commit Task 3**

Run:

```bash
git add app/runtime/process_registry.py app/tools/process_tools.py app/tools/arguments.py app/tools/registry.py app/tools/structured.py app/runtime/agent_loop.py app/agent/loop.py tests/unit/test_process_registry.py tests/unit/test_tool_registry.py
git commit -m "add background process tools"
```

## Task 4: Minimal LSP Tool

**Files:**
- Create: `app/runtime/lsp_client.py`
- Create: `app/tools/lsp_tool.py`
- Modify: `app/tools/arguments.py`
- Modify: `app/tools/registry.py`
- Test: `tests/unit/test_lsp_tool.py`
- Test: `tests/unit/test_tool_registry.py`

- [ ] **Step 1: Write failing LSP tests**

Create `tests/unit/test_lsp_tool.py`:

```python
from pathlib import Path

from app.config.settings import Settings
from app.tools.arguments import LspArgs
from app.tools.lsp_tool import lsp
from app.tools.structured import ToolExecutionContext


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


def test_lsp_unavailable_server_returns_rejected(tmp_path: Path) -> None:
    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    )

    observation = lsp(
        LspArgs(operation="definition", path="app.py", line=1, column=1),
        context,
    )

    assert observation.status == "rejected"
    assert "language server unavailable" in str(observation.error_message)
    assert observation.payload["operation"] == "definition"


def test_lsp_diagnostics_with_fake_client(tmp_path: Path) -> None:
    class FakeLspClient:
        def request(self, args: LspArgs, workspace_path: Path) -> dict[str, object]:
            return {
                "operation": args.operation,
                "results": [
                    {
                        "relative_path": "app.py",
                        "start_line": 1,
                        "message": "example diagnostic",
                    }
                ],
                "truncated": False,
            }

    context = ToolExecutionContext(
        workspace_path=tmp_path,
        settings=settings_for(tmp_path),
        verification_commands=[],
    ).model_copy(update={"lsp_client": FakeLspClient()})

    observation = lsp(LspArgs(operation="diagnostics", path="app.py"), context)

    assert observation.status == "succeeded"
    assert observation.payload["operation"] == "diagnostics"
    assert observation.payload["results"][0]["message"] == "example diagnostic"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_lsp_tool.py -q
```

Expected: import failure.

- [ ] **Step 3: Add `LspArgs`**

In `app/tools/arguments.py`, add:

```python
class LspArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal[
        "diagnostics",
        "definition",
        "references",
        "hover",
        "document_symbols",
        "workspace_symbols",
        "implementations",
    ]
    path: str | None = None
    line: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    query: str | None = None
    max_results: int = Field(default=50, ge=1, le=500)
```

- [ ] **Step 4: Add `lsp_client` to context**

In `app/tools/structured.py`, add:

```python
lsp_client: Any | None = None
```

- [ ] **Step 5: Implement minimal LSP client**

Create `app/runtime/lsp_client.py`:

```python
import shutil
from pathlib import Path

from app.tools.arguments import LspArgs


class LanguageServerUnavailable(RuntimeError):
    pass


class LspClientManager:
    def request(self, args: LspArgs, workspace_path: Path) -> dict[str, object]:
        server = self._server_for(args.path)
        if server is None:
            raise LanguageServerUnavailable("language server unavailable")
        raise LanguageServerUnavailable(
            "language server transport is unavailable in this environment"
        )

    def _server_for(self, path: str | None) -> str | None:
        if path is None:
            return None
        suffix = Path(path).suffix
        candidates: list[str] = []
        if suffix == ".py":
            candidates = ["pyright-langserver", "basedpyright-langserver"]
        elif suffix in {".ts", ".tsx", ".js", ".jsx"}:
            candidates = ["typescript-language-server"]
        for candidate in candidates:
            if shutil.which(candidate):
                return candidate
        return None
```

This first task intentionally implements unavailable-server behavior plus fake-client injection. Real JSON-RPC transport can be added in the next plan if the dependency and lifecycle are approved.

- [ ] **Step 6: Implement LSP tool executor**

Create `app/tools/lsp_tool.py`:

```python
from app.runtime.lsp_client import LanguageServerUnavailable, LspClientManager
from app.schemas.agent_action import Observation
from app.tools.arguments import LspArgs
from app.tools.observations import tool_observation
from app.tools.structured import ToolExecutionContext


def lsp(args: LspArgs, context: ToolExecutionContext) -> Observation:
    client = context.lsp_client or LspClientManager()
    try:
        payload = client.request(args, context.workspace_path)
    except LanguageServerUnavailable as exc:
        return tool_observation(
            tool_name="lsp",
            status="rejected",
            summary="Language server unavailable",
            payload=args.model_dump(mode="json"),
            error_message=str(exc),
        )
    return tool_observation(
        tool_name="lsp",
        status="succeeded",
        summary=f"LSP {args.operation}",
        payload=payload,
    )
```

- [ ] **Step 7: Register `lsp`**

In `app/tools/registry.py`, import `LspArgs` and `lsp`, then add:

```python
ToolSpec(
    name="lsp",
    description="Use language-server facts for diagnostics, definitions, references, hover, and symbols.",
    args_model=LspArgs,
    risk_level=ToolRisk.READ_ONLY,
    executor=lsp,
),
```

- [ ] **Step 8: Add schema test**

Add to `tests/unit/test_tool_registry.py`:

```python
def test_default_registry_contains_lsp_tool() -> None:
    registry = default_tool_registry()

    assert "lsp" in registry.names()
    schema = next(tool for tool in registry.openai_tools() if tool["function"]["name"] == "lsp")
    assert "operation" in schema["function"]["parameters"]["properties"]
```

- [ ] **Step 9: Run focused LSP tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_lsp_tool.py tests/unit/test_tool_registry.py::test_default_registry_contains_lsp_tool -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/runtime/lsp_client.py app/tools/lsp_tool.py app/tools/arguments.py app/tools/registry.py tests/unit/test_lsp_tool.py
```

Expected: pass.

- [ ] **Step 10: Commit Task 4**

Run:

```bash
git add app/runtime/lsp_client.py app/tools/lsp_tool.py app/tools/arguments.py app/tools/registry.py app/tools/structured.py tests/unit/test_lsp_tool.py tests/unit/test_tool_registry.py
git commit -m "add minimal lsp tool"
```

## Task 5: TUI and Scenario Coverage

**Files:**
- Modify: `app/tui/app.py`
- Modify: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Modify: `tests/e2e/test_tui_pty_live.py`

- [ ] **Step 1: Include new tools in TUI read-only agent surface**

In `app/tui/app.py`, update `READ_ONLY_TOOL_AGENT_TOOLS` to include:

```python
READ_ONLY_TOOL_AGENT_TOOLS = {
    "glob_file_search",
    "git",
    "list_dir",
    "lsp",
    "read_file",
    "rg",
    "search_code",
    "session_status",
    "tool_search",
}
```

Do not include process tools in the default read-only TUI surface. They belong in wider `coding_agent` or explicit future profile usage.

- [ ] **Step 2: Add scenario for LSP fallback evidence**

Add to `tests/scenarios/test_tui_repository_inspection_scenarios.py`:

```python
async def test_symbol_definition_question_uses_lsp_or_explicit_fallback(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="symbol definition",
            repo_files={"app/main.py": "def target():\n    return 1\n"},
            user_inputs=["target 函数在哪里定义"],
            tool_steps=[
                ScenarioToolStep(
                    action="lsp",
                    status="rejected",
                    summary="Language server unavailable",
                    payload={
                        "operation": "definition",
                        "path": "app/main.py",
                        "line": 1,
                        "column": 5,
                    },
                    error_message="language server unavailable",
                    args={
                        "operation": "definition",
                        "path": "app/main.py",
                        "line": 1,
                        "column": 5,
                    },
                ),
                ScenarioToolStep(
                    action="rg",
                    status="succeeded",
                    summary="Searched target",
                    payload={
                        "query": "target",
                        "matches": [
                            {
                                "relative_path": "app/main.py",
                                "line_number": 1,
                                "line_text": "def target():",
                            }
                        ],
                    },
                    args={"query": "target"},
                ),
            ],
            final_summary="target 定义在 app/main.py 第 1 行。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_evidence_from_any_observation(transcript, ("lsp", "rg"))
    assert_visible_answer_contains(transcript, "app/main.py")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)
```

- [ ] **Step 3: Add PTY live test for session status**

Add to `tests/e2e/test_tui_pty_live.py`:

```python
def test_live_tui_reports_available_tools_with_session_status(live_repo: Path) -> None:
    result = run_live_tui_question(
        live_repo,
        "现在你能用哪些工具",
        timeout_seconds=90,
    )

    assert_no_provider_failure_or_trace_exposed(result)
    assert_schema_tool_call_route(result)
    assert_conversation_has_tool_evidence(result, "session_status", "tool_search")
    assert_response_evidence_contains(result, "read_file")
```

- [ ] **Step 4: Run scenario and PTY focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/scenarios/test_tui_repository_inspection_scenarios.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py::test_live_tui_reports_available_tools_with_session_status -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check app/tui/app.py tests/scenarios/test_tui_repository_inspection_scenarios.py tests/e2e/test_tui_pty_live.py
```

Expected: pass when provider env is configured for PTY.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add app/tui/app.py tests/scenarios/test_tui_repository_inspection_scenarios.py tests/e2e/test_tui_pty_live.py
git commit -m "cover expanded tools in tui scenarios"
```

## Task 6: Documentation and Final Regression

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_问题记录.md`

- [ ] **Step 1: Update README tool list**

In `README.md`, add the new first-slice tools to the current state/tool section:

```markdown
- 新增工具池扩展方向包括 `session_status`、后台 `process_*`、基础 `lsp` 和重复工具调用保护。
```

If process/LSP are implemented in the same branch, list them in the structured tool sentence.

- [ ] **Step 2: Update development plan**

In `MendCode_开发方案.md`, update `3.3 ToolRegistry`:

```markdown
| `session_status` | 已完成 | 返回当前权限、可见工具、验证命令、trace 和近期步骤 |
| `process_start` / `process_poll` / `process_write` / `process_stop` / `process_list` | 已完成 | 管理本轮后台进程和增量日志 |
| `lsp` | 已完成 | 返回语言服务诊断、定义、引用等结构化结果；不可用时明确 rejected |
```

Add a note under AgentLoop:

```markdown
- [x] 重复等价只读工具调用检测，第三次重复调用返回结构化 rejected observation。
```

- [ ] **Step 3: Update problem record**

Add a new issue to `MendCode_问题记录.md`:

```markdown
### 问题：模型重复读取同一事实会浪费上下文

状态：已修复基础路径

现象：

模型在已经拿到文件内容、目录结果或搜索结果后，仍可能连续调用等价工具，导致 step budget 和上下文被工具过程占满。

根因：

AgentLoop 只按 step budget 限制总次数，没有识别“同一个工具 + 同一组语义参数”的重复调用。

处理：

AgentLoop 增加重复工具调用指纹，对 read-only 工具的第三次等价调用返回 rejected observation，提醒模型使用已有 observation 或收尾。

后续约束：

新增只读工具时要判断是否加入重复检测集合；写工具只有在幂等语义明确后才能加入。
```

- [ ] **Step 4: Run full verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected: all pass. If PTY provider env is missing, record the exact missing variables and do not claim PTY success.

- [ ] **Step 5: Commit Task 6**

Run:

```bash
git add README.md MendCode_开发方案.md MendCode_问题记录.md
git commit -m "document expanded tool pool"
```

## Final Self-Review Checklist

- [ ] `session_status` is visible in read-only pool and returns no secrets.
- [ ] `ToolRegistry.names()` supports existing aliases, new groups, and profiles.
- [ ] `tool_search` sees only final visible tools.
- [ ] repeated third equivalent read-only tool call returns a structured rejection and does not execute again.
- [ ] process logs are bounded in observation payloads and full logs live under `data/`.
- [ ] process start uses `ShellPolicy`; write/network/install/destructive commands are not auto-run.
- [ ] LSP unavailable behavior is explicit and does not install anything.
- [ ] TUI normal text still goes through schema tool calls.
- [ ] Conversation logs do not expose `trace_path` in visible TUI messages.
- [ ] Full pytest, ruff, and PTY live commands have been run after the final commit.
