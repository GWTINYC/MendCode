# Generic Tool Confirmation Design

## 1. Purpose

MendCode already has a schema-based ToolRegistry, a PermissionPolicy, shell-specific confirmation in the TUI, and a provider loop that can stop with `needs_user_confirmation`. The next step is to make confirmation a generic runtime capability instead of a shell-only UI state.

This design adds a unified confirmation gate for every model-requested tool call:

```text
Model tool_call
-> ToolRegistry validation
-> PermissionPolicy decision
-> allow / confirm / deny
-> tool execution or pending confirmation
-> observation back to model
-> compact user output and JSONL trace
```

The goal is to make risky tool calls controllable without making the model fall back to fabricated answers when a tool cannot run immediately.

## 2. Goals

- Replace shell-only pending confirmation with a generic pending tool confirmation model.
- Route every provider-visible tool through the same permission decision path.
- Let the TUI approve or reject a single pending tool call with natural replies such as `确认` or `取消`.
- Return a structured observation to the model when the user confirms or rejects the tool.
- Keep critical destructive operations denied even when the user is in a high-permission mode.
- Record confirmation requests, decisions, and execution summaries in trace data.
- Keep the visible chat concise while preserving enough detail for model context and later debugging.

## 3. Non-Goals

- Do not add a full permission configuration UI in this slice.
- Do not add persistent allow-lists or "always allow this tool" behavior yet.
- Do not build the review queue TUI panel in this slice.
- Do not change the default tool pool to expose dangerous tools in guided mode.
- Do not claim benchmark pass-rate or token-reduction metrics from this feature alone.

## 4. Current Gaps

The current codebase has the right primitives but not one complete confirmation surface:

- `PermissionPolicy` can return `allow`, `confirm`, or `deny`.
- `build_confirmation_request()` already models `allow_once`, `deny`, and `change_permission_mode`.
- `run_shell_command` has TUI pending shell handling.
- AgentLoop can produce `needs_user_confirmation`.
- Some non-shell tools, such as `memory_write` and `review_queue_accept`, are risk-classified but do not share the same TUI confirmation lifecycle.

This leaves two user-facing risks:

1. The model may request a tool that needs user approval, stop, and then fail to continue with a useful observation.
2. The TUI status and confirmation copy still describe shell commands rather than the broader tool system.

## 5. Architecture

### 5.1 PendingToolConfirmation

Add a generic model near the TUI/session boundary:

```text
PendingToolConfirmation
- id
- tool_call_id
- tool_name
- arguments
- reason
- risk_level
- required_mode
- preview
- source
- created_at
```

`preview` is a bounded, user-facing summary produced before execution. Examples:

- `run_shell_command`: command, cwd, shell risk reason
- `apply_patch`: changed file list and diff stat when available
- `write_file`: path and byte count
- `edit_file`: path and replacement count
- `git`: operation and target branch/path
- `memory_write`: memory kind, title, tags
- `review_queue_accept`: candidate id and summary

The model should not contain unbounded file contents, full patches, or long command output. Full tool arguments remain available in trace.

### 5.2 Confirmation Gate

Introduce a runtime helper responsible for turning a validated tool call plus permission decision into one of three outcomes:

```text
ToolGateResult
- allowed: execute immediately
- pending: return PendingToolConfirmation
- denied: return rejected observation
```

This helper should not execute tools. It only owns:

- permission decision normalization
- confirmation preview construction
- trace-safe confirmation request payloads
- common denied/rejected observation shaping

AgentLoop remains responsible for actually dispatching the tool when allowed.

### 5.3 AgentLoop Flow

For each normalized tool call:

1. Validate args with ToolRegistry.
2. Run tool-specific classifiers when needed, such as ShellPolicy for `run_shell_command`.
3. Ask PermissionPolicy for the final decision.
4. If `allow`, execute the tool and return normal observation.
5. If `deny`, append a rejected observation and continue the model loop when useful.
6. If `confirm`, stop the turn with `needs_user_confirmation` and include `PendingToolConfirmation`.

When the user confirms:

1. TUI calls a resume path with the exact pending confirmation id.
2. Runtime revalidates the stored tool call and executes it with `confirmed=True` or equivalent context.
3. The tool result becomes a `tool` observation for the next provider step.
4. The model gets one more chance to produce the concise final answer.

When the user rejects:

1. Runtime creates a rejected observation.
2. The model receives that rejection and should answer without claiming the tool ran.
3. Trace records the rejection reason.

The first implementation can support one pending tool at a time. If a provider returns multiple tool calls and the first needs confirmation, later tool calls are not executed until the pending call is resolved.

### 5.4 TUI Behavior

The TUI should rename shell-specific state to a generic pending tool state:

```text
SessionState.pending_tool
```

User-visible behavior:

- Low-risk tools still auto-run.
- Risky tools display a concise confirmation prompt.
- `/status` reports the pending tool name and reason.
- `确认`, `yes`, `y`, `开始`, `继续` approve the pending tool once.
- `取消`, `no`, `n`, `停止`, `算了` reject the pending tool.
- While a tool or worker is running, new shell/fix/tool requests are rejected with a short busy message.

The visible chat should not show trace paths or full raw tool arguments. Trace paths remain in logs and conversation metadata.

### 5.5 Observation Layers

Each confirmation-related event should produce separate shapes for the three consumers:

```text
model_observation:
  status, tool_name, decision, reason, compact result

user_summary:
  one or two short lines suitable for the chat stream

trace_payload:
  full tool name, args, permission decision, preview, user decision, result summary
```

This keeps the TUI from becoming noisy while still giving the provider enough state to avoid fabrication.

### 5.6 Permission Semantics

Use existing permission modes:

- `read-only`: read-only tools can run; writes are denied unless explicitly configured later.
- `workspace-write`: read and worktree write tools can run; dangerous tools require confirmation.
- `danger-full-access`: registered non-critical tools can run; critical destructive operations remain denied.
- `custom`: confirm by default until configured.

Tool-specific notes:

- `run_shell_command` continues to use ShellPolicy for command classification.
- `apply_patch`, `write_file`, and `edit_file` should support diff or file preview before confirmation when confirmation is required.
- `git` mutation operations must require confirmation or remain unimplemented.
- `memory_write`, `file_summary_refresh`, and review queue accept/reject should be confirmable when exposed by the active tool pool.
- `run_command` remains verification-scoped and must not become a general shell escape.

## 6. Data Flow

```text
User asks for a risky action
-> Provider emits tool_call
-> AgentLoop validates with ToolRegistry
-> PermissionPolicy returns confirm
-> AgentLoop returns needs_user_confirmation
-> TUI stores PendingToolConfirmation and asks user
-> User confirms or cancels
-> Runtime creates confirmed execution observation or rejected observation
-> Provider receives observation
-> Provider returns final user answer
-> Trace records confirmation lifecycle
```

This flow is also the contract for PTY tests.

## 7. Error Handling

- Invalid tool args produce `invalid_args` observations and do not ask the user for confirmation.
- Denied tools produce `rejected` observations and must not execute.
- Expired or mismatched confirmation ids are rejected.
- If the workspace changed before confirmation, write tools may revalidate or reject with a stale preview error.
- If confirmed execution fails, the tool returns a normal failed observation instead of hiding the failure.
- If the provider fails after a confirmation result, the TUI still shows the tool execution summary and records the provider failure separately.

## 8. Testing Plan

Unit tests:

- Permission gate builds `PendingToolConfirmation` for non-shell tools.
- Denied tools produce rejected observations without execution.
- Shell confirmation still respects ShellPolicy critical denial.
- Confirmation preview is bounded and excludes full raw payloads.
- Confirmed execution cannot be replayed twice.

TUI tests:

- `/status` displays `pending_tool` instead of only `pending_shell`.
- `取消` clears pending state and does not execute the tool.
- `确认` executes exactly one stored pending tool.
- Existing pending shell tests pass through the generic pending tool path.

Scenario and PTY tests:

- Natural language risky git request enters confirmation.
- Natural language memory write request enters confirmation when exposed.
- Natural language patch request shows confirmation or runs according to the active mode.
- After rejection, the final answer says the action was not executed.
- After confirmation, the final answer summarizes actual execution result.

Regression tests:

- Low-risk `list_dir`, `read_file`, `rg`, and `git status` still auto-run.
- `run_command` still only accepts declared verification commands.
- Dangerous shell commands remain blocked when ShellPolicy marks them critical.

## 9. Rollout Plan

1. Add generic confirmation models and unit tests.
2. Refactor current TUI pending shell state into pending tool state while preserving existing behavior.
3. Wire AgentLoop `confirm` decisions to the generic pending model.
4. Add resume handling for approve once and reject.
5. Update PTY and scenario tests.
6. Update `MendCode_开发方案.md` after implementation.

The first merged implementation should keep scope tight: one pending tool, approve once, reject, trace logging, and regression coverage. Persistent permissions and richer TUI configuration can be separate slices.

