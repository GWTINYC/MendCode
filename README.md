# MendCode

一款面向本地代码仓的可验证修复型 Code Agent。

MendCode 的目标形态是终端 TUI 工作台：用户输入 `mendcode` 进入聊天式界面，用自然语言描述问题，Agent 动态调用工具，在隔离 worktree 中完成修复、验证和工程审查收尾。

## Current Capabilities

- Python project skeleton with `pyproject.toml`
- CLI health check
- Minimal Agent Action Loop for tool calls, observations, permission decisions, and trace output
- Provider-driven Agent loop with scripted default and optional OpenAI-compatible JSON Action provider
- Secret-safe provider prompt context with a JSON Action repair contract
- Transitional `mendcode fix "<problem>" --test "<command>"` entry wired through the Agent loop
- Command-policy guarded verification execution with timeout and trace output
- Pytest-style failure insight extraction for failed verification output
- JSONL trace output for Agent loop runs

## Product Direction

The final user-facing entry is planned to be:

```bash
mendcode
```

The TUI should provide:

- chat-first natural language task input
- Guided Mode permission defaults
- model-driven MendCode Action loop
- worktree-isolated patching
- summary-first tool progress
- verification-gated completion
- diff/log/trace review before apply or discard

The current CLI commands are implementation slices and compatibility surfaces, not the final product shape.
The old fixed-flow task JSON, batch eval, and API surfaces have been removed from the mainline so development stays focused on the TUI Agent route.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

## CLI

Transitional agent-style verification:

```bash
mendcode fix "pytest 失败了，请定位并修复" --repo . --test "python -m pytest -q"
```

Compatibility and smoke commands:
Smoke commands:

```bash
mendcode version
mendcode health
```

In this nested worktree development setup, `python -m app.cli.main ...` is the authoritative invocation path. The `mendcode ...` examples remain valid for normal installed usage, but the branch-accurate commands are:

```bash
python -m app.cli.main version
python -m app.cli.main health
python -m app.cli.main fix "pytest 失败了，请定位并修复" --repo . --test "python -m pytest -q"
```

`fix` defaults to the scripted provider, then runs the Agent loop in an isolated git worktree over repository status, project detection, and the supplied verification command. It extracts pytest-style failure details, records trace output, and reports the worktree path. Patch proposal execution and diff summary are available inside the Agent loop and will be wired to model-driven repair next.

To try an OpenAI-compatible JSON Action provider, configure:

```bash
export MENDCODE_PROVIDER=openai-compatible
export MENDCODE_MODEL="<model>"
export MENDCODE_BASE_URL="<base-url>"
export MENDCODE_API_KEY="<key>"
```

This provider path asks the model for one MendCode Action JSON object per step. It uses a bounded prompt context with repair guidance for inspecting failures, proposing unified diff patches, rerunning verification, and avoiding unverified completion. It does not use native tool-calling formats yet.
