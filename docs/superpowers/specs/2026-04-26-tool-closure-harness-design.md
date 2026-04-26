# Tool Closure Harness Design

## 1. Purpose

This design defines the next MendCode development slice: stabilize the model tool-calling closure with a deterministic mock provider harness and a shared tool observation envelope.

The goal is to make this flow reproducible in tests:

```text
user asks for local facts
-> provider emits native tool_calls
-> AgentLoop checks allowed tools and permission
-> ToolRegistry executes local tool
-> structured observation returns to provider
-> provider writes a final answer grounded in the observation
```

This slice does not add new write tools. It prepares the runtime so later tools such as `write_file`, `edit_file`, and `todo_write` can be added without increasing ambiguity in provider behavior or result handling.

## 2. Scope

In scope:

- A deterministic provider harness for AgentLoop tests.
- Scripted native `tool_calls` scenarios for read-only tools, shell output, errors, and permission denials.
- A shared observation envelope for ToolRegistry executors.
- Regression tests that prove tool observations are sent back to the provider before final response.
- Documentation updates in `MendCode_开发方案.md` and, if user-visible behavior changes, `README.md`.

Out of scope:

- New write tools.
- Subagent execution.
- MCP lifecycle.
- TUI visual redesign.
- Session resume.
- Real network provider integration changes.

## 3. Architecture

### 3.1 Mock Provider Harness

Add a test-only provider helper that behaves like an OpenAI-compatible model at the AgentLoop boundary. It should script a sequence of provider steps:

1. Return a native tool invocation.
2. Receive the tool observation in the next provider input.
3. Assert the observation contains expected fields.
4. Return a final response grounded in that observation.

The harness should live under `tests/fixtures/` or `tests/support/` rather than production `app/` code. It should use existing `AgentProvider`, `AgentProviderStepInput`, `AgentProviderStepResult`, and `ToolInvocation` types instead of inventing a parallel protocol.

Recommended file:

```text
tests/fixtures/mock_tool_provider.py
```

Core concepts:

- `ScriptedToolStep`: expected provider input plus returned provider output.
- `MockToolProvider`: records calls, validates allowed tools, validates observation history, and returns scripted results.
- Helper assertions for common scenarios: final response after tool result, no disallowed tool schema exposure, error observation is preserved.

The harness must be deterministic and must not call any real LLM endpoint.

### 3.2 Tool Observation Envelope

Current tools return `Observation` payloads with related but inconsistent field shapes. Add a small helper layer that normalizes tool results before they enter AgentLoop and logs.

Recommended production file:

```text
app/tools/observations.py
```

Envelope fields:

```text
tool_name
status
summary
is_error
payload
truncated
next_offset
stdout_excerpt
stderr_excerpt
duration_ms
```

Rules:

- `status` remains compatible with existing `Observation.status` values.
- `payload` preserves the tool-specific data instead of flattening it away.
- Missing optional fields are represented as `None`, empty string, or `False` consistently.
- Failed and rejected tools still return structured observations so the provider can recover or explain the failure.
- Existing `ToolResult` outputs should be converted through one normalization path.

### 3.3 AgentLoop Integration

AgentLoop should keep using `Observation` as the public contract. This slice should not rewrite the loop. The change is that ToolRegistry executors produce observations whose payloads have a consistent envelope.

Provider prompt context should be checked only for compatibility. If prompt formatting already passes structured observation data through, no prompt rewrite is required beyond tests.

### 3.4 Permission Scenarios

The harness should cover both provider-level and AgentLoop-level denial behavior:

- A tool outside `allowed_tools` is rejected before execution.
- A tool requiring confirmation produces a structured rejected observation or `needs_user_confirmation` result, depending on existing loop behavior.
- A denied or rejected tool result is still visible to the next provider step only when the loop continues by design. If the loop stops for user confirmation, the test should assert the stop status instead.

This design does not implement a full `PermissionPolicy` object. That remains the next architecture slice after the harness locks current behavior.

## 4. Required Scenarios

The first harness version must cover these scenarios:

1. `list_dir_roundtrip`
   - User asks for current folder files.
   - Provider calls `list_dir`.
   - AgentLoop returns entries.
   - Provider final answer names files from the observation.

2. `read_file_roundtrip`
   - Provider calls `read_file`.
   - Final answer uses actual file content.

3. `rg_roundtrip`
   - Provider calls `rg`.
   - Final answer uses search matches.

4. `multi_tool_turn`
   - Provider calls two read-only tools in sequence or across two steps.
   - Final answer is based on both observations.

5. `shell_stdout_roundtrip`
   - Provider calls `run_shell_command` only when that tool is allowed.
   - Observation includes stdout excerpt, exit code, duration, and shell status.

6. `tool_error_roundtrip`
   - Provider calls a tool with invalid args or missing path.
   - Error observation is structured and available for final explanation.

7. `allowed_tools_denial`
   - Provider attempts a tool outside the current scoped set.
   - AgentLoop rejects it and does not execute it.

8. `permission_confirmation_stop`
   - Provider asks for a restricted command in a mode that requires confirmation.
   - AgentLoop stops with confirmation state instead of pretending the command ran.

## 5. Testing Strategy

Use focused unit tests first:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/unit/test_agent_loop.py tests/unit/test_tool_registry.py
```

Then run full verification:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Tests should assert behavior, not just object shape:

- Provider receives the previous observation before returning final response.
- Final answer appears only after at least one relevant observation for local facts.
- Tool payloads contain the normalized envelope fields.
- Disallowed tools are rejected at execution boundary.
- Permission confirmation does not run the underlying command.

## 6. Risks

### Risk: Over-normalizing payloads

The envelope should not erase tool-specific data. Keep tool-specific data under `payload` and add common envelope fields around it.

### Risk: Harness duplicates production provider logic

The harness should use provider interfaces and return `AgentProviderStepResult` objects directly. It should not reimplement OpenAI request parsing.

### Risk: Large refactor while stabilizing behavior

Avoid rewriting AgentLoop. This slice should add test coverage and result normalization with minimal production churn.

### Risk: Permission behavior ambiguity

If current behavior stops on confirmation, preserve that behavior and test it. Do not silently continue with a synthetic denial unless a later PermissionPolicy design explicitly changes it.

## 7. Acceptance Criteria

- Deterministic tests cover the required scenarios without network access.
- `list_dir`, `read_file`, `rg`, `git`, `run_shell_command`, `run_command`, and `apply_patch` observations expose the shared envelope fields.
- Error and rejected observations remain structured.
- A local-fact final answer in tests is grounded in a prior tool observation.
- Existing OpenAI-compatible provider tests still pass.
- Full pytest and ruff pass.
- `MendCode_开发方案.md` records the new harness and observation envelope status after implementation.
