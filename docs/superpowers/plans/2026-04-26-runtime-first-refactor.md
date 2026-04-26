# Runtime-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor MendCode around a reusable local Agent runtime where ToolRegistry, PermissionPolicy, session context, and TUI all share one execution path.

**Architecture:** ToolRegistry is the only source of provider-visible tools and tool executors. PermissionPolicy authorizes tool calls before execution. The TUI becomes a thin controller/display layer over the runtime.

**Tech Stack:** Python 3.12, Pydantic, Textual, OpenAI-compatible chat completions, pytest, ruff.

---

## File Structure

- Modify: `app/tools/arguments.py` for shared tool argument models.
- Modify: `app/tools/registry.py` to host all built-in tool specs and executors.
- Modify: `app/tools/structured.py` for canonical aliases and registry helpers.
- Modify: `app/agent/loop.py` until it becomes a wrapper around runtime.
- Modify: `app/agent/permission.py` during transition; later move policy into `app/permissions/policy.py`.
- Create: `app/runtime/agent_runtime.py` for the new runtime loop.
- Create: `app/runtime/turn.py` for turn and tool summary models.
- Create: `app/runtime/session_store.py` for session index and resume.
- Create: `app/permissions/policy.py` for target permission modes.
- Create: `app/tui/controller.py` for TUI-to-runtime orchestration.
- Test: `tests/unit/test_tool_registry.py`, `tests/unit/test_agent_loop.py`, `tests/unit/test_permission_gate.py`, `tests/unit/test_tui_app.py`, and new runtime/session tests.

## Task 1: Registry-Owns Read-Only Builtins

**Files:**
- Modify: `app/tools/arguments.py`
- Modify: `app/tools/registry.py`
- Modify: `app/tools/structured.py`
- Modify: `app/agent/permission.py`
- Modify: `app/agent/loop.py`
- Test: `tests/unit/test_tool_registry.py`

- [x] **Step 1: Add empty args model**

Add `EmptyToolArgs` so no-argument tools still validate with `extra="forbid"`.

- [x] **Step 2: Move `repo_status`, `detect_project`, and `show_diff` into ToolRegistry**

Each tool returns the shared observation envelope and keeps the legacy payload fields duplicated at the top level for compatibility.

- [x] **Step 3: Add aliases**

Add aliases for `status -> repo_status`, `project -> detect_project`, and `diff -> show_diff`.

- [x] **Step 4: Remove these tools from the legacy risk map**

`app/agent/permission.py` should derive their risk from ToolRegistry.

- [x] **Step 5: Verify focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tool_registry.py tests/unit/test_permission_gate.py tests/unit/test_agent_loop.py tests/unit/test_openai_compatible_provider.py tests/unit/test_prompt_context.py
```

Expected: all tests pass.

## Task 2: PermissionPolicy Extraction

**Files:**
- Create: `app/permissions/__init__.py`
- Create: `app/permissions/policy.py`
- Modify: `app/agent/permission.py`
- Modify: `app/agent/loop.py`
- Test: `tests/unit/test_permission_gate.py`
- Test: `tests/unit/test_shell_policy.py`

- [x] **Step 1: Write failing tests for target modes**

Add tests that assert:

```python
def test_read_only_allows_read_tools_and_denies_write_tools():
    ...

def test_workspace_write_prompts_for_dangerous_shell():
    ...

def test_danger_full_access_allows_registered_tools():
    ...
```

- [x] **Step 2: Implement `PermissionPolicy`**

The object should accept `active_mode`, `tool_registry`, and optional rule lists. It should return a decision with `status`, `reason`, `risk_level`, and `required_mode`.

- [x] **Step 3: Keep transitional aliases**

Map old modes as:

```text
safe -> read-only
guided -> workspace-write
full -> danger-full-access
custom -> prompt/confirm by default
```

- [x] **Step 4: Route shell policy through PermissionPolicy**

`ShellPolicy.evaluate()` remains the shell classifier, but final allow/confirm/deny belongs to `PermissionPolicy`.

- [x] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_permission_gate.py tests/unit/test_shell_policy.py tests/unit/test_agent_loop.py
```

Expected: all tests pass.

## Task 3: AgentRuntime Wrapper

**Files:**
- Create: `app/runtime/__init__.py`
- Create: `app/runtime/turn.py`
- Create: `app/runtime/agent_runtime.py`
- Modify: `app/agent/loop.py`
- Modify: `app/agent/session.py`
- Test: `tests/unit/test_agent_loop.py`
- Test: `tests/unit/test_agent_session.py`

- [x] **Step 1: Add runtime turn models**

Define `RuntimeTurnInput`, `RuntimeTurnResult`, `RuntimeToolStep`, and `RuntimeStatus`.

- [x] **Step 2: Move provider loop into `AgentRuntime.run_turn()`**

Keep `run_agent_loop()` as a compatibility wrapper that constructs `AgentRuntime`.

Current slice: `run_agent_loop()` now constructs `AgentRuntime`; `AgentRuntime.run_turn()` delegates to the preserved internal implementation. The trace-stable implementation body remains as `_run_agent_loop_impl` while later slices split it into smaller runtime units.

- [x] **Step 3: Keep trace output stable**

Existing trace event names can remain during migration.

- [x] **Step 4: Run session tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_agent_loop.py tests/unit/test_agent_session.py tests/unit/test_agent_loop_tool_closure.py
```

Expected: all tests pass.

## Task 4: TUI Controller Split

**Files:**
- Create: `app/tui/controller.py`
- Modify: `app/tui/app.py`
- Test: `tests/unit/test_tui_app.py`
- Test: `tests/unit/test_tui_intent.py`

- [x] **Step 1: Move task dispatch out of Textual app**

Controller owns parsing routed intents, launching runtime turns, and returning display events.

Current slice: `TuiController` owns input parsing, task intent routing, pending reply checks, and dispatch to chat/shell/tool/fix starters. Worker execution and rendering remain in `MendCodeTextualApp` behind host methods.

- [x] **Step 2: Keep Textual app display-only**

`MendCodeTextualApp` should append messages, show pending confirmations, and call controller methods.

- [x] **Step 3: Preserve conversation logging**

Conversation log writes stay compact and include trace pointers.

- [x] **Step 4: Run TUI tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tui_app.py tests/unit/test_tui_chat.py tests/unit/test_tui_intent.py tests/unit/test_conversation_log.py
```

Expected: all tests pass.

## Task 5: Write/Edit/Todo/Tool Search

**Files:**
- Modify: `app/tools/arguments.py`
- Modify: `app/tools/registry.py`
- Create: `app/tools/builtin_write.py` if registry grows too large.
- Test: `tests/unit/test_tool_registry.py`
- Test: `tests/unit/test_permission_gate.py`

- [x] **Step 1: Add `write_file` and `edit_file` tests**

Cover workspace-relative writes, path escape rejection, exact replacement, and missing old text.

- [x] **Step 2: Add `todo_write` tests**

Cover replacing the current short task list and returning it to prompt context.

- [x] **Step 3: Add `tool_search` tests**

Cover searching tool names and descriptions, with max result limits.

- [x] **Step 4: Implement tools through ToolRegistry**

Each tool uses the shared observation envelope and required permission mode.

- [x] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tool_registry.py tests/unit/test_permission_gate.py tests/unit/test_agent_loop_tool_closure.py
```

Expected: all tests pass.

## Task 6: Session Resume And Viewer

**Files:**
- Create: `app/runtime/session_store.py`
- Modify: `app/tui/conversation_log.py`
- Modify: `app/tui/app.py`
- Test: `tests/unit/test_conversation_log.py`
- Test: new `tests/unit/test_session_store.py`

- [ ] **Step 1: Add session index tests**

Assert latest session lookup, list ordering, and missing-session errors.

- [ ] **Step 2: Implement session index**

Scan `data/conversations/*.jsonl`, read compact metadata, and expose latest/session-id lookup.

- [ ] **Step 3: Add resume compact context tests**

Assert resumed context includes final answers and compact tool summaries, not full trace payloads.

- [ ] **Step 4: Add trace viewer helper**

Given a trace path, return matching tool events with excerpts and full payload access.

- [ ] **Step 5: Run focused tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_conversation_log.py tests/unit/test_tui_app.py tests/unit/test_prompt_context.py
```

Expected: all tests pass.

## Final Verification

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: full suite and lint pass before committing each completed slice.
