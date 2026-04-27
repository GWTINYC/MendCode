# Schema Tool Call Only Design

## 1. Purpose

MendCode should let the model operate the local repository through structured tool calls, not through free-form answers, rule-triggered shell shortcuts, or JSON text actions.

Target loop:

```text
user natural language
-> TUI sends the request to AgentLoop
-> Provider exposes ToolPool-generated OpenAI function schemas
-> model emits tool_calls
-> Harness validates tool name, args, allowed tools, and permission
-> ToolRegistry executor runs the local tool
-> Observation returns to the model
-> model emits more tool_calls or final_response
```

The product goal is that local facts are always grounded in tool observations. If the model needs the file list, Git status, file content, search result, or a shell diagnostic, it must call a schema tool.

## 2. Scope

In scope:

- Natural-language TUI requests use the AgentLoop schema tool-call path.
- Tool exposure is controlled by `ToolPool` using permission mode and scenario scope.
- All model-callable tools are represented as `ToolSpec` with Pydantic args schemas.
- OpenAI-compatible provider requires native `tool_calls` for normal operation.
- The Harness dispatches `ToolInvocation` objects to `ToolRegistry` executors after permission checks.
- `final_response` is the model-facing way to finish a turn after tool use.
- Tests are updated so local-fact questions assert tool-call evidence, not rule-route evidence.

Out of scope for this slice:

- Adding LSP, MCP, plugin, notebook, or remote tools.
- Supporting non-OpenAI protocols.
- Long-running background tasks.
- Interactive shell sessions.
- Automatic commit or push.
- Replacing slash commands such as `/status`, `/sessions`, and `/resume`.

## 3. Product Rules

### 3.1 Natural language goes through tools

For normal user text, TUI should not directly execute a rule-planned shell command or tool call. The model receives the user request and the current schema tool set, then chooses tools.

Examples:

```text
帮我查看当前文件夹里的文件
-> model calls list_dir

看下 git status
-> model calls git or run_shell_command

MendCode_问题记录.md 的最后一句是什么
-> model calls read_file with tail_lines or reads a bounded range
```

The TUI can still keep lightweight classification for UI control, such as slash commands, empty input, pending confirmation replies, and worker-running rejection. It should not use classification to answer local facts without model tool calls.

### 3.2 Slash commands remain local controls

These are not model tasks and should stay local:

- `/status`
- `/sessions`
- `/resume <session_id>`
- future explicit TUI commands for logs, traces, or settings

Keeping slash commands local avoids wasting model turns on UI state operations.

### 3.3 Provider fallback should not fabricate

If the configured OpenAI-compatible endpoint rejects `tools` or cannot return native `tool_calls`, MendCode should fail clearly for tool-driven requests. It should not silently fall back to free-form chat for local facts.

Allowed fallback:

- A clear provider error observation.
- A TUI-visible message that the provider does not support tool calls.

Disallowed fallback:

- Treating arbitrary assistant text as a local-fact answer.
- Parsing JSON text actions as the normal execution path.
- Asking the model to describe shell commands without running them.

## 4. Architecture

### 4.1 ToolRegistry

`ToolRegistry` remains the source of tool definitions:

```text
ToolSpec
  name
  description
  args_model
  risk_level
  executor
```

Every model-callable tool must have:

- a stable public name
- a model-facing description
- a Pydantic args schema
- a risk level
- an executor that returns a structured `Observation`
- tests for valid args, invalid args, permission behavior, and observation shape

### 4.2 ToolPool

`ToolPool` is the only source for Provider-visible tools.

Recommended exposure:

- `read-only`: read-only tools only
- `guided` / `workspace-write`: read, write-worktree, restricted shell, patch, todo, tool search
- `danger-full-access`: maximum tool surface, still subject to tool-specific safety checks

The provider must not call `ToolRegistry.openai_tools()` directly for user turns. It must call `registry.tool_pool(...).openai_tools()`.

### 4.3 Provider

The OpenAI-compatible provider becomes a native tool-call adapter:

1. Build messages.
2. Build tools from `ToolPool`.
3. Send OpenAI-compatible request with `tools`.
4. Parse `tool_calls` into `ToolInvocation`.
5. Parse only `final_response` tool calls as final answers.
6. Return provider failure if no valid tool call or final response can be parsed.

JSON Action parsing should no longer be part of the normal user-turn flow. It may remain temporarily in tests during migration, but every remaining use must be marked as legacy and scheduled for deletion.

### 4.4 Harness

Harness means the AgentLoop execution boundary that receives normalized tool calls and runs tools.

Responsibilities:

- reject unknown tool names
- reject tools not in the current `allowed_tools` / ToolPool
- validate args with the tool args model
- run permission policy
- run shell policy for shell tools
- call the executor
- record action, observation, trace, and conversation log
- return tool result messages to the model

Harness should not:

- infer local facts itself
- repair invalid model arguments by guessing
- execute tools outside the current workspace root
- allow `run_command` outside declared verification commands

### 4.5 Final response

`final_response` should be a provider-local tool schema. The model ends a turn by calling it with:

```json
{
  "status": "completed",
  "summary": "concise answer grounded in observations",
  "recommended_actions": []
}
```

Free-form assistant text after tool observations can be tolerated only as a short-term compatibility bridge. The target state is that final answers also arrive through schema tool calls.

## 5. Migration Plan

### Phase 1: Make schema tool call the only natural-language path

- Route normal TUI user text to AgentLoop.
- Stop direct rule execution for `ls`, `git status`, file reads, and code search.
- Keep slash commands local.
- Keep pending confirmation replies local.
- Keep worker-running rejection local.

### Phase 2: Remove provider JSON Action fallback from normal flow

- OpenAI-compatible provider should require native `tool_calls`.
- If `tools` are unsupported, return a clear provider failure.
- Remove or quarantine `_response_from_action_text` from normal user-turn execution.
- Keep deterministic test helpers that return `ToolInvocation` directly.

### Phase 3: Make final_response a required tool

- Include `final_response` in every provider request, not only after observations.
- Require local-fact answers to happen after relevant observations.
- Reject final_response that claims local facts without tool evidence.

### Phase 4: Delete legacy action execution branches

- Remove JSON `{ "type": "tool_call" }` as a runtime path.
- Remove direct `_execute_tool_call` branches once all tools run through `ToolRegistry`.
- Keep only compatibility wrappers if CLI repair still depends on them, with explicit deprecation notes and tests.

### Phase 5: Update tests and PTY harness

- Convert TUI tests from route assertions to tool-call evidence assertions.
- PTY tests should inspect conversation JSONL for tool invocation and observation records.
- Add failure tests for providers without tool-call support.
- Add tests that ordinary local-fact prompts cannot be answered by chat-only paths.

## 6. Permission and Safety

Choosing "expose all available tools by permission" means:

- Tools visible to the model are broad enough for autonomous operation.
- Tools are still filtered by permission mode.
- Harness remains the final authority.

Rules:

- Read-only tools auto-run in read-only and higher modes.
- Workspace-write tools require at least guided/workspace-write mode and may still require confirmation.
- Shell tools always go through ShellPolicy.
- `run_command` stays verification-only.
- Destructive shell commands and workspace escape remain rejected.
- Provider-visible schema does not imply execution permission.

## 7. Testing Strategy

Required tests:

- Provider sends tools from `ToolPool`.
- Provider fails clearly when tool support is unavailable.
- Provider parses native tool calls into `ToolInvocation`.
- Provider parses `final_response` tool call.
- AgentLoop executes native tool calls through Harness and ToolRegistry.
- AgentLoop rejects disallowed tool calls before execution.
- TUI natural-language directory, Git, file-content, and search questions produce tool evidence.
- TUI no longer uses direct shell/tool rule execution for normal text.
- Conversation logs record tool call, observation, and final answer.
- PTY live tests still pass with a real provider.

Verification commands:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

## 8. Risks

### Risk: Provider cannot use tools

Some OpenAI-compatible endpoints may claim compatibility but reject `tools`. The new behavior should fail clearly. This is preferable to fabricated answers.

### Risk: More model turns

Removing rule shortcuts can make simple tasks slower. This is acceptable because the product goal is autonomous tool use, not command shortcut speed.

### Risk: Final response loops

If the model fails to call `final_response`, the loop may exhaust the step budget. Prompt contract and tests must make final_response usage explicit.

### Risk: Legacy repair flow disruption

Some repair paths may still depend on JSON actions or direct patch proposal parsing. Migration should either convert them to tools or leave them behind a clearly marked compatibility layer until the tool-only path covers repair.

## 9. Acceptance Criteria

- Normal natural-language TUI requests use schema tool calls for local facts.
- Provider-visible tools always come from `ToolPool`.
- The OpenAI-compatible provider no longer silently falls back from tools to JSON/free text for normal user turns.
- Tool execution goes through Harness permission and ToolRegistry executor dispatch.
- Final answers for local facts are grounded in prior observations.
- Legacy JSON action paths are removed from normal flow or explicitly quarantined as compatibility code with tests.
- Full pytest, ruff, and PTY live tests pass.
