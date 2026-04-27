# Tool Pool Expansion Design

## 1. Purpose

MendCode already has the minimum schema tool-call loop for local repository work:

```text
natural language
-> AgentLoop
-> OpenAI-compatible tool_calls
-> ToolRegistry executor
-> Observation
-> final_response
```

The next step is to make the tool pool closer to mainstream coding agents without turning MendCode into a broad personal-assistant platform. The immediate product goal is stronger autonomous code investigation:

- the model can inspect its current session and available tool surface
- the model can run long-lived commands without blocking the TUI
- the model can use language-server facts instead of guessing from text search
- the loop can detect repeated equivalent tool calls before context is wasted
- future subagent, MCP, web, and browser tools have clear extension points

This spec defines the first implementation slice and the larger tool roadmap.

## 2. External Baseline

This design compares MendCode against the tool surfaces exposed by Claude Code, OpenClaw, Hermes, and the local reference implementation under `data/claw-code`. Mainstream coding agents converge on several tool families:

- File tools: read, write, edit, multi-edit, glob, grep.
- Runtime tools: shell, background process, process output polling.
- Code intelligence: diagnostics, definitions, references, symbols, hover.
- Planning/session tools: todo, task state, session metadata, compact context.
- Delegation: subagents or task agents.
- Extensibility: MCP tools/resources, custom CLI/HTTP/plugin tools.
- Web/browser: search, fetch, browser automation.
- Safety: permission modes, allow/deny rules, command validation, path boundaries.

MendCode already covers much of the file/search/git/shell/write base. The largest gaps for a code-focused agent are process management, LSP, session introspection, and loop control.

Reference inputs:

- Claude Code tools reference: `https://code.claude.com/docs/en/tools-reference`
- OpenClaw tools: `https://openclaw.cc/en/tools/`
- Hermes tool use: `https://hermes-agent.ai/features/tool-use`
- Local reference notes: `data/claw-code/PARITY.md`, `data/claw-code/rust/crates/runtime/src/permissions.rs`

## 3. Current MendCode Tool Surface

Current ToolRegistry tools:

| Tool | Category | Status |
|---|---|---|
| `read_file` | file/read | implemented |
| `list_dir` | file/read | implemented |
| `glob_file_search` | file/read | implemented |
| `rg` / `search_code` | search | implemented |
| `repo_status` | git/read | implemented |
| `git` | git/read | `status`, `diff`, `log` only |
| `show_diff` | git/read | compact diff stat |
| `detect_project` | project | implemented |
| `run_shell_command` | shell | restricted shell policy |
| `run_command` | verification | declared verification only |
| `apply_patch` | write | unified diff |
| `write_file` | write | complete file write |
| `edit_file` | write | exact string replace |
| `todo_write` | planning | replace short todo list |
| `tool_search` | introspection | search visible tools |

Provider-local tool:

| Tool | Category | Status |
|---|---|---|
| `final_response` | completion | implemented |

Important constraints already in place:

- Provider-visible tools come from `ToolPool`.
- Normal TUI text goes through schema tool calls.
- Local facts need tool evidence.
- Shell and verification execution are intentionally separate.
- Conversation logs compact tool output and keep trace paths in the background.

## 4. First Implementation Slice

This slice should add five capabilities:

1. `session_status`
2. tool groups / profiles
3. repeated tool-call detection
4. process tools
5. LSP tools

It should not add MCP, web search, browser automation, or subagents yet. Those need the same foundation but have wider security and UX implications.

## 5. Tool: `session_status`

### Goal

Let the model inspect the current runtime state without asking the user or guessing from prompt text.

### Schema

```python
class SessionStatusArgs(BaseModel):
    include_tools: bool = True
    include_recent_steps: bool = True
```

### Observation Payload

```json
{
  "repo_path": "/repo",
  "workspace_path": "/repo",
  "permission_mode": "guided",
  "allowed_tools": ["read_file", "list_dir"],
  "available_tools": ["read_file", "list_dir", "rg"],
  "denied_tools": [],
  "verification_commands": ["python -m pytest -q"],
  "pending_confirmation": null,
  "last_trace_path": "data/traces/agent-xxx.jsonl",
  "recent_steps": [
    {"index": 1, "action": "read_file", "status": "succeeded"}
  ]
}
```

### Rules

- Risk level: `READ_ONLY`.
- No secrets, API keys, full environment variables, or full tool payloads.
- Paths should be repo/workspace paths only.
- If a field is unavailable, return `null` or an empty list instead of failing.

### Tests

- Unit: schema generation and observation shape.
- Unit: respects current `available_tools`.
- AgentLoop: model can call `session_status` then `final_response`.
- TUI scenario: user asks "现在你能用哪些工具" and result is tool-backed.

## 6. Tool Groups and Profiles

### Goal

Give ToolPool a stable grouping layer so future prompts, tests, and permission decisions can talk about tool sets without duplicating lists.

### Groups

```text
fs_read:
  read_file, list_dir, glob_file_search, rg, search_code

fs_write:
  apply_patch, write_file, edit_file

git_read:
  repo_status, git, show_diff

runtime:
  run_shell_command, run_command

planning:
  todo_write

introspection:
  tool_search, session_status

process:
  process_start, process_poll, process_write, process_stop, process_list

lsp:
  lsp
```

### Profiles

```text
read_only_agent:
  fs_read, git_read, introspection, lsp

coding_agent:
  fs_read, fs_write, git_read, runtime, planning, introspection, lsp, process

repair_agent:
  coding_agent plus declared run_command emphasis

simple_chat_tool_agent:
  fs_read, git_read, introspection
```

### Rules

- Groups are expansion aliases, not separate executable tools.
- `allowed_tools` should accept both individual tools and group names.
- Group expansion must still pass permission filtering.
- `tool_search` must search only the final visible pool.

### Tests

- `ToolRegistry.names(allowed_tools={"fs_read"})` expands correctly.
- Unknown group fails clearly.
- Permission mode filters high-risk tools after group expansion.
- `tool_search` does not list tools excluded by profile or permission.

## 7. Repeated Tool-Call Detection

### Goal

Prevent wasted context when the model repeats equivalent `list_dir`, `read_file`, `rg`, `git`, or `session_status` calls.

### Design

Add a lightweight tool-call fingerprint to AgentLoop:

```text
fingerprint = tool_name + normalized_args + workspace_path + relevant_result_identity
```

Suggested normalization:

- sort JSON args
- normalize default values
- normalize paths relative to workspace
- ignore non-semantic args such as `max_results` only when the result was not truncated

When a repeated equivalent call exceeds the threshold, AgentLoop should not execute it again. It returns a structured observation:

```json
{
  "tool_name": "read_file",
  "status": "rejected",
  "summary": "Repeated equivalent tool call",
  "payload": {
    "repeat_count": 3,
    "previous_step": 4,
    "suggestion": "Use the previous observation or call final_response."
  },
  "error_message": "equivalent tool call repeated too many times"
}
```

### Defaults

- Allow one repeated equivalent call.
- Reject the third equivalent call.
- Apply first to read-only tools and `session_status`.
- Do not apply to write tools until write idempotency is explicit.

### Tests

- Repeated identical `read_file` third call is rejected.
- Same `read_file` with different line range is allowed.
- Same `rg` with different query is allowed.
- Rejection observation is passed back to provider.
- TUI scenario catches no more than two equivalent calls.

## 8. Process Tools

### Goal

Support long-running commands, dev servers, watch tests, and incremental logs without abusing `run_shell_command`.

### Tools

```python
process_start(
    command: str,
    cwd: str = ".",
    name: str | None = None,
    timeout_seconds: int | None = None,
    pty: bool = False,
    background: bool = True,
)

process_poll(
    process_id: str,
    offset: int | None = None,
    max_chars: int = 12000,
)

process_write(
    process_id: str,
    input: str,
)

process_stop(
    process_id: str,
    signal: Literal["term", "kill"] = "term",
)

process_list()
```

### Process State

Add a process registry under runtime/session state:

```text
process_id
command
cwd
started_at
status: running | exited | timed_out | stopped | failed
exit_code
stdout_log_path
stderr_log_path
last_activity_at
owner_run_id
```

Logs should live under `data/processes/` or `data/runs/<run_id>/processes/`.

### Permission

- Risk level: `SHELL_RESTRICTED`.
- `process_start` uses `ShellPolicy`.
- `process_write` requires the process to be owned by the current session/run.
- `process_stop` is allowed for owned processes.
- Network/install/write commands follow existing shell confirmation policy.
- Processes must be cleaned up when the run exits unless explicitly marked persistent in a future design.

### Output Handling

- `process_start` returns metadata and first output excerpt only.
- `process_poll` returns incremental output with offsets.
- Large logs stay on disk and are referenced by path.
- Conversation log stores compact summaries; trace stores full metadata.

### Tests

- Start `python -c "print('hello')"` and poll output.
- Start a sleeping command and stop it.
- Nonexistent process poll returns rejected.
- Dangerous command requires confirmation or is rejected.
- Process logs are truncated in TUI and full output remains in trace/log files.

## 9. LSP Tool

### Goal

Give the model code intelligence beyond grep so it can answer "where is this symbol defined", "what references this function", and "what diagnostics exist" with structured evidence.

### Tool

Use one tool with typed operation:

```python
lsp(
    operation: Literal[
        "diagnostics",
        "definition",
        "references",
        "hover",
        "document_symbols",
        "workspace_symbols",
        "implementations",
    ],
    path: str | None = None,
    line: int | None = None,
    column: int | None = None,
    query: str | None = None,
    max_results: int = 50,
)
```

### Backend

First implementation should keep the backend narrow:

- Python: `pyright-langserver` or `basedpyright-langserver` if available.
- TypeScript/JavaScript: `typescript-language-server` if available.
- If no matching server is installed, return a clear rejected observation with suggested install command, but do not install automatically.

### Runtime

Add a small LSP client manager:

```text
language id -> server command
workspace_path -> server process
request timeout
document open/cache state
```

The client manager may internally reuse process infrastructure, but it should expose LSP results through `lsp`, not through generic shell output.

### Observation Payload

```json
{
  "operation": "definition",
  "path": "app/main.py",
  "line": 12,
  "column": 8,
  "results": [
    {
      "relative_path": "app/config/settings.py",
      "start_line": 20,
      "start_column": 4,
      "end_line": 20,
      "end_column": 17,
      "symbol": "Settings"
    }
  ],
  "truncated": false
}
```

### Fallback

If LSP is unavailable:

- Return `status="rejected"` with `error_message="language server unavailable"`.
- Do not silently fall back to `rg` inside the tool.
- The model can decide to call `rg` after seeing the rejection.

### Tests

- Unit: args validation for operations.
- Unit: unavailable server returns rejected.
- Integration with fake LSP server for `definition` and `diagnostics`.
- AgentLoop: model calls `lsp`, receives observation, then final_response.
- TUI scenario: "这个函数在哪里定义" must have `lsp` or explicit fallback evidence.

## 10. Future Tool Roadmap

### Subagent Tools

Future tools:

```text
agent_spawn
agent_status
agent_send
agent_stop
agent_list
```

Rules:

- child agents default to read-only or isolated worktree
- child output returns compact summaries only
- no recursive spawn in first version

### MCP Tools

Future tools:

```text
mcp_list_servers
mcp_list_tools
mcp_call_tool
mcp_list_resources
mcp_read_resource
```

Rules:

- disabled by default until configured
- server/tool allowlist required
- external tool output gets the same observation envelope

### Web Tools

Future tools:

```text
web_search
web_fetch
```

Rules:

- network permission required
- cite URLs in final answers
- protect against prompt injection in fetched pages

### Browser Tools

Future tools:

```text
browser_start
browser_open
browser_snapshot
browser_click
browser_type
browser_press
browser_screenshot
browser_close
```

Rules:

- separate permission class from shell
- no credential entry without explicit user approval
- screenshots and DOM snapshots must be bounded

### File Operation Tools

Future tools:

```text
multi_edit
move_file
delete_file
create_dir
```

Rules:

- use structured file tools instead of shell `mv`, `rm`, and `mkdir`
- reject path escape
- delete should require confirmation outside isolated worktrees

## 11. Implementation Order

Recommended batches:

1. `session_status`, tool groups, and ToolPool profile tests.
2. repeated tool-call detection in AgentLoop.
3. process registry and `process_start/process_poll/process_stop/process_list`.
4. minimal `lsp` with unavailable-server behavior and fake-server integration tests.
5. TUI scenario and PTY coverage for the new tools.
6. Update README, `MendCode_开发方案.md`, and `MendCode_问题记录.md`.

This order keeps the foundation testable before adding process and LSP complexity.

## 12. Testing Strategy

Focused tests:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tool_registry.py tests/unit/test_agent_loop.py -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/scenarios -q
```

Full verification:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

New scenario prompts should include:

- "现在你能用哪些工具"
- "启动一个简单服务并查看输出"
- "停止刚才启动的服务"
- "这个函数在哪里定义"
- "这个文件有什么诊断问题"
- repeated local fact question that would otherwise call `read_file` three times

## 13. Acceptance Criteria

The slice is complete when:

- `session_status` is exposed through ToolRegistry and works in read-only mode.
- Tool groups/profiles can drive `ToolPool` exposure without duplicating lists.
- repeated equivalent read-only calls are blocked with a structured observation.
- process tools can start, poll, list, and stop a background command under shell policy.
- `lsp` returns structured diagnostics/definition data when a server is available and a clear rejection when unavailable.
- TUI scenarios assert tool evidence and concise answers for new capabilities.
- No new normal natural-language rule bypass is introduced.
- Full pytest, ruff, and PTY live verification pass.

## 14. Out of Scope

Not included in this implementation slice:

- subagent execution
- MCP server lifecycle
- web search/fetch
- browser automation
- notebook editing
- automatic commit/push
- installing language servers automatically
- long-term persistent daemon management

These should be designed after process and session-state foundations are stable.
