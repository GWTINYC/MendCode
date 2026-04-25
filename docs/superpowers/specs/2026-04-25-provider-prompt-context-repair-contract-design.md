# Provider Prompt Context And Repair Contract Design

## Purpose

MendCode now supports an OpenAI-compatible JSON Action provider, but the provider prompt is still too raw for repair work. It passes full observation payloads directly to the model and does not clearly define when to inspect, patch, verify, summarize, or stop.

This slice adds a tested prompt-context layer and repair contract for provider-driven repair attempts. It prepares the current provider for real model smoke testing without adding TUI, apply/discard, new provider types, or real-network tests.

## Product Fit

This work advances the TUI Agent route by making the provider boundary reliable enough for model-driven repair:

```text
Observation history -> Prompt context summary -> JSON Action provider -> MendCodeAction
```

MendCode still controls validation, permission, execution, worktree boundaries, verification, and trace.

## Scope

In scope:

- Add a provider prompt context builder.
- Summarize prior action/observation history into bounded, model-readable records.
- Include explicit repair workflow guidance in the system prompt.
- Include allowed action types and allowed tool names in a stable prompt section.
- Include the verification rule: do not return `final_response.completed` until a verification command has passed after any patch.
- Include patch proposal rules for unified diff output.
- Redact secrets from prompt context.
- Ensure API keys and provider secrets do not appear in prompts, observations, trace payloads, or CLI output.
- Update `OpenAICompatibleAgentProvider` to use the prompt context builder.
- Add fake-provider repair-chain tests that prove a patch proposal can flow through worktree apply, verification, diff summary, and final response.
- Add an optional real API smoke command path only after unit and integration tests pass, using existing environment variables if configured.

Out of scope:

- TUI.
- apply/discard to the main workspace.
- commit, push, or PR automation.
- Anthropic adapter.
- OpenAI native tool-calling adapter.
- streaming.
- config files or keyring.
- required real-network tests.

## Prompt Context

Create `app/agent/prompt_context.py` with a small public API:

```python
build_provider_messages(step_input, *, secret_values=None) -> list[ChatMessage]
```

The returned messages should include:

- system prompt with MendCode role and repair contract
- user prompt with JSON context:
  - problem statement
  - verification commands
  - step index
  - remaining steps
  - summarized observations

Observation summaries should include:

- action type
- tool/action name when available
- status
- summary
- error message
- selected payload fields relevant for repair

Large textual fields must be capped. The goal is to provide enough context for repair while avoiding unlimited prompt growth.

## Repair Contract

The system prompt must tell the model:

- Return exactly one JSON object and no prose.
- The JSON object must validate as one MendCode Action.
- Prefer this repair sequence:
  1. inspect repo status and project type if not already known
  2. run or inspect verification failure
  3. read failing test files
  4. search candidate implementation
  5. propose a unified diff patch
  6. rerun verification
  7. show diff
  8. return final response
- Never claim `completed` after a failed verification.
- Use `patch_proposal` for unified diff patches.
- Use `show_diff` after a patch and verification pass.
- Use `final_response.failed` when the step budget is low and repair is not verified.

## Testing

Tests must be written before implementation.

Required coverage:

- prompt context includes problem statement, verification commands, step budget, and allowed tools.
- prompt context summarizes failed `run_command` observations with command status and stderr excerpt.
- prompt context summarizes `read_file` content with truncation.
- prompt context summarizes `search_code` matches with truncation.
- prompt context includes patch proposal rules.
- prompt context redacts configured secrets.
- OpenAI-compatible provider calls the prompt context builder instead of building ad hoc messages internally.
- fake provider repair chain applies a patch in worktree, reruns verification, shows diff, and completes.
- failed verification after patch cannot be reported as completed.

Full verification:

```bash
python -m pytest -q
ruff check .
git diff --check
```

## Real API Smoke

After tests pass, attempt a real provider smoke only if all required environment variables are configured:

```text
MENDCODE_PROVIDER=openai-compatible
MENDCODE_MODEL
MENDCODE_BASE_URL
MENDCODE_API_KEY
```

The smoke should use a minimal temporary git repository and a low-risk verification command. It should not print the API key. If configuration is missing, skip the real API smoke and report which non-secret variables are missing.

## Documentation Updates

After implementation and verification, update:

- `README.md`
- `MendCode_开发方案.md`
- `MendCode_全局路线图.md`
- `MendCode_TUI产品基调与交互方案.md`

Only mark prompt context and repair-contract items complete when tests and lint pass.

## Acceptance Criteria

- Provider prompt construction is isolated and unit-tested.
- OpenAI-compatible provider uses the shared prompt context builder.
- Prompt context is bounded and redacts secrets.
- Fake repair-chain test proves patch proposal, worktree apply, verification, diff summary, and final response.
- No TUI, apply/discard, new provider type, or required real-network test is introduced.
- Full tests and lint pass.
