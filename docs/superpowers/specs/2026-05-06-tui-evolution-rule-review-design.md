# TUI Evolution Rule Review Design

## 1. Purpose

MendCode's self-evolution loop should be conversation-first. Users should not need to leave the TUI or run CLI commands to review and accept behavior improvements. The first self-evolution slice will focus on prompt-rule and tool-schema guidance candidates, then let users review them through natural language.

This design intentionally does not let MendCode automatically rewrite source prompts or tool schemas. It creates a safer middle layer:

```text
rule candidate
-> TUI natural-language review
-> explicit accept / reject / accept with edits
-> accepted rule store
-> relevant rule recall into AgentLoop context
```

The goal is to make failed task analysis actionable while keeping every durable change reviewable, traceable, and reversible.

## 2. Product Principle

The primary interface is the Textual TUI chat. CLI commands may exist later for debugging, but they are not the product path for this slice.

Target user interactions:

```text
有哪些待确认的规则？
查看第一条规则。
接受第一条规则。
拒绝第二条规则。
接受第一条，但改成：回答 Git 状态前必须调用 git 工具。
```

The model should satisfy these requests by calling schema tools. The TUI should show compact, user-readable summaries rather than raw JSON, trace paths, or long evidence payloads.

## 3. Scope

This first slice implements the rule review and runtime recall loop:

```text
Rule Candidate Queue
-> schema tools
-> TUI natural-language review
-> Rule Store
-> Runtime Rule Recall
-> provider context injection
```

It does not implement automatic proposal from the last session yet. That comes after the review loop works.

## 4. Rule Types

Accepted rules and candidates use four rule types:

```text
tool_required
observation_required
tool_schema_hint
answer_style
```

Meanings:

- `tool_required`: the model must call a specific tool group before answering a task class.
- `observation_required`: the model must not state local facts without a successful observation.
- `tool_schema_hint`: the model should choose a specific argument pattern or tool for a recurring task class.
- `answer_style`: the final answer should be shorter, narrower, or formatted in a specific way for a task class.

These map directly to recent failure patterns: missing tools, unsupported local claims, unclear tool choice, and overly verbose answers.

## 5. Data Model

Add an evolution rule model under the evolution domain.

### Rule Candidate

```text
EvolutionRuleCandidate
  candidate_id
  rule_type
  rule_text
  scope
  activation_hint
  source_report
  source_trace
  evidence
  root_cause
  status: pending | accepted | rejected
  created_at
  updated_at
```

`source_report`, `source_trace`, `evidence`, and `root_cause` are immutable review evidence. They must not be editable through TUI tools.

### Accepted Rule

```text
EvolutionRule
  rule_id
  candidate_id
  rule_type
  rule_text
  scope
  activation_hint
  evidence_ref
  source_report
  source_trace
  created_at
  updated_at
  status: active | disabled
```

Accepted rules are stored locally in:

```text
data/evolution/rules.jsonl
```

This path is a local runtime artifact and must not be committed.

## 6. Candidate Queue Strategy

Use the existing review-queue concept, but extend it for evolution targets rather than creating a separate queue system.

Candidate records should include:

```text
target_kind: rule
rule_candidate: EvolutionRuleCandidate
```

Future targets can include:

```text
memory
skill
prompt_rule
tool_schema
benchmark_case
```

For this slice, only `target_kind=rule` needs to be accepted into a durable artifact.

## 7. TUI-Visible Schema Tools

Expose these tools through `ToolRegistry` / `ToolPool`:

```text
evolution_rule_list
evolution_rule_view
evolution_rule_accept
evolution_rule_reject
evolution_rule_accept_with_edits
```

Tool behavior:

- `evolution_rule_list`: list pending rule candidates with compact summaries.
- `evolution_rule_view`: show one candidate with bounded evidence summary.
- `evolution_rule_accept`: accept a candidate without edits and write an accepted rule.
- `evolution_rule_reject`: reject a candidate and keep evidence traceable.
- `evolution_rule_accept_with_edits`: accept a candidate after user-edited `rule_text`, `scope`, or `activation_hint`.

Allowed edits:

```text
rule_text
scope
activation_hint
```

Forbidden edits:

```text
candidate_id
source_report
source_trace
evidence
root_cause
created_at
```

All write operations should require the same high-risk / confirmation path used for long-term memory updates, because accepted rules affect future model behavior.

## 8. Natural Language Flow

The TUI should remain chat-first. Users should not need slash commands.

Example list flow:

```text
User: 有哪些待确认的规则？
Model tool call: evolution_rule_list
TUI: 发现 2 条待确认规则：
  1. [observation_required] 回答本地文件/Git/目录事实前必须有成功 observation
  2. [answer_style] 用户问最后一句时只回答最后一句，不要返回全文
```

Example accept-with-edits flow:

```text
User: 接受第一条，但改成：回答 Git 状态前必须调用 git 工具。
Model tool call: evolution_rule_accept_with_edits
TUI: 已接受规则：
  [tool_required] 回答 Git 状态前必须调用 git 工具。
```

The visible TUI output should not expose raw trace paths, raw JSON, or full evidence. Trace/report references remain in the tool payload and local artifacts.

## 9. Runtime Rule Recall

Accepted rules should affect future AgentLoop turns through relevant recall, not fixed injection.

Input:

```text
user_message
accepted active rules
```

Ranking signals:

- scope keyword hit
- activation hint keyword hit
- rule text keyword hit
- rule type relevance
- recency as a small tie-breaker

Output:

```text
top 3 accepted rules
bounded character budget
```

Provider context injection format:

```text
Accepted Evolution Rules:
- [tool_required] When user asks git status, call git or run_shell_command before answering.
- [observation_required] Do not state local repository facts unless supported by a successful observation.
```

The recall layer should live near context/memory runtime boundaries, not inside the TUI.

## 10. Safety And Review Boundaries

- Pending candidates do not affect Agent behavior.
- Only accepted active rules can be recalled into provider context.
- Accepted rules live under `data/evolution/rules.jsonl`.
- Rule evidence is immutable through TUI tools.
- `accept_with_edits` can only edit text/scope/hint fields.
- Rule injection is capped by count and character budget.
- If rule storage or recall fails, the current user turn must not fail; it should degrade gracefully and record a compact error.

## 11. Integration With Session Analysis

This slice does not automatically generate candidates from a session analysis report. It prepares the review and recall path that those candidates will use.

The next slice can add:

```text
evolution_propose_rules_from_report
evolution_propose_rules_from_last_session
```

Those tools can map `SessionAnalysisReport` findings to `EvolutionRuleCandidate` records:

- missing expected tool -> `tool_required`
- unsupported local claim -> `observation_required`
- missing argument pattern -> `tool_schema_hint`
- oversized final answer -> `answer_style`

## 12. Testing Strategy

Unit tests:

- Rule store append/list/read.
- Candidate accept/reject state transitions.
- `accept_with_edits` changes only allowed fields.
- Immutable evidence fields cannot be modified.
- Relevant recall returns top 3 and respects budget.

Tool tests:

- `evolution_rule_list` returns compact pending candidates.
- `evolution_rule_view` returns bounded evidence.
- `evolution_rule_accept` writes an accepted rule.
- `evolution_rule_reject` does not write a rule.
- `evolution_rule_accept_with_edits` writes edited text/scope/hint while preserving evidence.
- Write tools go through permission policy.

Agent/context tests:

- Accepted rules relevant to `git status` are injected into provider context.
- Irrelevant rules are not injected.
- Pending or rejected rules are not injected.
- Recall failure does not fail the turn.

TUI/scenario tests:

- User asks "有哪些待确认的规则" and model calls `evolution_rule_list`.
- User says "接受第一条" and model calls `evolution_rule_accept`.
- User says "接受第一条，但改成..." and model calls `evolution_rule_accept_with_edits`.
- Visible output does not leak raw trace path or raw JSON evidence.

## 13. Acceptance Criteria

- TUI-facing schema tools can list, view, accept, reject, and accept-with-edits rule candidates.
- Accepted rules are persisted to `data/evolution/rules.jsonl`.
- Accepted rules are recalled by relevance and injected into provider context with top-3 and character budget limits.
- Pending and rejected candidates do not affect Agent behavior.
- Evidence remains immutable during edit-and-accept.
- Tests cover store, tools, recall, context injection, and TUI natural-language review flows.
- Documentation explains this as the first TUI-first self-evolution loop, not as a CLI-first workflow.

## 14. Non-Goals

- No automatic source prompt or tool schema rewriting.
- No full SKILL.md loader in this slice.
- No automatic proposal from the last session in this slice.
- No vector database or embedding search.
- No benchmark-driven auto-accept.
- No raw evidence display in the TUI chat stream.
