# Tool Closure Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize MendCode's native model tool-calling loop with a deterministic provider test harness and a shared structured tool observation envelope.

**Architecture:** Add test-only provider fixtures that script native `ToolInvocation` responses and assert observation handoff between AgentLoop steps. Add `app/tools/observations.py` as the single helper for building tool observations, then wire ToolRegistry executors through it while preserving existing payload compatibility.

**Tech Stack:** Python 3.12, pytest, Pydantic v2 models, existing MendCode `AgentProvider`, `ToolRegistry`, `Observation`, and `ToolResult` contracts.

---

## File Structure

- Create: `tests/fixtures/__init__.py`
  - Makes fixture helpers importable as `tests.fixtures`.
- Create: `tests/fixtures/mock_tool_provider.py`
  - Test-only deterministic provider harness for native tool-call closure scenarios.
- Create: `tests/unit/test_tool_observations.py`
  - Unit tests for the shared observation envelope helper.
- Create: `tests/unit/test_agent_loop_tool_closure.py`
  - End-to-end AgentLoop tests using the mock provider harness.
- Create: `app/tools/observations.py`
  - Production helper for consistent tool observation payloads.
- Modify: `app/tools/structured.py`
  - Use the observation helper for invalid tool argument observations.
- Modify: `app/tools/registry.py`
  - Route read-only, git, shell, verification, and patch tool observations through the shared helper.
- Modify: `tests/unit/test_tool_registry.py`
  - Update expectations to assert both existing payload fields and new envelope fields.
- Modify: `MendCode_开发方案.md`
  - Mark harness and observation envelope progress after implementation.

---

### Task 1: Add Deterministic Provider Harness

**Files:**
- Create: `tests/fixtures/__init__.py`
- Create: `tests/fixtures/mock_tool_provider.py`
- Test: `tests/unit/test_agent_loop_tool_closure.py`

- [ ] **Step 1: Create the fixture package marker**

Create `tests/fixtures/__init__.py`:

```python
"""Test fixtures shared across MendCode unit tests."""
```

- [ ] **Step 2: Add the mock provider harness**

Create `tests/fixtures/mock_tool_provider.py`:

```python
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.schemas.agent_action import FinalResponseStatus
from app.tools.structured import ToolInvocation

StepAssertion = Callable[[AgentProviderStepInput], None]


@dataclass(frozen=True)
class ScriptedToolStep:
    response: ProviderResponse
    expected_allowed_tools: set[str] | None = None
    expected_observation_count: int | None = None
    assertions: tuple[StepAssertion, ...] = field(default_factory=tuple)


class MockToolProvider:
    def __init__(self, steps: list[ScriptedToolStep]) -> None:
        self.steps = steps
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        index = len(self.calls) - 1
        if index >= len(self.steps):
            raise AssertionError(f"provider called more than scripted steps: {len(self.calls)}")

        step = self.steps[index]
        if step.expected_allowed_tools is not None:
            assert step_input.allowed_tools == step.expected_allowed_tools
        if step.expected_observation_count is not None:
            assert len(step_input.observations) == step.expected_observation_count
        for assertion in step.assertions:
            assertion(step_input)
        return step.response


def tool_call_step(
    *invocations: ToolInvocation,
    expected_allowed_tools: set[str] | None = None,
    expected_observation_count: int | None = None,
    assertions: tuple[StepAssertion, ...] = (),
) -> ScriptedToolStep:
    return ScriptedToolStep(
        response=ProviderResponse(status="succeeded", tool_invocations=list(invocations)),
        expected_allowed_tools=expected_allowed_tools,
        expected_observation_count=expected_observation_count,
        assertions=assertions,
    )


def final_response_step(
    summary: str,
    *,
    status: FinalResponseStatus = "completed",
    expected_observation_count: int | None = None,
    assertions: tuple[StepAssertion, ...] = (),
) -> ScriptedToolStep:
    return ScriptedToolStep(
        response=ProviderResponse(
            status="succeeded",
            actions=[
                {
                    "type": "final_response",
                    "status": status,
                    "summary": summary,
                }
            ],
        ),
        expected_observation_count=expected_observation_count,
        assertions=assertions,
    )


def native_tool(
    name: str,
    args: dict[str, object] | None = None,
    *,
    call_id: str = "call_1",
) -> ToolInvocation:
    return ToolInvocation(
        id=call_id,
        name=name,
        args=args or {},
        source="openai_tool_call",
    )


def assert_last_observation(
    *,
    tool_name: str,
    status: Literal["succeeded", "failed", "rejected"] = "succeeded",
) -> StepAssertion:
    def _assert(step_input: AgentProviderStepInput) -> None:
        assert step_input.observations
        record = step_input.observations[-1]
        assert record.tool_invocation is not None
        assert record.tool_invocation.name == tool_name
        assert record.observation.status == status
        assert record.observation.payload["tool_name"] == tool_name
        assert record.observation.payload["status"] == status

    return _assert


def assert_payload_contains(key: str, expected: object) -> StepAssertion:
    def _assert(step_input: AgentProviderStepInput) -> None:
        payload = step_input.observations[-1].observation.payload
        assert payload.get(key) == expected or payload.get("payload", {}).get(key) == expected

    return _assert
```

- [ ] **Step 3: Add a minimal harness smoke test**

Create `tests/unit/test_agent_loop_tool_closure.py` with this initial content:

```python
from pathlib import Path

from app.agent.loop import AgentLoopInput, run_agent_loop
from app.config.settings import Settings
from tests.fixtures.mock_tool_provider import (
    MockToolProvider,
    assert_last_observation,
    final_response_step,
    native_tool,
    tool_call_step,
)


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


def test_mock_tool_provider_harness_drives_list_dir_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("demo\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("list_dir", {"path": "."}, call_id="call_list"),
                expected_allowed_tools={"list_dir", "read_file"},
                expected_observation_count=0,
            ),
            final_response_step(
                "当前目录包含 README.md",
                expected_observation_count=1,
                assertions=(assert_last_observation(tool_name="list_dir"),),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="帮我查看当前文件夹里的文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"list_dir", "read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "当前目录包含 README.md"
    assert len(provider.calls) == 2
```

- [ ] **Step 4: Run the new smoke test and confirm it fails before envelope work**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_agent_loop_tool_closure.py::test_mock_tool_provider_harness_drives_list_dir_roundtrip
```

Expected:

```text
FAILED ... KeyError: 'tool_name'
```

The failure proves the harness is checking the missing observation envelope.

---

### Task 2: Add Shared Tool Observation Envelope

**Files:**
- Create: `app/tools/observations.py`
- Modify: `app/tools/structured.py`
- Create: `tests/unit/test_tool_observations.py`

- [ ] **Step 1: Write observation helper tests**

Create `tests/unit/test_tool_observations.py`:

```python
from pathlib import Path

from app.tools.observations import (
    observation_from_tool_result,
    tool_observation,
)
from app.tools.schemas import ToolResult


def test_tool_observation_adds_envelope_and_preserves_payload_keys() -> None:
    observation = tool_observation(
        tool_name="list_dir",
        status="succeeded",
        summary="Listed .",
        payload={
            "relative_path": ".",
            "entries": [{"relative_path": "README.md"}],
            "truncated": False,
        },
    )

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "list_dir"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["summary"] == "Listed ."
    assert observation.payload["is_error"] is False
    assert observation.payload["truncated"] is False
    assert observation.payload["next_offset"] is None
    assert observation.payload["stdout_excerpt"] == ""
    assert observation.payload["stderr_excerpt"] == ""
    assert observation.payload["duration_ms"] is None
    assert observation.payload["payload"]["entries"] == [{"relative_path": "README.md"}]
    assert observation.payload["entries"] == [{"relative_path": "README.md"}]
    assert observation.error_message is None


def test_tool_observation_requires_error_message_for_failed_status() -> None:
    observation = tool_observation(
        tool_name="read_file",
        status="rejected",
        summary="Unable to read missing.txt",
        payload={"relative_path": "missing.txt"},
        error_message="path does not exist",
    )

    assert observation.status == "rejected"
    assert observation.payload["is_error"] is True
    assert observation.payload["payload"]["relative_path"] == "missing.txt"
    assert observation.error_message == "path does not exist"


def test_observation_from_tool_result_maps_passed_to_succeeded(tmp_path: Path) -> None:
    result = ToolResult(
        tool_name="read_file",
        status="passed",
        summary="Read README.md",
        payload={"relative_path": "README.md", "content": "demo\n", "truncated": False},
        error_message=None,
        workspace_path=str(tmp_path),
    )

    observation = observation_from_tool_result(result)

    assert observation.status == "succeeded"
    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["payload"]["content"] == "demo\n"
    assert observation.payload["content"] == "demo\n"
```

- [ ] **Step 2: Run tests to verify helper is missing**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tool_observations.py
```

Expected:

```text
FAILED ... ModuleNotFoundError: No module named 'app.tools.observations'
```

- [ ] **Step 3: Implement the helper**

Create `app/tools/observations.py`:

```python
from __future__ import annotations

from typing import Any, Literal

from app.schemas.agent_action import Observation, ObservationStatus
from app.tools.schemas import ToolResult

ToolResultStatus = Literal["passed", "failed", "rejected"]


def _observation_status(status: ObservationStatus | ToolResultStatus) -> ObservationStatus:
    if status == "passed":
        return "succeeded"
    return status


def tool_observation(
    *,
    tool_name: str,
    status: ObservationStatus | ToolResultStatus,
    summary: str,
    payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    truncated: bool | None = None,
    next_offset: int | None = None,
    stdout_excerpt: str | None = None,
    stderr_excerpt: str | None = None,
    duration_ms: int | None = None,
) -> Observation:
    observation_status = _observation_status(status)
    tool_payload = dict(payload or {})
    stdout_value = stdout_excerpt
    if stdout_value is None:
        stdout_value = str(tool_payload.get("stdout_excerpt", "") or "")
    stderr_value = stderr_excerpt
    if stderr_value is None:
        stderr_value = str(tool_payload.get("stderr_excerpt", "") or "")

    envelope: dict[str, Any] = {
        "tool_name": tool_name,
        "status": observation_status,
        "summary": summary,
        "is_error": observation_status != "succeeded",
        "payload": tool_payload,
        "truncated": bool(tool_payload.get("truncated", False) if truncated is None else truncated),
        "next_offset": next_offset if next_offset is not None else tool_payload.get("next_offset"),
        "stdout_excerpt": stdout_value,
        "stderr_excerpt": stderr_value,
        "duration_ms": duration_ms if duration_ms is not None else tool_payload.get("duration_ms"),
    }
    for key, value in tool_payload.items():
        envelope.setdefault(key, value)

    return Observation(
        status=observation_status,
        summary=summary,
        payload=envelope,
        error_message=error_message,
    )


def observation_from_tool_result(result: ToolResult) -> Observation:
    return tool_observation(
        tool_name=result.tool_name,
        status=result.status,
        summary=result.summary,
        payload=result.payload,
        error_message=result.error_message,
        truncated=result.payload.get("truncated") if isinstance(result.payload.get("truncated"), bool) else None,
    )
```

- [ ] **Step 4: Route invalid ToolSpec args through the helper**

Modify `app/tools/structured.py` imports:

```python
from app.config.settings import Settings
from app.schemas.agent_action import Observation
from app.tools.observations import tool_observation
```

Replace the `except ValidationError as exc:` block in `ToolSpec.execute` with:

```python
        except ValidationError as exc:
            return tool_observation(
                tool_name=self.name,
                status="rejected",
                summary="Invalid tool arguments",
                payload={"args": args},
                error_message=str(exc),
            )
```

- [ ] **Step 5: Run helper tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tool_observations.py
```

Expected:

```text
3 passed
```

---

### Task 3: Wire ToolRegistry Observations Through the Envelope

**Files:**
- Modify: `app/tools/registry.py`
- Modify: `tests/unit/test_tool_registry.py`
- Test: `tests/unit/test_tool_registry.py`

- [ ] **Step 1: Update registry imports and `tool_result_to_observation`**

Modify `app/tools/registry.py` imports:

```python
from app.tools.observations import observation_from_tool_result, tool_observation
```

Replace `tool_result_to_observation` with:

```python
def tool_result_to_observation(result: ToolResult) -> Observation:
    return observation_from_tool_result(result)
```

- [ ] **Step 2: Update `_failed` and `_rejected` to accept tool names**

Replace `_failed` and `_rejected` with:

```python
def _failed(
    tool_name: str,
    summary: str,
    error_message: str,
    payload: dict[str, object] | None = None,
) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="failed",
        summary=summary,
        payload=payload or {},
        error_message=error_message,
    )


def _rejected(
    tool_name: str,
    summary: str,
    error_message: str,
    payload: dict[str, object] | None = None,
) -> Observation:
    return tool_observation(
        tool_name=tool_name,
        status="rejected",
        summary=summary,
        payload=payload or {},
        error_message=error_message,
    )
```

Then update call sites:

```python
return _rejected("git", "Unable to run git", error_message, payload=args.model_dump(mode="json"))
return _failed("git", "Unable to run git", "...", payload={...})
return _rejected("run_shell_command", "Unable to run shell command", "command must not be empty", payload={"command": args.command})
return _rejected("run_command", "Unable to run command", "command must not be empty", payload={"command": args.command})
return _rejected("apply_patch", "Unable to apply patch", error_message, payload={"paths": paths})
return _failed("apply_patch", "Unable to apply patch", "...", payload={...})
```

- [ ] **Step 3: Update shell observation conversion**

Replace `_shell_result_to_observation` with:

```python
def _shell_result_to_observation(result: ShellCommandResult) -> Observation:
    if result.status == "passed":
        status = "succeeded"
    elif result.status in {"rejected", "needs_confirmation"}:
        status = "rejected"
    else:
        status = "failed"
    payload = result.model_dump(mode="json")
    return tool_observation(
        tool_name="run_shell_command",
        status=status,
        summary=f"Ran shell command: {result.command}",
        payload=payload,
        error_message=None if status == "succeeded" else result.stderr_excerpt,
        stdout_excerpt=result.stdout_excerpt,
        stderr_excerpt=result.stderr_excerpt,
        duration_ms=result.duration_ms,
    )
```

- [ ] **Step 4: Update successful git, run_command, and apply_patch observations**

In `_git`, replace the final success return with:

```python
    return tool_observation(
        tool_name="git",
        status="succeeded",
        summary=f"Ran git: {command}",
        payload=payload,
        stdout_excerpt=payload["stdout_excerpt"],
        stderr_excerpt=payload["stderr_excerpt"],
    )
```

In `_run_command`, replace the final `Observation(...)` construction with:

```python
    payload = result.model_dump(mode="json")
    return tool_observation(
        tool_name="run_command",
        status=status,
        summary=f"Ran command: {args.command}",
        payload=payload,
        error_message=None if result.status == "passed" else result.stderr_excerpt,
        stdout_excerpt=result.stdout_excerpt,
        stderr_excerpt=result.stderr_excerpt,
        duration_ms=result.duration_ms,
    )
```

In `_apply_patch`, replace the success return with:

```python
    return tool_observation(
        tool_name="apply_patch",
        status="succeeded",
        summary="Applied patch",
        payload=payload,
        stdout_excerpt=payload["stdout_excerpt"],
        stderr_excerpt=payload["stderr_excerpt"],
    )
```

- [ ] **Step 5: Update registry tests for envelope fields**

In `tests/unit/test_tool_registry.py`, update `test_tool_result_to_observation_maps_passed_result`:

```python
    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["payload"] == {"relative_path": "README.md"}
    assert observation.payload["relative_path"] == "README.md"
```

In `test_registry_executes_read_file_tool`, add:

```python
    assert observation.payload["tool_name"] == "read_file"
    assert observation.payload["status"] == "succeeded"
    assert observation.payload["payload"]["content"] == "hello\n"
```

In `test_registry_executes_search_code_alias`, add:

```python
    assert observation.payload["tool_name"] == "search_code"
    assert observation.payload["payload"]["total_matches"] == 2
```

In `test_git_status_uses_structured_operation`, add:

```python
    assert observation.payload["tool_name"] == "git"
    assert observation.payload["payload"]["command"] == "git status --short"
```

In `test_run_command_keeps_verification_allowlist`, add:

```python
    assert observation.payload["tool_name"] == "run_command"
    assert observation.payload["is_error"] is True
```

In `test_apply_patch_rejects_repo_escaping_path`, add:

```python
    assert observation.payload["tool_name"] == "apply_patch"
    assert observation.payload["is_error"] is True
```

- [ ] **Step 6: Run registry tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tool_registry.py tests/unit/test_tool_observations.py
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 7: Run existing AgentLoop tests to catch compatibility breaks**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_agent_loop.py
```

Expected:

```text
all selected tests passed
```

Existing tests that read `observation.payload["entries"]`, `["command"]`, or `["stdout_excerpt"]` should still pass because the helper preserves tool-specific keys at the top level for compatibility.

---

### Task 4: Add AgentLoop Tool Closure Scenario Coverage

**Files:**
- Modify: `tests/unit/test_agent_loop_tool_closure.py`
- Test: `tests/unit/test_agent_loop_tool_closure.py`

- [ ] **Step 1: Add read file roundtrip test**

Append to `tests/unit/test_agent_loop_tool_closure.py`:

```python
def test_read_file_roundtrip_returns_observation_before_final_answer(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("MendCode demo\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("read_file", {"path": "README.md"}, call_id="call_read")),
            final_response_step(
                "README.md 内容是 MendCode demo",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="read_file"),
                    assert_payload_contains("content", "MendCode demo\n"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="读取 README.md",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "README.md 内容是 MendCode demo"
```

- [ ] **Step 2: Add rg roundtrip test**

Append:

```python
def test_rg_roundtrip_returns_matches_before_final_answer(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def run():\n    return 'needle'\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("rg", {"query": "needle", "glob": "*.py"}, call_id="call_rg")),
            final_response_step(
                "needle 出现在 app.py",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="rg"),
                    assert_payload_contains("total_matches", 1),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="搜索 needle",
            provider=provider,
            verification_commands=[],
            allowed_tools={"rg"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "needle 出现在 app.py"
```

- [ ] **Step 3: Add multi-tool turn test**

Append:

```python
def test_multi_tool_turn_preserves_both_observations(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("readme\n", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("notes\n", encoding="utf-8")
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("read_file", {"path": "README.md"}, call_id="call_readme"),
                native_tool("read_file", {"path": "notes.txt"}, call_id="call_notes"),
            ),
            final_response_step(
                "读取了 README.md 和 notes.txt",
                expected_observation_count=2,
                assertions=(
                    assert_last_observation(tool_name="read_file"),
                    assert_payload_contains("content", "notes\n"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="读取两个文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert [step.observation.payload["tool_name"] for step in result.steps[:2]] == [
        "read_file",
        "read_file",
    ]
```

- [ ] **Step 4: Add shell stdout roundtrip test**

Append:

```python
def test_shell_stdout_roundtrip_includes_exit_code_and_stdout(tmp_path: Path) -> None:
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool(
                    "run_shell_command",
                    {"command": "printf 'hello-shell'"},
                    call_id="call_shell",
                )
            ),
            final_response_step(
                "shell 输出 hello-shell",
                expected_observation_count=1,
                assertions=(
                    assert_last_observation(tool_name="run_shell_command"),
                    assert_payload_contains("exit_code", 0),
                    assert_payload_contains("stdout_excerpt", "hello-shell"),
                ),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="运行一个安全 shell 命令",
            provider=provider,
            verification_commands=[],
            allowed_tools={"run_shell_command"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "completed"
    assert result.summary == "shell 输出 hello-shell"
```

- [ ] **Step 5: Add tool error roundtrip test**

Append:

```python
def test_tool_error_roundtrip_is_structured_and_blocks_completed_final(tmp_path: Path) -> None:
    provider = MockToolProvider(
        [
            tool_call_step(native_tool("read_file", {"path": "missing.txt"}, call_id="call_missing")),
            final_response_step(
                "文件不存在",
                status="failed",
                expected_observation_count=1,
                assertions=(assert_last_observation(tool_name="read_file", status="rejected"),),
            ),
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="读取 missing.txt",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.summary == "文件不存在"
    assert result.steps[0].observation.payload["is_error"] is True
```

- [ ] **Step 6: Add allowed-tools denial test**

Append:

```python
def test_allowed_tools_denial_stops_before_execution(tmp_path: Path) -> None:
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool("apply_patch", {"patch": ""}, call_id="call_patch"),
                expected_allowed_tools={"read_file"},
            )
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="只读任务不应该暴露写工具",
            provider=provider,
            verification_commands=[],
            allowed_tools={"read_file"},
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert result.steps[0].observation.status == "rejected"
    assert result.steps[0].observation.summary == "Tool denied by allowed-tools gate"
    assert not (tmp_path / ".git" / "applypatch-msg.sample").exists()
```

- [ ] **Step 7: Add permission confirmation stop test**

Append:

```python
def test_permission_confirmation_stop_does_not_run_restricted_shell(tmp_path: Path) -> None:
    marker = tmp_path / "marker.txt"
    provider = MockToolProvider(
        [
            tool_call_step(
                native_tool(
                    "run_shell_command",
                    {"command": "touch marker.txt"},
                    call_id="call_touch",
                )
            )
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="尝试写入文件",
            provider=provider,
            verification_commands=[],
            allowed_tools={"run_shell_command"},
            permission_mode="guided",
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "needs_user_confirmation"
    assert result.steps[0].action.type == "user_confirmation_request"
    assert result.steps[0].observation.status == "rejected"
    assert not marker.exists()
```

- [ ] **Step 8: Run closure tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_agent_loop_tool_closure.py
```

Expected:

```text
8 passed
```

If `test_allowed_tools_denial_stops_before_execution` fails because the marker assertion is not meaningful for `apply_patch`, remove that marker assertion and keep the status/summary assertions. The execution boundary is already proven by rejection before `apply_patch` receives valid patch input.

---

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `MendCode_开发方案.md`
- Optional modify: `README.md` only if final implementation exposes a user-visible behavior change.

- [ ] **Step 1: Update development plan status**

In `MendCode_开发方案.md`, update section `3.1 AgentLoop`:

```markdown
- [x] deterministic mock provider harness for native tool-call closure
```

Update current不足 by removing or narrowing:

```markdown
- [ ] 没有完整 mock provider parity harness
```

to:

```markdown
- [ ] mock provider harness 仍需扩展到 future write tools 和 permission allow/deny resume
```

In section `3.3 ToolRegistry`, add to 已完成:

```markdown
- [x] shared tool observation envelope
```

In section `4. 当前重点任务队列`, update Task 2 and Task 3 to mark this slice as landed:

```markdown
状态：

- 基础 observation envelope 已完成，后续继续收敛 legacy builtin tool payload。
- Mock provider harness 已覆盖 read/list/rg/multi-tool/shell/error/allowed-tools/confirmation stop。
```

- [ ] **Step 2: Add issue record only if a new reusable pitfall was discovered**

If implementation exposes a new repeated-risk pattern, add it to `MendCode_问题记录.md` using this format:

```markdown
### 问题 N：<问题标题>

状态：<状态>

现象：

根因：

处理：

后续约束：
```

Do not update the issue log for ordinary implementation details.

- [ ] **Step 3: Run focused verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_tool_observations.py tests/unit/test_tool_registry.py tests/unit/test_agent_loop_tool_closure.py tests/unit/test_agent_loop.py tests/unit/test_openai_compatible_provider.py
```

Expected:

```text
all selected tests passed
```

- [ ] **Step 4: Run full verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected:

```text
pytest passes
ruff passes
```

- [ ] **Step 5: Inspect final diff**

Run:

```bash
git diff --stat
git diff -- app/tools/observations.py app/tools/structured.py app/tools/registry.py tests/fixtures/mock_tool_provider.py tests/unit/test_tool_observations.py tests/unit/test_agent_loop_tool_closure.py MendCode_开发方案.md
```

Expected:

```text
Diff contains only the harness, observation envelope, registry wiring, tests, and docs for this slice.
```

- [ ] **Step 6: Commit implementation**

Run:

```bash
git add app/tools/observations.py app/tools/structured.py app/tools/registry.py tests/fixtures/__init__.py tests/fixtures/mock_tool_provider.py tests/unit/test_tool_observations.py tests/unit/test_agent_loop_tool_closure.py tests/unit/test_tool_registry.py MendCode_开发方案.md
git commit -m "Add tool closure harness"
```

Expected:

```text
[main <hash>] Add tool closure harness
```

---

## Self-Review

- Spec coverage:
  - Deterministic provider harness: Task 1 and Task 4.
  - Shared observation envelope: Task 2 and Task 3.
  - Read/list/rg/multi-tool/shell/error/denial/confirmation scenarios: Task 4.
  - Documentation update: Task 5.
- Placeholder scan:
  - No implementation placeholders remain. The only conditional note is a concrete fallback for a possibly weak marker assertion in one test.
- Type consistency:
  - The plan uses existing `AgentProviderStepInput`, `ProviderResponse`, `ToolInvocation`, `Observation`, and `ToolResult` types.
  - Helper names introduced in Task 1 are reused consistently in Task 4.
