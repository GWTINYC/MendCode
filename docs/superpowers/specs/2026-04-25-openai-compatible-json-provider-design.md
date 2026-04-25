# OpenAI-Compatible JSON Provider MVP Design

## Purpose

MendCode now has a provider-driven Agent loop: each step can request the next `MendCodeAction` from a provider after seeing observation history. The next slice is to add the first real-model provider path without changing the Agent loop, TUI, or workspace apply boundaries.

This MVP adds an `openai-compatible` provider that asks a chat-completions-compatible API for exactly one MendCode Action JSON object per step.

## Product Fit

This work advances the TUI Code Agent route by replacing deterministic scripted action selection with a real provider option while preserving MendCode's internal safety model:

```text
Provider -> MendCodeAction JSON -> schema validation -> Permission Gate -> Tool Execution -> Observation
```

The business layer must continue to consume only MendCode Action dictionaries. Provider-specific response formats stay inside the provider adapter.

## Scope

In scope:

- Add provider configuration for:
  - provider type: `scripted` or `openai-compatible`
  - model name
  - base URL
  - API key
  - request timeout
- Read configuration from environment variables:
  - `MENDCODE_PROVIDER`
  - `MENDCODE_MODEL`
  - `MENDCODE_BASE_URL`
  - `MENDCODE_API_KEY`
  - `MENDCODE_PROVIDER_TIMEOUT_SECONDS`
- Keep `scripted` as the default provider when no provider is configured.
- Add an `OpenAICompatibleAgentProvider` implementing `next_action()`.
- Use a small client boundary so tests can inject a fake client and avoid network calls.
- Ask the model to return exactly one JSON object matching the MendCode Action schema.
- Parse plain JSON and JSON inside a single fenced code block.
- Validate parsed JSON through the existing `MendCodeAction` parser.
- Convert invalid JSON, invalid action schema, empty responses, and client errors into `ProviderResponse.failed(...)`.
- Ensure API keys and authorization headers are not written to trace payloads, observations, or CLI tables.
- Add CLI provider selection for the existing `mendcode fix` transitional entry.

Out of scope:

- Anthropic adapter.
- Native OpenAI or Anthropic tool-calling formats.
- Streaming.
- TUI provider settings UI.
- Config files under `~/.config/mendcode/` or `.mendcode/`.
- Keyring integration.
- Automatic patch apply to the main workspace.
- Commit, push, or PR automation.
- Real network integration tests.

## Provider Behavior

The provider receives `AgentProviderStepInput` and returns `ProviderResponse` containing exactly one action dictionary on success.

The prompt should include:

- the user's `problem_statement`
- the verification commands
- current step index and remaining step budget
- prior action/observation history
- the allowed MendCode action types
- the allowed tool names
- a hard instruction to return one JSON object only

The provider should not expose API keys in prompts, observations, exceptions, or trace data.

## Configuration

The first configuration layer is environment-only.

Defaults:

```text
MENDCODE_PROVIDER=scripted
MENDCODE_PROVIDER_TIMEOUT_SECONDS=60
```

`openai-compatible` requires:

```text
MENDCODE_MODEL
MENDCODE_BASE_URL
MENDCODE_API_KEY
```

If required openai-compatible settings are missing, provider construction should fail before the Agent loop starts and produce a clear CLI error. The default scripted path must keep working without any environment variables.

## Client Boundary

Add a minimal client protocol with a method that accepts messages and returns assistant text. The concrete client can use the existing `openai` package dependency, but tests should inject a fake client.

The provider should not depend on Typer or CLI code. CLI code only selects and constructs the provider.

## JSON Parsing

Accepted response forms:

```json
{"type":"tool_call","action":"repo_status","reason":"inspect repo","args":{}}
```

or:

````text
```json
{"type":"final_response","status":"completed","summary":"done"}
```
````

Rejected response forms:

- multiple JSON objects
- prose before or after JSON
- arrays
- empty text
- JSON that does not validate as `MendCodeAction`

Rejected responses should become provider failures. The Agent loop already records provider failures as failed observations.

## CLI Compatibility

`mendcode fix` should keep current behavior by default:

```bash
mendcode fix "pytest 失败了，请定位并修复" --repo . --test "python -m pytest -q"
```

With no provider environment set, it uses `ScriptedAgentProvider`.

With:

```bash
MENDCODE_PROVIDER=openai-compatible
MENDCODE_MODEL=<model>
MENDCODE_BASE_URL=<base-url>
MENDCODE_API_KEY=<key>
```

the same command uses the openai-compatible provider. This slice does not guarantee that a real model can fully repair a project; it only guarantees that real provider output can drive the existing MendCode Action loop safely.

## Error Handling

- Missing provider config returns a CLI failure before loop execution.
- Client exceptions become `ProviderResponse.failed("Provider request failed: ...")`.
- Empty assistant response becomes `ProviderResponse.failed("Provider returned empty response")`.
- JSON parse failure becomes `ProviderResponse.failed("Provider returned invalid JSON action")`.
- Schema validation failure becomes `ProviderResponse.failed("Provider returned invalid MendCode action")`.

Error messages must avoid including API keys. If an exception contains the key, redact it before surfacing the message.

## Testing

Tests must be written before implementation.

Required coverage:

- settings read default `scripted` provider.
- settings read openai-compatible environment values.
- missing openai-compatible model/base URL/API key fails provider construction.
- fake client response with plain JSON returns one action.
- fake client response with fenced JSON returns one action.
- fake client empty response becomes provider failure.
- fake client invalid JSON becomes provider failure.
- fake client invalid action schema becomes provider failure.
- fake client exception becomes provider failure with redacted API key.
- CLI `fix` still defaults to scripted provider.
- CLI `fix` can select an injected or monkeypatched openai-compatible provider path without real network calls.

Full verification:

```bash
python -m pytest -q
ruff check .
```

## Documentation Updates

After implementation and verification, update:

- `MendCode_开发方案.md`
- `MendCode_全局路线图.md`
- `MendCode_TUI产品基调与交互方案.md`
- `README.md` if the CLI provider environment variables become user-visible

Only mark provider items complete when tests and lint pass.

## Acceptance Criteria

- Scripted provider remains the default path.
- OpenAI-compatible provider can be selected through environment variables.
- Provider responses are normalized to MendCode Action dictionaries.
- No provider-specific response shape leaks into `app/agent/loop.py`.
- No API key appears in observations, traces, CLI output, or test failure messages.
- No real network calls are required by tests.
- `python -m pytest -q` passes.
- `ruff check .` passes.
