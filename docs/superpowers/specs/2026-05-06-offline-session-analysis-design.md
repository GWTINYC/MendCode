# Offline Session Analysis Design

## 1. Purpose

MendCode needs an offline analysis loop for failed or inefficient conversations. The first version should help developers answer:

- What did the user ask?
- Which tools should have been called?
- Which tools were actually called?
- Did any tool call fail, repeat, or get ignored?
- Did the final answer rely on local observations, or did it fabricate local facts?
- Did the turn waste context by returning full files, long logs, or repeated observations?
- What should be improved next: memory, skill, prompt rule, tool schema, permission policy, or benchmark coverage?

This feature is analysis-first. It does not change AgentLoop behavior directly. It produces structured evidence that later benchmark, memory, and evolution flows can consume.

## 2. Command

Add a CLI entry:

```bash
mendcode trace analyze-session <path>
```

Supported examples:

```bash
mendcode trace analyze-session data/conversations/2026-04-27_160326-323e138850fe.md
mendcode trace analyze-session data/traces/session.jsonl
mendcode trace analyze-session data/conversations/session.md --output-dir data/analysis-reports
mendcode trace analyze-session data/traces/session.jsonl --format json
```

Arguments:

- `<path>`: a repo-relative or absolute path to a conversation Markdown file or JSONL trace file.
- `--output-dir`: defaults to `data/analysis-reports`.
- `--format`: `json`, `md`, or `both`; defaults to `both`.
- `--llm`: reserved for a later evidence-grounded natural language summary. The first implementation may reject this flag with a clear "not implemented" message.

Default outputs:

```text
data/analysis-reports/<session-id>.json
data/analysis-reports/<session-id>.md
```

## 3. Architecture

Add a small standalone package:

```text
app/runtime/session_analysis/
  __init__.py
  models.py
  parsers.py
  analyzer.py
  renderer.py
```

Responsibilities:

- `models.py`: Pydantic models for normalized session events and final reports.
- `parsers.py`: Markdown and JSONL parsers that normalize raw files into the same session model.
- `analyzer.py`: deterministic rule engine that derives findings from normalized events.
- `renderer.py`: JSON and Markdown report rendering.

The CLI should only handle argument parsing, path resolution, and file output. Parsing, analysis, and rendering rules must stay in the runtime package so tests and later benchmark integration can call them directly.

## 4. Input Model

Both input formats should normalize into a shared internal structure:

```text
SessionTranscript
  session_id
  source_path
  input_kind: conversation_markdown | jsonl_trace
  user_messages[]
  assistant_messages[]
  tool_calls[]
  observations[]
  final_answer
```

`ToolCallEvent` should keep:

```text
tool_name
arguments_excerpt
arguments_fingerprint
call_index
status
requires_confirmation
risk_level
duration_ms
```

`ObservationEvent` should keep:

```text
tool_name
status
stdout_excerpt
stderr_excerpt
content_excerpt
exit_code
error_excerpt
visible_chars
raw_excerpt
```

The parser should be conservative. If it cannot confidently extract a field, it should leave the field empty and preserve a raw excerpt rather than inventing structure.

## 5. Parser Behavior

### Markdown Conversation Parser

The Markdown parser targets files under `data/conversations/*.md`. It should detect:

- user messages
- assistant messages
- visible command/tool blocks when present
- final assistant answer
- long visible outputs

Because conversation Markdown may be lossy, this parser is allowed to return partial evidence. It should still detect high-value symptoms such as "local factual answer with no observed tool" and "assistant returned a very long file excerpt".

### JSONL Trace Parser

The JSONL parser targets trace files emitted by MendCode runtime. It should detect:

- tool call events
- tool observations
- permission confirmation / rejection events
- final response events
- provider or tool errors

JSONL should be treated as the more authoritative source when both trace and conversation evidence exist in future integrations.

## 6. Analysis Rules

The first version is deterministic and rule-based.

### Expected Tools

Infer expected tools from user messages:

- Directory listing requests: `list_dir` or `run_shell_command`.
- Current directory requests: `repo_status`, `list_dir`, or `run_shell_command`.
- Git status requests: `git` or `run_shell_command`.
- File content questions: `read_file`.
- "Last sentence", "last line", "tail", or "最后一句": `read_file` with tail or line range.
- Code search requests: `rg`, `search_code`, or `glob_file_search`.
- Patch or repair requests: `read_file`, `apply_patch`, and a verification tool.
- Dangerous shell requests: permission or risk event should exist.

This inference is intentionally approximate. Reports should label it as "expected by heuristic".

### Missing Tools

`missing_tools` is derived from expected tool groups that have no acceptable observed equivalent.

Example:

- User asks "查看 git 状态".
- No `git` or `run_shell_command` observation exists.
- Report should mark missing `git_or_shell_status`.

### Repeated Tools

Detect repeated calls by `(tool_name, arguments_fingerprint)`.

Flag when the same read-only call appears more than once without new user input or changed context. Repeated failed calls should be highlighted more strongly because they often precede fabricated answers.

### Failed Tools

Flag observations with status:

- `failed`
- `rejected`
- `timed_out`
- `permission_required`
- `needs_user_confirmation`

The report should distinguish expected confirmation from actual failure.

### Oversized Outputs

Flag:

- final assistant answer over a configurable visible character threshold
- tool observation visible text over threshold
- Markdown conversation sections that appear to contain full file dumps

Initial defaults:

- final answer threshold: 3000 visible chars
- observation threshold: 6000 visible chars

These are intentionally conservative and can be tuned after benchmark data exists.

### Unsupported Claims

Flag likely fabrication when:

- The final answer states local repository facts but no relevant tool observation exists.
- The relevant tool failed or was rejected, but the final answer is still certain.
- The user asked for a precise local fact, but the answer is not grounded in a successful observation.

The report should avoid claiming "definite fabrication" unless evidence is strong. Prefer labels such as `unsupported_local_claim` and include the supporting reason.

### Risk Events

Detect:

- dangerous command requested
- confirmation required
- user confirmed
- user cancelled
- command denied
- path escape or destructive command denied

The report should verify that dangerous operations are not silently executed.

### Recommendations

Map findings to improvement targets:

- Missing expected tool: `prompt_rule` or `tool_schema`.
- Tool failure then final certainty: `prompt_rule` and `final_response_gate`.
- Repeated reads: `memory` or `context_compaction`.
- Oversized output: `context_compaction` or `tui_rendering`.
- Dangerous command behavior: `permission_policy`.
- Repeated task pattern: `skill`.
- Missing benchmark coverage: `benchmark_case`.

## 7. Output Model

`SessionAnalysisReport` should include:

```text
session_id
source_path
input_kind
user_messages
final_answer_excerpt
tool_calls
observations
expected_tools
observed_tools
missing_tools
repeated_tools
failed_tools
oversized_outputs
unsupported_claims
risk_events
root_causes
recommendations
confidence
```

`confidence` should be lower for Markdown-only reports and higher for JSONL trace reports.

## 8. Markdown Report

The Markdown report should be readable without opening the JSON. Suggested sections:

```text
# MendCode Session Analysis

## Summary
## User Request
## Expected Tool Chain
## Actual Tool Chain
## Missing / Repeated / Failed Tools
## Observation Grounding
## Context Waste
## Permission And Risk Events
## Root Causes
## Recommendations
```

Keep excerpts bounded. Do not paste full conversation logs or full tool outputs into the report.

## 9. LLM-Assisted Layer

The first implementation should reserve the `--llm` option but keep the core rule engine independent of model calls.

Future `--llm` behavior:

```text
rule evidence
-> compact evidence packet
-> model summary prompt with strict "do not add facts" contract
-> natural language root-cause summary
```

LLM output must not overwrite rule-derived fields. It may only add an optional narrative summary.

## 10. Testing

Add unit coverage for:

- Markdown conversation with "当前文件夹有哪些文件" and no tool call: missing `list_dir` / shell-style expected tool and unsupported local claim.
- Markdown conversation asking for a document's last sentence but returning excessive content: oversized final answer.
- JSONL trace with repeated failed tool calls followed by a certain final answer: repeated tools, failed tools, unsupported claim.
- JSONL trace where user asks for git status but no git or shell observation exists: missing expected tool.
- JSON and Markdown renderer produce bounded reports.
- CLI writes expected files to a temporary output directory.

Do not rely on live provider calls. Test fixtures should be deterministic.

## 11. Integration Path

After this offline analyzer is implemented:

1. Benchmark and PTY scenario failures can call `analyze-session` automatically.
2. `EvolutionRuntime` can consume `report.json` to generate lesson candidates.
3. Review queue can show analysis reports as evidence.
4. Later TUI commands such as `/analyze-last` can reuse the same analyzer without duplicating logic.

## 12. Non-Goals

The first version does not:

- Fix AgentLoop behavior directly.
- Automatically write memories or skills.
- Call an LLM by default.
- Parse every historical conversation format perfectly.
- Store raw full conversations inside reports.

## 13. Acceptance Criteria

- `mendcode trace analyze-session <conversation.md>` writes bounded JSON and Markdown reports.
- `mendcode trace analyze-session <trace.jsonl>` writes bounded JSON and Markdown reports.
- Reports expose expected, observed, missing, repeated, failed, oversized, unsupported-claim, risk, root-cause, and recommendation fields.
- Unit tests cover both input kinds and renderer behavior.
- The implementation does not commit files under `data/`.
- Documentation is updated after implementation to show the new command and its role in the memory/self-evolution loop.
