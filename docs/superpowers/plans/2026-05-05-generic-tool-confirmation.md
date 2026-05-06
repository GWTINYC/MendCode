# Generic Tool Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic one-shot tool confirmation flow so any risky schema tool can pause for user approval, execute once after confirmation, or return a rejection observation without fabrication.

**Architecture:** Add a small runtime confirmation module that owns pending confirmation models, bounded previews, and rejected observations. Wire AgentLoop to produce and resume from confirmed tool observations, then refactor the TUI from `pending_shell` to `pending_tool` while preserving shell command behavior.

**Tech Stack:** Python 3.12, Pydantic v2, Textual TUI, OpenAI-compatible native tool calls, existing ToolRegistry and PermissionPolicy.

---

## File Structure

- Create `app/runtime/tool_confirmation.py`: confirmation models, preview builder, rejected observation helper, and one-shot pending lifecycle helpers.
- Modify `app/schemas/agent_action.py`: extend `UserConfirmationRequestAction` with optional confirmation metadata.
- Modify `app/agent/permission.py`: populate confirmation metadata in `build_confirmation_request`.
- Modify `app/agent/loop.py`: use generic confirmation payloads and support initial observations for resume.
- Modify `app/runtime/agent_loop.py`: seed observation history from `AgentLoopInput.initial_observations`.
- Modify `app/tui/state.py`: replace shell-only pending state with generic `PendingToolConfirmation`, keeping compatibility helpers.
- Modify `app/tui/controller.py`: route user replies through `handle_pending_tool_reply`.
- Modify `app/tui/app.py`: store pending tool requests from `needs_user_confirmation`, approve/reject them, and update `/status`.
- Modify `app/tools/session_status.py`: report pending tool metadata instead of shell-only metadata.
- Modify `MendCode_开发方案.md`: update current implementation state after code lands.
- Test files:
  - `tests/unit/test_tool_confirmation.py`
  - `tests/unit/test_permission_gate.py`
  - `tests/unit/test_agent_loop.py`
  - `tests/unit/test_tui_controller.py`
  - `tests/unit/test_tui_app.py`
  - `tests/scenarios/test_tui_repository_inspection_scenarios.py`

## Task 1: Add Confirmation Runtime Models

**Files:**
- Create: `app/runtime/tool_confirmation.py`
- Test: `tests/unit/test_tool_confirmation.py`

- [ ] **Step 1: Write failing tests for pending confirmation previews**

Create `tests/unit/test_tool_confirmation.py`:

```python
from app.permissions.policy import PermissionDecision
from app.runtime.tool_confirmation import (
    PendingToolConfirmation,
    build_pending_tool_confirmation,
    build_tool_rejected_observation,
    is_confirmation_match,
)
from app.schemas.agent_action import ToolCallAction
from app.tools.structured import ToolInvocation


def test_build_pending_tool_confirmation_for_shell_command() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="run_shell_command",
        reason="Need to inspect generated files",
        args={"command": "find . -maxdepth 2 -type f"},
    )
    invocation = ToolInvocation(
        id="call_shell",
        name="run_shell_command",
        args={"command": "find . -maxdepth 2 -type f"},
        source="openai_tool_call",
        group_id="provider-1",
    )
    decision = PermissionDecision(
        status="confirm",
        reason="command is not in the low-risk allowlist",
        risk_level="medium",
        required_mode="danger-full-access",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=invocation,
        source="agent_loop",
    )

    assert pending.tool_name == "run_shell_command"
    assert pending.tool_call_id == "call_shell"
    assert pending.arguments == {"command": "find . -maxdepth 2 -type f"}
    assert pending.preview["command"] == "find . -maxdepth 2 -type f"
    assert pending.preview["reason"] == "command is not in the low-risk allowlist"
    assert pending.risk_level == "medium"
    assert pending.required_mode == "danger-full-access"


def test_build_pending_tool_confirmation_bounds_large_patch_preview() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="apply_patch",
        reason="Need to change implementation",
        args={
            "files_to_modify": ["app/example.py"],
            "patch": "x" * 5000,
        },
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool apply_patch requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )

    assert pending.preview["files_to_modify"] == ["app/example.py"]
    assert pending.preview["patch_chars"] == 5000
    assert "patch" not in pending.preview


def test_rejected_observation_mentions_tool_and_decision() -> None:
    pending = PendingToolConfirmation(
        id="confirm-123",
        tool_call_id="call_123",
        tool_name="memory_write",
        arguments={"title": "lesson", "content": "body", "kind": "failure_lesson"},
        reason="tool memory_write requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
        preview={"title": "lesson", "kind": "failure_lesson"},
        source="agent_loop",
    )

    observation = build_tool_rejected_observation(pending, user_reply="取消")

    assert observation.status == "rejected"
    assert observation.summary == "Tool call rejected by user"
    assert observation.payload["tool_name"] == "memory_write"
    assert observation.payload["confirmation_id"] == "confirm-123"
    assert observation.error_message == "user rejected tool memory_write"


def test_confirmation_match_prevents_replay() -> None:
    pending = PendingToolConfirmation(
        id="confirm-123",
        tool_call_id=None,
        tool_name="write_file",
        arguments={"path": "README.md", "content": "hello"},
        reason="requires workspace write",
        risk_level="medium",
        required_mode="workspace-write",
        preview={"path": "README.md", "content_chars": 5},
        source="tui",
        consumed=False,
    )

    assert is_confirmation_match(pending, "confirm-123") is True
    consumed = pending.model_copy(update={"consumed": True})
    assert is_confirmation_match(consumed, "confirm-123") is False
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_confirmation.py -q
```

Expected: fail because `app.runtime.tool_confirmation` does not exist.

- [ ] **Step 3: Implement confirmation runtime module**

Create `app/runtime/tool_confirmation.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.permissions.policy import PermissionDecision, RequiredPermissionMode
from app.schemas.agent_action import Observation, RiskLevel, ToolCallAction
from app.tools.structured import ToolInvocation

_MAX_PREVIEW_ITEMS = 20


class PendingToolConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"confirm-{uuid4().hex[:12]}")
    tool_call_id: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    risk_level: RiskLevel
    required_mode: RequiredPermissionMode
    preview: dict[str, Any] = Field(default_factory=dict)
    source: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    consumed: bool = False


def build_pending_tool_confirmation(
    *,
    action: ToolCallAction,
    decision: PermissionDecision,
    tool_invocation: ToolInvocation | None,
    source: str,
) -> PendingToolConfirmation:
    return PendingToolConfirmation(
        tool_call_id=tool_invocation.id if tool_invocation is not None else None,
        tool_name=action.action,
        arguments=dict(action.args),
        reason=decision.reason,
        risk_level=decision.risk_level,
        required_mode=decision.required_mode,
        preview=_preview_for_tool(action.action, action.args, decision.reason),
        source=source,
    )


def build_tool_rejected_observation(
    pending: PendingToolConfirmation,
    *,
    user_reply: str,
) -> Observation:
    return Observation(
        status="rejected",
        summary="Tool call rejected by user",
        payload={
            "confirmation_id": pending.id,
            "tool_call_id": pending.tool_call_id,
            "tool_name": pending.tool_name,
            "risk_level": pending.risk_level,
            "required_mode": pending.required_mode,
            "reason": pending.reason,
            "user_reply": user_reply,
        },
        error_message=f"user rejected tool {pending.tool_name}",
    )


def is_confirmation_match(pending: PendingToolConfirmation, confirmation_id: str) -> bool:
    return pending.id == confirmation_id and not pending.consumed


def _preview_for_tool(tool_name: str, args: dict[str, Any], reason: str) -> dict[str, Any]:
    if tool_name == "run_shell_command":
        return {"command": str(args.get("command", "")), "reason": reason}
    if tool_name == "process_start":
        return {
            "command": str(args.get("command", "")),
            "cwd": str(args.get("cwd", ".")),
            "reason": reason,
        }
    if tool_name == "apply_patch":
        files = args.get("files_to_modify", [])
        return {
            "files_to_modify": _bounded_list(files),
            "patch_chars": len(str(args.get("patch", ""))),
            "reason": reason,
        }
    if tool_name == "write_file":
        return {
            "path": str(args.get("path", "")),
            "content_chars": len(str(args.get("content", ""))),
            "reason": reason,
        }
    if tool_name == "edit_file":
        return {
            "path": str(args.get("path", "")),
            "old_chars": len(str(args.get("old_string", ""))),
            "new_chars": len(str(args.get("new_string", ""))),
            "replace_all": bool(args.get("replace_all", False)),
            "reason": reason,
        }
    if tool_name == "git":
        return {
            "operation": str(args.get("operation", args.get("command", ""))),
            "path": args.get("path"),
            "reason": reason,
        }
    if tool_name == "memory_write":
        return {
            "kind": str(args.get("kind", "")),
            "title": str(args.get("title", "")),
            "tags": _bounded_list(args.get("tags", [])),
            "content_chars": len(str(args.get("content", ""))),
            "reason": reason,
        }
    if tool_name in {"review_queue_accept", "review_queue_reject"}:
        return {"candidate_id": str(args.get("candidate_id", "")), "reason": reason}
    return {
        "argument_keys": sorted(str(key) for key in args.keys())[:_MAX_PREVIEW_ITEMS],
        "reason": reason,
    }


def _bounded_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return value[:_MAX_PREVIEW_ITEMS]
```

- [ ] **Step 4: Run tests and confirm pass**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_confirmation.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add app/runtime/tool_confirmation.py tests/unit/test_tool_confirmation.py
git commit -m "feat: add generic tool confirmation models"
```

## Task 2: Add Confirmation Metadata To Actions And AgentLoop

**Files:**
- Modify: `app/schemas/agent_action.py`
- Modify: `app/agent/permission.py`
- Modify: `app/agent/loop.py`
- Test: `tests/unit/test_permission_gate.py`
- Test: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: Add failing schema and permission tests**

Append to `tests/unit/test_permission_gate.py`:

```python
def test_confirmation_request_includes_tool_metadata():
    action = ToolCallAction(
        type="tool_call",
        action="memory_write",
        reason="Store a lesson",
        args={"kind": "failure_lesson", "title": "lesson", "content": "body"},
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool memory_write requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
    )

    request = build_confirmation_request(action=action, decision=decision)

    assert request.tool_name == "memory_write"
    assert request.required_mode == "workspace-write"
    assert request.permission_reason == "tool memory_write requires confirmation"
```

Append to `tests/unit/test_agent_loop.py`:

```python
def test_agent_loop_confirmation_payload_contains_pending_tool(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            ToolInvocation(
                id="call_memory",
                name="memory_write",
                args={"kind": "failure_lesson", "title": "lesson", "content": "body"},
                source="openai_tool_call",
            )
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="remember this lesson",
            provider=provider,
            permission_mode="custom",
            step_budget=2,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "needs_user_confirmation"
    step = result.steps[0]
    assert step.action.type == "user_confirmation_request"
    assert step.action.tool_name == "memory_write"
    pending = step.observation.payload["pending_confirmation"]
    assert pending["tool_name"] == "memory_write"
    assert pending["tool_call_id"] == "call_memory"
    assert pending["preview"]["title"] == "lesson"
```

- [ ] **Step 2: Run targeted tests and confirm failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_permission_gate.py::test_confirmation_request_includes_tool_metadata tests/unit/test_agent_loop.py::test_agent_loop_confirmation_payload_contains_pending_tool -q
```

Expected: fail because `UserConfirmationRequestAction` lacks metadata and AgentLoop does not add `pending_confirmation`.

- [ ] **Step 3: Extend confirmation action schema**

In `app/schemas/agent_action.py`, change `UserConfirmationRequestAction` to:

```python
class UserConfirmationRequestAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["user_confirmation_request"]
    prompt: str
    risk_level: RiskLevel
    options: list[str]
    tool_name: ToolName | None = None
    required_mode: str | None = None
    permission_reason: str | None = None
    confirmation_id: str | None = None
    preview: dict[str, Any] = Field(default_factory=dict)
```

- [ ] **Step 4: Populate metadata in build_confirmation_request**

In `app/agent/permission.py`, update `build_confirmation_request()`:

```python
def build_confirmation_request(
    *,
    action: ToolCallAction,
    decision: PermissionDecision,
    confirmation_id: str | None = None,
    preview: dict[str, object] | None = None,
) -> UserConfirmationRequestAction:
    return UserConfirmationRequestAction(
        type="user_confirmation_request",
        prompt=(
            f"Agent wants to run {action.action}.\n"
            f"Reason: {action.reason}\n"
            f"Permission decision: {decision.reason}"
        ),
        risk_level=decision.risk_level,
        options=["allow_once", "deny", "change_permission_mode"],
        tool_name=action.action,
        required_mode=decision.required_mode,
        permission_reason=decision.reason,
        confirmation_id=confirmation_id,
        preview=preview or {},
    )
```

- [ ] **Step 5: Wire pending confirmation into AgentLoop**

In `app/agent/loop.py`:

1. Import `build_pending_tool_confirmation`.
2. Change `_confirmation_handled_action()` to accept `tool_invocation`.
3. Build pending confirmation before building the request.
4. Put `pending_confirmation` in observation payload.

Use this implementation shape:

```python
from app.runtime.tool_confirmation import build_pending_tool_confirmation
```

```python
def _confirmation_handled_action(
    *,
    action: ToolCallAction,
    decision: PermissionDecision,
    index: int,
    payload: dict[str, Any],
    error_message: str | None,
    tool_invocation: ToolInvocation | None = None,
) -> _HandledAction:
    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=tool_invocation,
        source="agent_loop",
    )
    payload = dict(payload)
    payload["pending_confirmation"] = pending.model_dump(mode="json")
    confirmation = build_confirmation_request(
        action=action,
        decision=decision,
        confirmation_id=pending.id,
        preview=pending.preview,
    )
    observation = Observation(
        status="rejected",
        summary="User confirmation required",
        payload=payload,
        error_message=error_message,
    )
    return _HandledAction(
        stop=True,
        status="needs_user_confirmation",
        summary=observation.summary,
        step=AgentStep(index=index, action=confirmation, observation=observation),
    )
```

Update the call site in `_handle_tool_call_action()`:

```python
return _confirmation_handled_action(
    action=action,
    decision=decision,
    index=index,
    payload=payload,
    error_message=decision.reason,
    tool_invocation=None,
)
```

Update `_handle_tool_invocation()` so its confirm path passes the current invocation:

```python
return _confirmation_handled_action(
    action=action,
    decision=decision,
    index=index,
    payload=payload,
    error_message=decision.reason,
    tool_invocation=invocation,
)
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_permission_gate.py tests/unit/test_agent_loop.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add app/schemas/agent_action.py app/agent/permission.py app/agent/loop.py tests/unit/test_permission_gate.py tests/unit/test_agent_loop.py
git commit -m "feat: attach pending tool confirmation metadata"
```

## Task 3: Support Resume From Confirmed Tool Observation

**Files:**
- Modify: `app/agent/loop.py`
- Modify: `app/runtime/agent_loop.py`
- Test: `tests/unit/test_agent_loop.py`

- [ ] **Step 1: Add failing test for seeded observations**

Append to `tests/unit/test_agent_loop.py`:

```python
def test_agent_loop_can_resume_after_confirmed_tool_observation(tmp_path: Path) -> None:
    invocation = ToolInvocation(
        id="call_ls",
        name="list_dir",
        args={"path": "."},
        source="openai_tool_call",
        group_id="provider-1",
    )
    action = ToolCallAction(
        type="tool_call",
        action="list_dir",
        reason="confirmed by user",
        args={"path": "."},
    )
    observation = Observation(
        status="succeeded",
        summary="Listed directory",
        payload={"entries": [{"relative_path": "README.md", "type": "file"}]},
    )
    provider = RecordingProvider(
        [
            {
                "type": "final_response",
                "status": "completed",
                "summary": "README.md is present",
            }
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="list files",
            provider=provider,
            permission_mode="guided",
            initial_observations=[
                AgentObservationRecord(
                    action=action,
                    tool_invocation=invocation,
                    observation=observation,
                )
            ],
            step_budget=2,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert provider.calls[0].observations[0].tool_invocation == invocation
    assert result.steps[0].observation.summary == "Listed directory"
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py::test_agent_loop_can_resume_after_confirmed_tool_observation -q
```

Expected: fail because `AgentLoopInput` does not accept `initial_observations`.

- [ ] **Step 3: Add initial observation fields**

In `app/agent/loop.py`, import `AgentObservationRecord` only under a forward-compatible path if needed. Because `app/runtime/agent_loop.py` already imports `AgentObservationRecord`, add this field to `AgentLoopInput`:

```python
initial_observations: list[Any] = Field(default_factory=list)
```

Use `Any` to avoid circular schema coupling inside `app.agent.loop`; validate shape in runtime code.

- [ ] **Step 4: Seed observations in runtime loop**

In `app/runtime/agent_loop.py`, replace:

```python
observation_history: list[AgentObservationRecord] = []
```

with:

```python
observation_history: list[AgentObservationRecord] = [
    record
    for record in loop_input.initial_observations
    if isinstance(record, AgentObservationRecord)
]
```

After `steps: list[AgentStep] = []`, add synthetic steps for trace and visible result continuity:

```python
for seed_index, record in enumerate(observation_history, start=1):
    if record.action is None:
        continue
    steps.append(
        AgentStep(
            index=seed_index,
            action=record.action,
            observation=record.observation,
            tool_invocation=record.tool_invocation,
        )
    )
```

Set the provider loop index to start after seeded steps:

```python
index = len(steps) + 1
```

where the provider path currently uses `index = 1`.

- [ ] **Step 5: Record seeded observations into ContextManager**

After `context_manager.begin_turn(...)`, add:

```python
for record in observation_history:
    context_manager.record_observation(record)
```

- [ ] **Step 6: Run targeted tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add app/agent/loop.py app/runtime/agent_loop.py tests/unit/test_agent_loop.py
git commit -m "feat: resume agent loop with confirmed tool observation"
```

## Task 4: Refactor TUI State To Pending Tool

**Files:**
- Modify: `app/tui/state.py`
- Modify: `app/tui/controller.py`
- Test: `tests/unit/test_tui_controller.py`
- Test: `tests/unit/test_tui_app.py`

- [ ] **Step 1: Add failing state/controller tests**

Update the fake host in `tests/unit/test_tui_controller.py` so it records `pending_tool_replies`, then add:

```python
def test_controller_routes_pending_tool_reply_before_starting_agent() -> None:
    host = FakeHost()
    host.pending_tool_result = True
    controller = TuiController(host)

    controller.handle_user_input("确认")

    assert host.pending_tool_replies == ["确认"]
    assert host.started_tasks == []
```

Append to `tests/unit/test_tui_app.py`:

```python
async def test_status_displays_pending_tool(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))
    async with app.run_test() as pilot:
        app.session_state.set_pending_tool(
            tool_name="memory_write",
            arguments={"title": "lesson"},
            risk_level="medium",
            reason="tool memory_write requires confirmation",
            source="test",
            required_mode="workspace-write",
            preview={"title": "lesson"},
        )

        app.handle_user_input("/status")

    assert "pending_tool: memory_write" in "\n".join(app.message_texts)
```

- [ ] **Step 2: Run tests and confirm failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_controller.py tests/unit/test_tui_app.py::test_status_displays_pending_tool -q
```

Expected: fail because controller and state still use shell-only pending state.

- [ ] **Step 3: Replace state model**

In `app/tui/state.py`, remove `PendingShell` and import the runtime model:

```python
from app.runtime.tool_confirmation import PendingToolConfirmation
```

Change the field:

```python
pending_tool: PendingToolConfirmation | None = None
```

Add:

```python
    def set_pending_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        risk_level: str,
        reason: str,
        source: str,
        required_mode: str = "danger-full-access",
        preview: dict[str, object] | None = None,
        tool_call_id: str | None = None,
        confirmation_id: str | None = None,
    ) -> None:
        payload = {
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "reason": reason,
            "risk_level": risk_level,
            "required_mode": required_mode,
            "preview": preview or {},
            "source": source,
        }
        if confirmation_id is not None:
            payload["id"] = confirmation_id
        self.pending_tool = PendingToolConfirmation.model_validate(payload)

    def clear_pending_tool(self) -> None:
        self.pending_tool = None

    def set_pending_shell(
        self,
        *,
        command: str,
        risk_level: str,
        reason: str,
        source: str,
    ) -> None:
        self.set_pending_tool(
            tool_name="run_shell_command",
            arguments={"command": command},
            risk_level=risk_level,
            reason=reason,
            source=source,
            required_mode="danger-full-access",
            preview={"command": command, "reason": reason},
        )

    def clear_pending_shell(self) -> None:
        self.clear_pending_tool()

    @property
    def pending_shell(self) -> PendingToolConfirmation | None:
        if self.pending_tool is None or self.pending_tool.tool_name != "run_shell_command":
            return None
        return self.pending_tool
```

This preserves existing tests that still check `pending_shell`.

- [ ] **Step 4: Update controller protocol**

In `app/tui/controller.py`, change the protocol method from:

```python
def handle_pending_shell_reply(self, message: str) -> bool: ...
```

to:

```python
def handle_pending_tool_reply(self, message: str) -> bool: ...
```

Change `handle_task()`:

```python
if self._host.handle_pending_tool_reply(task):
    return
if self._host.handle_pending_fix_reply(task):
    return
```

- [ ] **Step 5: Add compatibility method in TUI app**

In `app/tui/app.py`, replace the public method:

```python
def handle_pending_shell_reply(self, message: str) -> bool:
    return self._handle_pending_shell_reply(message)
```

with:

```python
def handle_pending_tool_reply(self, message: str) -> bool:
    return self._handle_pending_tool_reply(message)
```

Keep `_handle_pending_shell_reply` as an alias until old tests are migrated:

```python
def handle_pending_shell_reply(self, message: str) -> bool:
    return self._handle_pending_tool_reply(message)
```

- [ ] **Step 6: Update `/status`**

In `_status_text()`, replace the `pending_shell` block with:

```python
pending_tool = (
    self.session_state.pending_tool.tool_name
    if self.session_state.pending_tool is not None
    else "none"
)
```

and replace:

```python
f"pending_shell: {pending_shell}",
```

with:

```python
f"pending_tool: {pending_tool}",
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_controller.py tests/unit/test_tui_app.py -q
```

Expected: pass after updating old assertions from `pending_shell` to `pending_tool` where the user-visible text changed.

- [ ] **Step 8: Commit**

```bash
git add app/tui/state.py app/tui/controller.py app/tui/app.py tests/unit/test_tui_controller.py tests/unit/test_tui_app.py
git commit -m "feat: replace pending shell state with pending tool state"
```

## Task 5: Execute Or Reject Pending Tools In TUI

**Files:**
- Modify: `app/tui/app.py`
- Modify: `app/tools/session_status.py`
- Test: `tests/unit/test_tui_app.py`
- Test helper: `tests/scenarios/tui_scenario_runner.py`
- Test: `tests/scenarios/test_tui_repository_inspection_scenarios.py`

- [ ] **Step 1: Add failing TUI tests for approve and reject**

Append to `tests/unit/test_tui_app.py`:

```python
async def test_pending_tool_cancel_records_rejection(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))
    async with app.run_test() as pilot:
        app.session_state.set_pending_tool(
            tool_name="memory_write",
            arguments={"kind": "failure_lesson", "title": "lesson", "content": "body"},
            risk_level="medium",
            reason="tool memory_write requires confirmation",
            source="test",
            required_mode="workspace-write",
            preview={"title": "lesson"},
        )

        app.handle_user_input("取消")

    assert app.session_state.pending_tool is None
    assert "已取消待确认的工具调用" in "\n".join(app.message_texts)


async def test_pending_shell_confirmation_still_runs_command(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))
    app.session_state.set_pending_shell(
        command="printf hello",
        risk_level="medium",
        reason="test pending shell",
        source="test",
    )

    async with app.run_test() as pilot:
        app.handle_user_input("确认")
        await pilot.pause()

    assert app.session_state.pending_tool is None
    assert any("Running command: printf hello" in item for item in app.message_texts)
```

- [ ] **Step 2: Extend scenario runner for pending confirmations**

In `tests/scenarios/tui_scenario_runner.py`, import `UserConfirmationRequestAction`:

```python
from app.schemas.agent_action import (
    FinalResponseAction,
    Observation,
    ToolCallAction,
    UserConfirmationRequestAction,
)
```

Add a field to `TuiScenario`:

```python
pending_confirmation: dict[str, Any] | None = None
```

At the start of `FakeToolAgentRunner.__call__()`, before building ordinary tool steps, add:

```python
if self.scenario.pending_confirmation is not None:
    pending = self.scenario.pending_confirmation
    return AgentLoopResult(
        run_id=f"scenario-{self.scenario.name.replace(' ', '-')}",
        status="needs_user_confirmation",
        summary="User confirmation required",
        trace_path=str(self.repo_path / "data" / "traces" / "scenario.jsonl"),
        workspace_path=str(self.repo_path),
        steps=[
            AgentStep(
                index=1,
                action=UserConfirmationRequestAction(
                    type="user_confirmation_request",
                    prompt="Tool call requires confirmation.",
                    risk_level=str(pending["risk_level"]),
                    options=["allow_once", "deny", "change_permission_mode"],
                    tool_name=str(pending["tool_name"]),
                    required_mode=str(pending["required_mode"]),
                    permission_reason=str(pending["reason"]),
                    confirmation_id=str(pending["id"]),
                    preview=dict(pending.get("preview", {})),
                ),
                observation=Observation(
                    status="rejected",
                    summary="User confirmation required",
                    payload={"pending_confirmation": pending},
                    error_message=str(pending["reason"]),
                ),
            )
        ],
    )
```

- [ ] **Step 3: Add failing scenario test for provider confirmation**

Append a scenario test in `tests/scenarios/test_tui_repository_inspection_scenarios.py` using the local scenario runner fake provider style:

```python
async def test_tui_stores_pending_tool_from_agent_loop_confirmation(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="pending memory write confirmation",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["请写入一条记忆"],
            pending_confirmation={
                "id": "confirm-memory",
                "tool_call_id": "call_memory",
                "tool_name": "memory_write",
                "arguments": {
                    "kind": "failure_lesson",
                    "title": "lesson",
                    "content": "body",
                },
                "reason": "tool memory_write requires confirmation",
                "risk_level": "medium",
                "required_mode": "workspace-write",
                "preview": {"title": "lesson"},
                "source": "agent_loop",
            },
        )
    )

    assert_used_tool_path(transcript)
    assert_visible_answer_contains(transcript, "工具调用需要确认")
```

- [ ] **Step 4: Run tests and confirm failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_app.py::test_pending_tool_cancel_records_rejection tests/unit/test_tui_app.py::test_pending_shell_confirmation_still_runs_command tests/scenarios/test_tui_repository_inspection_scenarios.py::test_tui_stores_pending_tool_from_agent_loop_confirmation -q
```

Expected: fail because the TUI does not yet store pending tool results from AgentLoop.

- [ ] **Step 5: Implement pending tool reply handler**

In `app/tui/app.py`, replace `_handle_pending_shell_reply()` with:

```python
def _handle_pending_tool_reply(self, message: str) -> bool:
    pending = self.session_state.pending_tool
    if pending is None:
        return False
    normalized = message.strip().lower()
    if normalized in _CANCEL_TERMS:
        self.session_state.clear_pending_tool()
        self._conversation_log.append_event(
            "tool_confirmation_rejected",
            pending.model_dump(mode="json"),
        )
        self.append_message("System", "已取消待确认的工具调用。")
        return True
    if normalized in _CONFIRM_TERMS:
        self.session_state.clear_pending_tool()
        self._conversation_log.append_event(
            "tool_confirmation_approved",
            pending.model_dump(mode="json"),
        )
        if pending.tool_name == "run_shell_command":
            command = str(pending.arguments.get("command", ""))
            self._start_shell_command(command, confirmed=True)
            return True
        self._start_confirmed_tool(pending)
        return True
    return False
```

Add compatibility alias:

```python
def _handle_pending_shell_reply(self, message: str) -> bool:
    return self._handle_pending_tool_reply(message)
```

- [ ] **Step 6: Store pending tool from AgentLoop result**

In `_complete_tool_request()`, before rendering, add:

```python
if result.status == "needs_user_confirmation" and self._store_pending_tool_from_result(result):
    self.session_state.mark_tool_completed(result.status)
    self._conversation_log.append_event("tool_result", compact_agent_loop_result(result))
    self._render_tool_result(result)
    return
```

Add helper:

```python
def _store_pending_tool_from_result(self, result: AgentLoopResult) -> bool:
    for step in reversed(result.steps):
        pending = step.observation.payload.get("pending_confirmation")
        if not isinstance(pending, dict):
            continue
        self.session_state.set_pending_tool(
            tool_name=str(pending["tool_name"]),
            arguments=dict(pending.get("arguments", {})),
            risk_level=str(pending["risk_level"]),
            reason=str(pending["reason"]),
            source=str(pending.get("source", "agent_loop")),
            required_mode=str(pending.get("required_mode", "danger-full-access")),
            preview=dict(pending.get("preview", {})),
            tool_call_id=pending.get("tool_call_id") if isinstance(pending.get("tool_call_id"), str) else None,
            confirmation_id=str(pending["id"]),
        )
        self.append_message(
            "System",
            "\n".join(
                [
                    "工具调用需要确认。",
                    f"tool: {pending['tool_name']}",
                    f"risk_level: {pending['risk_level']}",
                    f"reason: {pending['reason']}",
                    "回复“确认”或 yes 执行，回复“取消”放弃。",
                ]
            ),
        )
        return True
    return False
```

- [ ] **Step 7: Add confirmed non-shell execution entry**

In `app/tui/app.py`, add:

```python
def _start_confirmed_tool(self, pending: PendingToolConfirmation) -> None:
    if self.session_state.running:
        self.append_message("Error", "A request is already running.")
        return
    self.session_state.mark_tool_started(pending.tool_name)
    self.append_message("Agent", f"Running confirmed tool: {pending.tool_name}")
    self._run_confirmed_tool_worker(pending)
```

This task only stores pending confirmations and keeps shell compatibility. Task 6 adds the provider resume path for confirmed non-shell tools.

- [ ] **Step 8: Update session status tool**

In `app/tools/session_status.py`, use `context.pending_confirmation` as generic metadata. The returned payload should include:

```python
"pending_confirmation": context.pending_confirmation,
```

and no shell-specific key.

- [ ] **Step 9: Run targeted tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_app.py tests/scenarios/test_tui_repository_inspection_scenarios.py -q
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add app/tui/app.py app/tools/session_status.py tests/unit/test_tui_app.py tests/scenarios/tui_scenario_runner.py tests/scenarios/test_tui_repository_inspection_scenarios.py
git commit -m "feat: handle pending tool confirmation in tui"
```

## Task 6: Resume Provider With Confirmed Or Rejected Observation

**Files:**
- Modify: `app/tui/app.py`
- Test: `tests/unit/test_tui_app.py`
- Test: `tests/scenarios/test_tui_repository_inspection_scenarios.py`

- [ ] **Step 1: Add failing resume tests**

Append to `tests/unit/test_tui_app.py`:

```python
async def test_confirmed_tool_result_is_passed_back_to_agent_loop(tmp_path: Path) -> None:
    calls: list[AgentLoopInput] = []

    def runner(*, problem_statement: str, initial_observations=None) -> AgentLoopResult:
        calls.append(
            AgentLoopInput(
                repo_path=tmp_path,
                problem_statement=problem_statement,
                initial_observations=initial_observations or [],
            )
        )
        return AgentLoopResult(
            run_id="agent-test",
            status="completed",
            summary="工具已执行。",
            trace_path=None,
            workspace_path=str(tmp_path),
            steps=[],
        )

    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=runner,
    )
    app.session_state.recent_task = "写入记忆"
    app.session_state.set_pending_tool(
        tool_name="memory_write",
        arguments={"kind": "failure_lesson", "title": "lesson", "content": "body"},
        risk_level="medium",
        reason="tool memory_write requires confirmation",
        source="agent_loop",
        required_mode="workspace-write",
        preview={"title": "lesson"},
        tool_call_id="call_memory",
    )

    async with app.run_test() as pilot:
        app.handle_user_input("确认")
        await pilot.pause()

    assert calls
    assert calls[0].initial_observations
```

- [ ] **Step 2: Run test and confirm failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_app.py::test_confirmed_tool_result_is_passed_back_to_agent_loop -q
```

Expected: fail because confirmed tools are not converted into initial observations yet.

- [ ] **Step 3: Execute confirmed tool through ToolRegistry**

In `app/tui/app.py`, import:

```python
from app.agent.provider import AgentObservationRecord
from app.runtime.tool_confirmation import (
    PendingToolConfirmation,
    build_tool_rejected_observation,
)
from app.schemas.agent_action import ToolCallAction
from app.tools.structured import ToolExecutionContext, ToolInvocation
from app.tools.registry import default_tool_registry
```

Add a helper:

```python
def _execute_pending_tool(self, pending: PendingToolConfirmation) -> AgentObservationRecord:
    action = ToolCallAction(
        type="tool_call",
        action=pending.tool_name,
        reason=f"user approved pending tool {pending.tool_name}",
        args=pending.arguments,
    )
    invocation = ToolInvocation(
        id=pending.tool_call_id,
        name=pending.tool_name,
        args=pending.arguments,
        source="openai_tool_call" if pending.tool_call_id is not None else "json_action",
    )
    spec = default_tool_registry().get(pending.tool_name)
    observation = spec.execute(
        pending.arguments,
        ToolExecutionContext(
            workspace_path=self.repo_path,
            settings=self.settings,
            verification_commands=self.session_state.verification_commands,
            permission_mode="danger-full-access",
            pending_confirmation=pending.model_dump(mode="json"),
        ),
    )
    return AgentObservationRecord(
        action=action,
        tool_invocation=invocation,
        observation=observation,
    )
```

- [ ] **Step 4: Resume tool agent loop with initial observation**

Change `_run_tool_agent_loop()` signature:

```python
def _run_tool_agent_loop(
    self,
    *,
    problem_statement: str,
    initial_observations: list[AgentObservationRecord] | None = None,
) -> AgentLoopResult:
```

Pass to `AgentLoopInput`:

```python
initial_observations=initial_observations or [],
```

Change custom runner protocol and `_run_tool_worker()` to accept `initial_observations` only where supported by a new `_run_tool_worker_with_observations()` method. Keep the existing public runner path compatible by making the default `initial_observations=None`.

Add:

```python
def _start_confirmed_tool(self, pending: PendingToolConfirmation) -> None:
    if self.session_state.running:
        self.append_message("Error", "A request is already running.")
        return
    try:
        confirmed_record = self._execute_pending_tool(pending)
    except Exception as exc:
        self.append_message("Error", str(exc))
        return
    self._conversation_log.append_event(
        "tool_confirmation_executed",
        {
            "pending": pending.model_dump(mode="json"),
            "observation": confirmed_record.observation.model_dump(mode="json"),
        },
    )
    task = self.session_state.recent_task or f"Summarize {pending.tool_name} result"
    self.session_state.mark_tool_started(task)
    self._run_tool_worker(task, initial_observations=[confirmed_record])
```

- [ ] **Step 5: Handle rejection as model observation**

In `_handle_pending_tool_reply()`, when canceling a non-shell pending tool:

```python
rejected_observation = build_tool_rejected_observation(pending, user_reply=message)
self._conversation_log.append_event(
    "tool_confirmation_rejected",
    {
        "pending": pending.model_dump(mode="json"),
        "observation": rejected_observation.model_dump(mode="json"),
    },
)
```

For the first implementation, render:

```python
self.append_message("System", "已取消待确认的工具调用。模型会被告知该工具没有执行。")
```

For this slice, rejection is logged and rendered immediately. Provider resume on rejection is a separate follow-up because the user has explicitly denied execution and no tool result needs summarizing.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_app.py tests/scenarios/test_tui_repository_inspection_scenarios.py -q
```

Expected: pass.

- [ ] **Step 7: Commit**

```bash
git add app/tui/app.py tests/unit/test_tui_app.py tests/scenarios/test_tui_repository_inspection_scenarios.py
git commit -m "feat: resume tui tool loop after confirmation"
```

## Task 7: Regression Tests, Docs, And Final Verification

**Files:**
- Modify: `MendCode_开发方案.md`
- Modify: tests touched in earlier tasks if assertions need final wording cleanup.

- [ ] **Step 1: Add regression tests for low-risk auto-run and critical denial**

Append to `tests/unit/test_agent_loop.py`:

```python
def test_low_risk_read_tool_still_auto_runs_without_confirmation(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\n", encoding="utf-8")
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_read",
                    name="read_file",
                    args={"path": "README.md"},
                    source="openai_tool_call",
                )
            ],
            {
                "type": "final_response",
                "status": "completed",
                "summary": "README was read",
            },
        ],
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="read README",
            provider=provider,
            permission_mode="guided",
            step_budget=3,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert all(step.action.type != "user_confirmation_request" for step in result.steps)


def test_critical_shell_still_denied_without_confirmation(tmp_path: Path) -> None:
    provider = NativeToolProvider(
        [
            ToolInvocation(
                id="call_shell",
                name="run_shell_command",
                args={"command": "rm -rf /"},
                source="openai_tool_call",
            )
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="run dangerous command",
            provider=provider,
            permission_mode="danger-full-access",
            step_budget=2,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert "confirmation" not in result.steps[0].observation.payload
```

- [ ] **Step 2: Update development document**

In `MendCode_开发方案.md`, update section `3.4 Permission / Shell Policy`:

```markdown
- [x] TUI pending shell confirmation 已升级为 generic pending tool confirmation
- [x] `needs_user_confirmation` 会携带 `pending_confirmation`，TUI 可确认或取消任意待确认工具
- [x] 用户确认后按 allow-once 执行一次工具，并把 observation 回传后续 AgentLoop
- [x] 用户取消后记录 rejected observation，避免模型假装工具已经执行
```

Move these from current不足 to completed or remove them:

```markdown
- [ ] 工具确认和 TUI pending confirmation 还没有完全统一为 allow once / deny / change mode
- [ ] allow once / deny / change mode 回写不完整
```

Keep `Custom mode 未配置化` as a remaining gap.

- [ ] **Step 3: Run targeted regression suite**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_confirmation.py tests/unit/test_permission_gate.py tests/unit/test_agent_loop.py tests/unit/test_tui_controller.py tests/unit/test_tui_app.py tests/scenarios/test_tui_repository_inspection_scenarios.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Run non-e2e suite and ruff**

Run:

```bash
env -u MENDCODE_PROVIDER -u MENDCODE_MODEL -u MENDCODE_BASE_URL -u MENDCODE_API_KEY PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q --ignore=tests/e2e
```

Expected: all non-e2e tests pass.

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: ruff passes.

- [ ] **Step 5: Commit final docs and regression cleanup**

```bash
git add MendCode_开发方案.md tests/unit/test_agent_loop.py
git commit -m "test: cover generic tool confirmation regressions"
```

- [ ] **Step 6: Merge back to develop and push**

From the main worktree:

```bash
git checkout develop
git merge --ff-only feature/generic-tool-confirmation
git push origin develop
git worktree remove .worktrees/generic-tool-confirmation
git branch -d feature/generic-tool-confirmation
```

Expected: `develop` tracks `origin/develop` with a clean worktree.

## Self-Review

- Spec coverage: Tasks cover generic pending model, AgentLoop metadata, one-shot approval, rejection observation, TUI status, trace/conversation events, and regression tests.
- Scope control: Plan does not add persistent permissions, permission configuration UI, or review queue panel.
- Type consistency: `PendingToolConfirmation`, `UserConfirmationRequestAction`, `AgentObservationRecord`, and `ToolInvocation` names match current code paths.
- Known implementation constraint: Task 6 changes `_tool_agent_runner` to accept `initial_observations=None`; update `FakeToolAgentRunner` in `tests/unit/test_tui_app.py` and `tests/scenarios/tui_scenario_runner.py` with that default argument in the same task.
