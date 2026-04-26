# TUI Experience Scenario Tests Design

## Goal

Build a scenario-driven test system that catches poor TUI conversation experience before manual use does.

The test system should simulate realistic user conversations, not only isolated functions. It must verify that MendCode routes common natural-language requests to the right agent/tool path, returns concise evidence-based answers, avoids irrelevant explanation, and does not fabricate local repository facts.

## Non-Goals

- Do not depend on a real LLM, network API, or user terminal.
- Do not build screenshot or pixel-level Textual tests in the first version.
- Do not replace existing unit tests for ToolRegistry, PermissionPolicy, provider adapters, or AgentLoop internals.
- Do not assert exact full transcript text unless the wording is intentionally stable.

## Testing Approach

Use in-process TUI scenario tests built on `MendCodeTextualApp.run_test()`.

Each scenario represents a small realistic conversation:

```text
given repo fixture
given deterministic fake provider/tool/chat behavior
when user sends one or more messages
then route, tool usage, conversation log, and visible answer satisfy experience rules
```

The first layer should be deterministic and fast enough for normal `pytest`. A later layer can add optional pseudo-terminal or screenshot tests after the core interaction rules stabilize.

## Core Components

### `TuiScenario`

Defines a user-facing scenario:

- `name`
- `repo_files`
- `inputs`
- fake tool/provider/chat responses
- expected route events
- expected visible message substrings
- forbidden visible message substrings
- output quality limits

Example scenario categories:

- directory listing
- file content question
- git status / diff inspection
- code search
- test failure repair request
- missing file or failed tool result
- repeated tool-call behavior
- resume context follow-up
- dangerous shell confirmation

### `TuiScenarioRunner`

Runs a scenario against `MendCodeTextualApp` and returns a `ScenarioTranscript`.

Responsibilities:

- create a temporary git repo fixture
- inject fake chat responder, fake tool agent runner, fake shell executor, and fake intent router when needed
- submit user inputs in order
- wait for running work to finish
- collect visible TUI messages
- collect conversation JSONL records
- collect compact `tool_result` payloads
- expose failure-friendly transcript text

### `ScenarioTranscript`

Stable read model for assertions:

- visible messages
- user messages
- assistant/system/tool/shell messages
- route events from conversation JSONL
- compact tool result steps
- chat responder calls
- shell executor calls
- tool agent runner calls

The transcript should be easy to print on failure. It should hide long payloads by default and include pointers to JSONL or trace paths when available.

### `ExperienceAssertions`

Shared assertions for TUI quality:

- `assert_used_tool_path()`
- `assert_did_not_use_chat()`
- `assert_visible_answer_contains()`
- `assert_no_fabricated_command_claims()`
- `assert_no_raw_trace_or_large_json_dump()`
- `assert_answer_is_concise(max_lines, max_chars)`
- `assert_tool_summary_is_compact(max_steps, max_lines)`
- `assert_has_evidence_from_observation(tool_name)`
- `assert_no_repeated_equivalent_tool_calls(limit)`

These assertions should fail with a readable transcript excerpt and a direct reason.

## Common User Question Coverage

The scenario suite should start broad enough to represent normal use, but keep each test small and deterministic.

### Repository Inspection

- "帮我查看当前文件夹里的文件"
- "列一下当前目录"
- "看下 git status"
- "看一下当前改了哪些文件"
- "项目是什么技术栈"

Expected behavior:

- route to tool/shell where appropriate
- use `list_dir`, `git`, `repo_status`, `detect_project`, or `show_diff`
- answer with a short summary and relevant entries only

### File Questions

- "README 第一段是什么"
- "MendCode_开发方案第一句话是什么"
- "这个文件里有没有提到 tool call"
- "帮我找一下配置 provider 的地方"

Expected behavior:

- discover files with `glob_file_search` or `list_dir` if needed
- read actual file content with `read_file`
- answer only from observation
- never invent file paths or content

### Code Search

- "哪里定义了 ToolRegistry"
- "搜索 run_shell_command"
- "哪些测试覆盖了 TUI intent"

Expected behavior:

- use `rg` / `search_code`
- summarize matches compactly
- avoid dumping full files unless asked

### Repair Flow

- "pytest 失败了，帮我修复"
- "这个报错帮我看下怎么改"

Expected behavior:

- route to fix flow, not casual chat
- require or infer verification command as designed
- show concise pending confirmation or review summary

### Failure And Ambiguity

- ask for a missing file
- ask for a dangerous shell command
- ask a vague question requiring clarification
- provider returns failed or repeated tool calls

Expected behavior:

- be honest about missing evidence
- request confirmation for risky work
- ask a short clarifying question when needed
- stop or fail clearly instead of producing a fabricated final answer

### Resume And Follow-Up

- `/sessions`
- `/resume <session_id>`
- "继续刚才那个问题"
- "刚才你读到的第一句话是什么"

Expected behavior:

- use compact resume context
- keep answer short
- distinguish restored context from newly executed tools

## Output Quality Rules

These are testable constraints for visible TUI responses:

- Simple answers should stay under 12 lines unless the user explicitly asks for detail.
- Tool result displays should show summaries and selected samples, not raw full JSON.
- A final answer should lead with the answer, not internal reasoning.
- The assistant must not claim it ran a command unless a shell/tool result exists in the transcript.
- The assistant must not mention fake paths, fake files, or fake command output.
- Missing evidence should be stated plainly in one or two sentences.
- Repeated equivalent tool calls should be flagged when they exceed a small threshold, initially 2 for identical read/list/search requests.

The first version can enforce these rules through heuristics. The wording rules should be intentionally conservative to avoid brittle exact-match tests.

## Data Flow

```text
TuiScenario
-> TuiScenarioRunner
-> MendCodeTextualApp.run_test()
-> fake responder / fake tool runner / fake shell executor
-> visible messages + conversation JSONL
-> ScenarioTranscript
-> ExperienceAssertions
```

The fake provider/tool runner should simulate realistic tool observations, including success, failure, repeated calls, and final responses. It should not call a real model.

## File Layout

Proposed files:

```text
tests/scenarios/
├── __init__.py
├── tui_scenario_runner.py
├── test_tui_repository_inspection_scenarios.py
├── test_tui_file_question_scenarios.py
├── test_tui_failure_scenarios.py
└── test_tui_resume_scenarios.py
```

Existing `tests/unit/test_tui_app.py` should keep low-level behavior tests. New scenario tests should focus on realistic user experience and readable transcripts.

## Failure Output

When a scenario fails, the assertion should show:

- scenario name
- user inputs
- visible transcript excerpt
- route events
- tool/shell/chat calls
- compact tool steps
- exact failed quality rule

This is important because the purpose is not only correctness; it is to make bad user experience obvious.

## Phased Implementation

### Phase 1: Harness And Smoke Scenarios

- Add `TuiScenarioRunner`
- Add transcript collection
- Add concise-output and routing assertions
- Cover directory listing, file question, tool failure, and resume context

### Phase 2: Common Question Suite

- Add repository inspection scenarios
- Add file/content scenarios
- Add code search scenarios
- Add repair flow routing scenarios
- Add dangerous shell confirmation scenario

### Phase 3: Regression Rules

- Add repeated equivalent tool-call detection
- Add no-fabrication assertions against known bad phrases
- Add golden compact transcript snapshots only for stable high-value cases

### Phase 4: Optional True E2E Layer

- Add slower pseudo-terminal or screenshot tests only for a small number of flows.
- Keep this optional so normal development remains fast.

## Acceptance Criteria

- Running the scenario suite does not require network access.
- At least 10 common user questions are represented by deterministic scenarios after Phase 2.
- Scenario failures explain whether the issue is routing, tool usage, output verbosity, missing evidence, or fabrication.
- Existing unit tests continue to pass.
- The suite makes it hard to regress into chat-only fabricated answers for local repository questions.

