# MendCode

MendCode is a local TUI Code Agent for repository inspection, repair, verification, and review. It runs from the current repo, accepts natural-language requests, lets the model call structured tools, executes those tools under local safety rules, and records the conversation for later review.

The current product direction is:

```text
natural language
-> intent routing
-> model tool call
-> local permission gate
-> structured tool execution
-> observation returned to the model
-> grounded final answer or verified repair
```

## Current Status

MendCode currently supports the early TUI Agent workflow:

- Natural-language chat, shell, tool, and repair routing.
- OpenAI-compatible native `tool_calls` as the primary model-tool path.
- JSON Action fallback for providers or endpoints that reject tools.
- Structured tools including `read_file`, `list_dir`, `glob_file_search`, `rg` / `search_code`, read-only `git`, `run_shell_command`, `run_command`, `apply_patch`, `repo_status`, `detect_project`, and `show_diff`.
- Scoped tool exposure through `allowed_tools`, so read-only requests do not expose write tools.
- Guided permission mode with low-risk read-only actions auto-run and risky commands confirmed or rejected.
- Verification-only `run_command`, separated from general shell execution.
- Conversation logs in Markdown and JSONL under `data/conversations/`.
- Trace output for AgentLoop actions.
- Worktree-based repair path and review actions.

This is not yet a polished full product. The main engineering focus is stabilizing the Agent runtime, tool registry, permission policy, and session replay path.

## Quick Start

Install dependencies and run the test suite:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Start the TUI from a repository:

```bash
mendcode
```

Useful examples inside the TUI:

```text
帮我查看当前文件夹里的文件
读取 README.md 的前几行
看下 git status
pytest 失败了，帮我修复
```

Direct CLI repair remains a transitional entrypoint:

```bash
mendcode fix "fix the failing test" --test "python -m pytest -q"
```

## Provider Configuration

The actively supported model path is OpenAI-compatible chat completions.

Expected environment variables:

```bash
export MENDCODE_PROVIDER=openai-compatible
export MENDCODE_MODEL="your-model"
export MENDCODE_BASE_URL="https://your-provider.example/v1"
export MENDCODE_API_KEY="your-api-key"
```

API keys must stay outside the repository. Prefer environment variables or local user configuration.

## Architecture Map

```text
app/
├── agent/          # AgentLoop, provider adapters, prompt context, permissions, sessions
├── tools/          # ToolRegistry, tool schemas, read-only and patch tools
├── tui/            # Textual UI, intent routing, conversation logging
├── workspace/      # shell policy/executor, verification executor, worktree helpers
├── schemas/        # MendCodeAction, Observation, trace and verification schemas
└── tracing/        # JSONL trace recorder
```

Key runtime contracts:

- `ToolRegistry` is the source of tool schemas, risk levels, and executors.
- `AgentLoop` is the execution boundary and must re-check allowed tools before running native tool calls.
- `PermissionPolicy` logic must remain centralized; avoid duplicating risk tables.
- Tool observations must be structured enough to pass back to the model and to persist in logs.
- Local facts must come from tools, not from ordinary chat text.

## Documentation

The root documentation set is intentionally small:

- `README.md`: project overview, setup, current status, and navigation.
- `MendCode_全局路线图.md`: concise long-term direction and phase priorities.
- `MendCode_开发方案.md`: detailed implementation state, subsystem contracts, and next tasks.
- `MendCode_问题记录.md`: architecture-relevant issues and constraints.

After every development round, update `MendCode_开发方案.md` when implementation reality changes. Update the roadmap only when the high-level direction or phase priority changes. Update the issue log when a new recurring risk or architectural constraint is discovered.

## Data Directory

`data/` is for local runtime artifacts, not source code:

- `data/conversations/`: Markdown and JSONL conversation logs.
- `data/traces/`: AgentLoop traces.
- `data/reference-*` or other local analysis clones: reference material, ignored by git.

Do not commit runtime logs or cloned reference repositories.

## Development Rule

Every meaningful change should preserve the core loop:

```text
model requests tool
-> MendCode validates permissions
-> MendCode executes locally
-> observation returns to model
-> final answer or repair is grounded in evidence
```

If a change makes this loop weaker, it should not be merged.
