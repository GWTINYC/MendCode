# Runtime-First Refactor Design

## Goal

MendCode will be refactored from a TUI-centered tool caller into a local Code Agent runtime. The model should obtain local facts through structured tools, the runtime should enforce permissions before execution, and every turn should be recoverable through compact session records and detailed traces.

## Product Boundary

The main product line remains the TUI Agent path. CLI repair remains a compatibility entry, not the architecture center. The refactor may change internal public interfaces as long as these user-visible behaviors remain true:

- Natural language requests can trigger model-selected tools.
- Low-risk local inspection can run without repeated confirmation.
- Write, install, network, destructive, and git-mutation actions are gated.
- Tool results are returned to the model before final answers.
- Conversation logs stay readable; full payloads stay in traces or viewers.
- Repairs are verified before being presented as successful.

## Architecture

The target shape is a runtime core with thin adapters around it:

```text
app/runtime/
  agent_runtime.py        # provider -> tool -> observation loop
  turn.py                 # turn summaries, tool call/result summaries
  context.py              # prompt context and compaction
  session_store.py        # session index, resume, compact summary

app/tools/
  registry.py             # only source of tool schema, risk, executor
  builtin/                # read/list/rg/git/shell/patch/write/edit/todo
  executor.py             # invoke registry tools through a shared envelope

app/permissions/
  policy.py               # read-only/workspace-write/danger-full-access policy
  shell.py                # shell command classifier feeding policy
  prompts.py              # allow once, deny, change mode

app/providers/
  openai_compatible.py    # protocol adapter only
  mock_provider.py        # deterministic parity scenarios

app/tui/
  controller.py           # TUI event -> runtime turn
  app.py                  # display and input only
```

Existing modules can move incrementally. Compatibility imports may remain while tests are migrated.

## Runtime Contract

One runtime turn follows this loop:

```text
User input
-> build provider request from compact session context
-> provider emits assistant text or tool calls
-> runtime validates allowed tools
-> PermissionPolicy authorizes, confirms, or denies
-> ToolRegistry executor returns structured observation
-> runtime appends assistant/tool messages
-> provider receives tool result
-> final response or next tool call
-> session log and trace are written
```

The runtime owns step budget, failure gating, permission outcomes, tool result forwarding, and trace emission. TUI must not directly execute shell commands except through the runtime controller path.

## Tool Registry Contract

ToolRegistry becomes the single source for:

- canonical name and aliases
- model-facing JSON schema
- required permission mode
- executor
- result envelope

Legacy `repo_status`, `detect_project`, and `show_diff` are read-only ToolRegistry tools. Remaining legacy tool paths must either move into ToolRegistry or be deleted after compatibility tests are migrated.

The first-class tool set is:

```text
read_file
list_dir
glob_file_search
rg / search_code
git
repo_status
detect_project
show_diff
run_shell_command
run_command
apply_patch
write_file
edit_file
todo_write
tool_search
session_status
```

`run_command` remains verification-only. General commands use `run_shell_command`.

## Permission Contract

The target permission modes are:

```text
read-only
workspace-write
danger-full-access
```

Current `safe/guided/full/custom` may remain as transitional aliases, but the runtime policy should reason in the target modes.

Policy inputs:

- tool spec required mode
- active session mode
- allowed tools for the current turn
- shell classifier result
- path boundary validation
- user confirmation state

Policy outcomes:

```text
allow
confirm
deny
```

Every non-allow outcome must become a structured observation so the model can recover instead of hallucinating.

## Session And Context

Session storage has two layers:

- readable conversation log for the user
- structured runtime trace for exact debugging

Provider context must not blindly replay full logs. It should include:

- compact recent messages
- compact tool summaries
- selected full tool outputs only when needed
- project instructions when present
- current repo status when explicitly requested or cached by the runtime

Long tool outputs stay in traces, with excerpts in conversation logs and prompt context.

## Mock Parity Harness

The refactor is only acceptable if a deterministic harness can prove the loop. Required scenarios:

- streaming text without tools
- read file roundtrip
- list directory roundtrip
- grep roundtrip
- multi-tool turn
- shell stdout roundtrip
- write allowed under workspace-write
- write denied under read-only
- confirmation required and denied
- confirmation approved and resumed
- final answer after tool results
- no final success when observations failed

The harness should not depend on a real model or network.

## Migration Strategy

1. Move all read-only legacy tools into ToolRegistry.
2. Extract PermissionPolicy as a standalone object and keep old mode names as aliases.
3. Introduce `AgentRuntime` and make `AgentLoop` a compatibility wrapper.
4. Split TUI controller from Textual rendering.
5. Add write/edit/todo/session tools under the same registry.
6. Add session index, resume, and trace viewer.
7. Expand mock parity scenarios before removing old compatibility paths.

## Acceptance Criteria

- All provider-visible tools are generated from ToolRegistry.
- AgentLoop no longer hardcodes common tool execution branches.
- Permission decisions are tested independently from TUI.
- TUI tool requests and natural-language requests both use the same runtime.
- Conversation logs stay compact while traces retain complete tool payloads.
- Full pytest and ruff pass after each migration slice.
