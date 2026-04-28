# Context + Memory + Evolution Runtime Framework Design

## 1. Purpose

MendCode already has the core schema tool-call loop, ToolRegistry, PermissionPolicy, JSONL trace, conversation log, and a first slice of layered memory. The next step is to make these capabilities part of a coherent runtime framework instead of leaving context assembly, memory recall, observation tracking, and trace-derived lessons scattered across AgentLoop, provider context, and TUI logging code.

This design introduces three runtime layers and connects them to the main AgentLoop path:

```text
User Message
-> ContextManager.begin_turn()
-> MemoryRuntime.recall_for_turn()
-> Provider Input Bundle
-> Tool Calls
-> ContextManager.record_observation()
-> Final Response
-> EvolutionRuntime.after_turn()
-> Trace / Metrics / Review Queue
```

The first implementation should establish stable interfaces and prove the path works. It should not attempt to solve every compaction, memory ranking, or skill evolution problem in one pass.

## 2. Goals

- Route provider-visible context through one `ContextManager`.
- Move automatic memory recall behind a `MemoryRuntime` boundary.
- Add a reviewable lesson-candidate queue for trace-derived experience.
- Hook an `EvolutionRuntime` into the end of each AgentLoop turn.
- Record context metrics that support future benchmark claims, including memory hits, context size, observation count, `read_file` count, and repeated `read_file` count.
- Keep long-term memory conservative: generated lessons are candidates until explicitly accepted.

## 3. Non-Goals

- Do not implement a full SKILL.md loader or skill execution engine in this phase.
- Do not automatically modify prompts, tool schemas, skills, or long-term memory.
- Do not implement exact tokenizer accounting; character-based estimates are enough for the first pass.
- Do not build a TUI memory review panel yet.
- Do not claim token reduction or pass-rate metrics until benchmark cases produce real reports.

## 4. Architecture

### 4.1 ContextManager

Add:

```text
app/context/
  __init__.py
  models.py
  manager.py
  metrics.py
```

`ContextManager` is the boundary between AgentLoop and provider input construction. It decides what context the model sees; it does not execute tools, decide permissions, or write long-term memory.

Responsibilities:

- Accept the current user message, chat history, runtime metadata, and configured budget.
- Ask `MemoryRuntime` for relevant memory.
- Maintain recent observation summaries for the current turn.
- Build a compact provider context bundle.
- Track context metrics for trace, conversation summary, and benchmark inputs.

Suggested models:

```text
ContextItem
- kind: user_message / memory / observation / file_summary / session_summary / skill_hint
- content
- source
- priority
- estimated_chars
- metadata

ContextBudget
- max_items
- max_chars
- max_memory_items
- max_observation_chars
- max_file_summary_chars

ContextBundle
- provider_context
- memory_hits
- compacted_items
- metrics

ContextMetrics
- context_chars
- memory_recall_hits
- observation_count
- read_file_count
- repeated_read_file_count
- compacted_item_count
```

AgentLoop should call:

```text
context_bundle = context_manager.begin_turn(...)
context_manager.record_observation(tool_name, args, observation)
context_bundle = context_manager.build_provider_context(...)
```

The first implementation may keep the provider context format close to the current format. The important change is ownership: AgentLoop no longer directly assembles memory recall text or owns context metrics.

### 4.2 MemoryRuntime

Add:

```text
app/memory/runtime.py
app/memory/recall.py
app/memory/review_queue.py
```

`MemoryRuntime` wraps the existing `MemoryStore` and file summary cache. It is the only runtime-facing API for automatic recall and reviewable memory candidates.

Responsibilities:

- Recall relevant memory for the current turn.
- Apply simple kind, tag, recency, and budget filters.
- Return compact memory hits instead of raw full records.
- Provide a stable file-summary access point for future context compaction.
- Manage a review queue for lesson candidates.

Suggested APIs:

```text
MemoryRuntime.recall_for_turn(user_message, repo_state, budget) -> MemoryRecallResult
MemoryRuntime.get_file_summary(path) -> FileSummaryResult
MemoryRuntime.enqueue_candidate(candidate) -> ReviewQueueResult
MemoryRuntime.list_candidates(...) -> list[LessonCandidate]
MemoryRuntime.accept_candidate(candidate_id) -> MemoryRecord
MemoryRuntime.reject_candidate(candidate_id) -> ReviewQueueResult
```

First-pass recall strategy:

- Search by the user message and extracted keywords.
- Prefer `project_fact`, `task_state`, and `failure_lesson`.
- Limit recall to 3-5 compact records.
- Track hit count, returned chars, and truncation.

Review queue:

```text
data/memory/review_queue.jsonl
```

The review queue stores candidates, not accepted memory. `enqueue_candidate()` must not write to long-term memory. `accept_candidate()` is the only path that can promote a candidate into `MemoryStore`, and it can remain unused by TUI in the first phase.

### 4.3 EvolutionRuntime

Add:

```text
app/evolution/
  __init__.py
  models.py
  runtime.py
  lesson_builder.py
```

`EvolutionRuntime` runs after each AgentLoop turn. It analyzes the completed turn and may generate reviewable lesson candidates. It must not affect the final response for the current turn.

Suggested input:

```text
EvolutionTurnInput
- user_message
- final_response
- turn_status
- tool_steps
- trace_path
- verification_results
- context_metrics
```

Suggested output:

```text
EvolutionTurnResult
- generated_candidates
- skipped_reason
- signals
```

Candidate model:

```text
LessonCandidate
- id
- kind: failure_lesson / tool_policy_lesson / context_lesson / test_fix_lesson
- summary
- evidence
- source_trace_path
- suggested_memory_kind
- suggested_skill
- confidence
- created_at
- status: pending / accepted / rejected
```

First-pass signals:

- Failed, timed out, or provider-failed turns produce a failure candidate.
- Rejected tool observations produce a tool-policy candidate.
- Repeated `read_file` calls above a threshold produce a context candidate.
- Verification failure followed by a later pass may produce a test-fix candidate.
- Successful ordinary turns with no signal are skipped.

`trace_analyze` remains a manual tool for historical trace analysis. `EvolutionRuntime.after_turn()` is the automatic per-turn hook. Both should write candidates to the review queue only.

## 5. Main Path Integration

`app.runtime.agent_loop.run_agent_loop_turn` should become the first integration point:

1. Create or receive `ContextManager`, `MemoryRuntime`, and `EvolutionRuntime`.
2. Call `ContextManager.begin_turn()` before the first provider request.
3. Pass the resulting provider context to the provider.
4. After each tool execution, call `ContextManager.record_observation()`.
5. Rebuild provider context through `ContextManager` before the next provider step.
6. After final response, failed status, or step-budget exhaustion, call `EvolutionRuntime.after_turn()`.
7. Attach context and evolution summaries to `RuntimeTurnResult` and trace events.

Compatibility constraints:

- Existing provider-driven tool-call behavior must continue to work.
- Existing `memory_search`, `file_summary_read`, and `trace_analyze` tools remain available.
- `memory_write` remains high risk and must not become default-visible through this framework.
- Existing tests for final response gate, tool closure, permission, and TUI scenarios should continue to pass.

## 6. Error Handling

- If memory recall fails, AgentLoop should continue with an empty memory recall result and record the recall error as a context warning.
- If review queue writing fails, the user-facing final response should not fail; trace should record the evolution error.
- If context budget truncates items, metrics should record the truncation.
- If EvolutionRuntime cannot classify a turn, it should return a skipped result with a reason.

## 7. Testing

Unit tests:

- `ContextManager` recalls memory, builds a bundle, records observations, and updates metrics.
- `MemoryRuntime` recalls compact hits, appends review candidates, lists candidates, and avoids unsafe long-term writes.
- `EvolutionRuntime` generates candidates for failed turns, rejected tool observations, and repeated file reads.
- `EvolutionRuntime` skips ordinary successful turns.
- AgentLoop calls `ContextManager` and `EvolutionRuntime` on the main provider-driven path.

Scenario or integration tests:

- A local-fact question still uses schema tools and records context metrics.
- A memory-relevant question includes memory recall evidence in trace or conversation compact payload.
- A repeated-read or rejected-tool scenario produces a pending lesson candidate.

Regression requirements:

- Tool-call loop tests still pass.
- Permission and shell policy tests still pass.
- TUI scenario tests do not expose trace paths directly to the user.

## 8. Documentation Updates

After implementation:

- Update `MendCode_开发方案.md` with actual module boundaries, completed items, and remaining gaps.
- Update `README.md` only if user-facing capabilities or startup instructions change.
- Update `MendCode_问题记录.md` if the implementation exposes a new recurring architectural risk.

## 9. First Implementation Cut

The first implementation should be intentionally narrow:

- Add the new modules and models.
- Wire ContextManager, MemoryRuntime, and EvolutionRuntime into `run_agent_loop_turn`.
- Preserve current provider context behavior where possible.
- Add review queue persistence.
- Add context/evolution summaries to trace or runtime result.
- Add focused unit tests and one scenario-level assertion.

The expected end state is not full intelligence. The expected end state is a stable runtime foundation:

```text
ContextManager owns provider context.
MemoryRuntime owns recall and reviewable memory candidates.
EvolutionRuntime owns post-turn lesson-candidate generation.
AgentLoop orchestrates these pieces without embedding their policies.
```

This foundation makes later Context Compaction, Layered Memory refinement, SKILL.md execution, and benchmark-driven improvement possible without another large AgentLoop rewrite.
