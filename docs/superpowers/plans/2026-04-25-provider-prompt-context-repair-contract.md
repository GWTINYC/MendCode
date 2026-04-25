# Provider Prompt Context And Repair Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a bounded, secret-safe provider prompt context builder and prove a patch repair chain can run through the existing Agent loop.

**Architecture:** Create `app/agent/prompt_context.py` as the only module responsible for turning `AgentProviderStepInput` into provider messages. Update `OpenAICompatibleAgentProvider` to use that module. Add integration coverage for a fake provider repair chain that produces a patch proposal, verifies it in a worktree, shows diff, and completes.

**Tech Stack:** Python 3.11, Pydantic v2, pytest, ruff, existing MendCode Agent loop and provider abstractions.

---

## File Structure

- Create `app/agent/prompt_context.py`
  - `PromptContextLimits`
  - `summarize_observation_record()`
  - `build_provider_messages()`
  - secret redaction helpers

- Modify `app/agent/openai_compatible.py`
  - remove internal ad hoc `_build_messages()`
  - call `build_provider_messages()`

- Create `tests/unit/test_prompt_context.py`
  - coverage for repair contract prompt, bounded summaries, selected payloads, and redaction

- Modify `tests/unit/test_openai_compatible_provider.py`
  - prove provider uses prompt context output

- Create `tests/integration/test_agent_repair_chain.py`
  - fake provider repair chain over a temp git repo

- Modify docs:
  - `README.md`
  - `MendCode_开发方案.md`
  - `MendCode_全局路线图.md`
  - `MendCode_TUI产品基调与交互方案.md`

---

### Task 1: Prompt Context Builder

**Files:**
- Create: `app/agent/prompt_context.py`
- Test: `tests/unit/test_prompt_context.py`

- [ ] **Step 1: Write failing prompt context tests**

Create `tests/unit/test_prompt_context.py`:

```python
from app.agent.prompt_context import PromptContextLimits, build_provider_messages
from app.agent.provider import AgentObservationRecord, AgentProviderStepInput
from app.schemas.agent_action import Observation, ToolCallAction


def test_provider_messages_include_repair_contract_and_allowed_tools() -> None:
    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="fix failing tests",
            verification_commands=["python -m pytest -q"],
            step_index=1,
            remaining_steps=6,
            observations=[],
        )
    )

    assert messages[0].role == "system"
    assert "Return exactly one JSON object and no prose" in messages[0].content
    assert "patch_proposal" in messages[0].content
    assert "show_diff" in messages[0].content
    assert "Never claim completed after a failed verification" in messages[0].content
    assert messages[1].role == "user"
    assert "fix failing tests" in messages[1].content
    assert "python -m pytest -q" in messages[1].content
```

Add:

```python
def test_provider_messages_summarize_failed_run_command() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="run_command",
        reason="run tests",
        args={"command": "python -m pytest -q"},
    )
    observation = Observation(
        status="failed",
        summary="Ran command: python -m pytest -q",
        payload={
            "command": "python -m pytest -q",
            "status": "failed",
            "stderr_excerpt": "AssertionError: assert -1 == 5",
        },
        error_message="AssertionError: assert -1 == 5",
    )

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="fix failing tests",
            verification_commands=["python -m pytest -q"],
            step_index=2,
            remaining_steps=5,
            observations=[AgentObservationRecord(action=action, observation=observation)],
        )
    )

    assert "run_command" in messages[1].content
    assert "AssertionError: assert -1 == 5" in messages[1].content
```

Add:

```python
def test_provider_messages_truncate_large_read_file_content() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="read_file",
        reason="read file",
        args={"relative_path": "tests/test_calculator.py"},
    )
    observation = Observation(
        status="succeeded",
        summary="Read tests/test_calculator.py",
        payload={
            "relative_path": "tests/test_calculator.py",
            "content": "x" * 200,
            "truncated": False,
        },
    )

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="fix failing tests",
            verification_commands=["python -m pytest -q"],
            step_index=3,
            remaining_steps=4,
            observations=[AgentObservationRecord(action=action, observation=observation)],
        ),
        limits=PromptContextLimits(max_text_chars=40, max_observations=5),
    )

    assert "x" * 40 in messages[1].content
    assert "x" * 80 not in messages[1].content
```

Add:

```python
def test_provider_messages_redact_secrets() -> None:
    observation = Observation(
        status="failed",
        summary="Provider failed",
        payload={"stderr_excerpt": "token secret-key leaked"},
        error_message="secret-key",
    )

    messages = build_provider_messages(
        AgentProviderStepInput(
            problem_statement="secret-key should not leak",
            verification_commands=["python -m pytest -q"],
            step_index=1,
            remaining_steps=4,
            observations=[AgentObservationRecord(action=None, observation=observation)],
        ),
        secret_values=["secret-key"],
    )

    combined = "\n".join(message.content for message in messages)
    assert "secret-key" not in combined
    assert "[REDACTED]" in combined
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
python -m pytest tests/unit/test_prompt_context.py -q
```

Expected: FAIL because `app.agent.prompt_context` does not exist.

- [ ] **Step 3: Implement prompt context builder**

Create `app/agent/prompt_context.py` with bounded summaries and redaction.

- [ ] **Step 4: Run prompt context tests**

Run:

```bash
python -m pytest tests/unit/test_prompt_context.py -q
```

Expected: PASS.

---

### Task 2: OpenAI-Compatible Provider Uses Prompt Context

**Files:**
- Modify: `app/agent/openai_compatible.py`
- Modify: `tests/unit/test_openai_compatible_provider.py`

- [ ] **Step 1: Add failing test for prompt context use**

Add to `tests/unit/test_openai_compatible_provider.py`:

```python
def test_openai_compatible_provider_uses_repair_contract_prompt() -> None:
    client = FakeClient(
        '{"type":"tool_call","action":"repo_status","reason":"inspect","args":{}}'
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    provider.next_action(step_input())

    messages = client.calls[0]["messages"]
    assert isinstance(messages, list)
    assert "Never claim completed after a failed verification" in messages[0].content
    assert "secret-key" not in "\n".join(message.content for message in messages)
```

- [ ] **Step 2: Run provider test to verify RED**

Run:

```bash
python -m pytest tests/unit/test_openai_compatible_provider.py::test_openai_compatible_provider_uses_repair_contract_prompt -q
```

Expected: FAIL because current provider builds a simpler prompt internally.

- [ ] **Step 3: Update provider to use `build_provider_messages()`**

Import and call:

```python
from app.agent.prompt_context import build_provider_messages
```

In `next_action()`:

```python
messages=build_provider_messages(step_input, secret_values=[self._api_key])
```

Remove `_build_messages()`.

- [ ] **Step 4: Run provider tests**

Run:

```bash
python -m pytest tests/unit/test_openai_compatible_provider.py -q
```

Expected: PASS.

---

### Task 3: Fake Repair Chain Integration

**Files:**
- Create: `tests/integration/test_agent_repair_chain.py`

- [ ] **Step 1: Write failing repair-chain test**

Create a fake provider that emits:

1. failing verification command
2. patch proposal
3. passing verification command
4. show diff
5. final completed response

Assert:

- result status is completed
- workspace file changed
- main repo file unchanged
- diff stat includes changed file

- [ ] **Step 2: Run test to verify behavior**

Run:

```bash
python -m pytest tests/integration/test_agent_repair_chain.py -q
```

Expected: PASS if existing loop already supports the chain, otherwise fail on the missing contract.

- [ ] **Step 3: Add failed-verification-after-patch test**

Create a second fake provider where verification after patch fails and final response incorrectly says completed.

Assert:

```python
assert result.status == "failed"
assert result.summary == "Agent loop ended with failed observations"
```

- [ ] **Step 4: Run repair-chain tests**

Run:

```bash
python -m pytest tests/integration/test_agent_repair_chain.py -q
```

Expected: PASS.

---

### Task 4: Documentation And Real API Smoke

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_全局路线图.md`
- Modify: `MendCode_TUI产品基调与交互方案.md`

- [ ] **Step 1: Update docs**

Document:

- provider prompt context exists
- prompt contract is JSON Action only
- fake repair-chain integration is covered
- real API smoke is optional and depends on environment variables

- [ ] **Step 2: Run full verification**

Run:

```bash
python -m pytest -q
ruff check .
git diff --check
```

Expected: all pass.

- [ ] **Step 3: Check real API environment without printing secrets**

Run:

```bash
python - <<'PY'
import os
for name in ["MENDCODE_PROVIDER", "MENDCODE_MODEL", "MENDCODE_BASE_URL", "MENDCODE_API_KEY"]:
    print(f"{name}={'SET' if os.getenv(name) else 'UNSET'}")
PY
```

- [ ] **Step 4: If configured, run a real API smoke**

If all required variables are set and `MENDCODE_PROVIDER=openai-compatible`, run a bounded smoke against a temporary git repo. If variables are missing, skip and report missing non-secret variable names.

- [ ] **Step 5: Commit**

Run:

```bash
git add app/agent/prompt_context.py app/agent/openai_compatible.py tests/unit/test_prompt_context.py tests/unit/test_openai_compatible_provider.py tests/integration/test_agent_repair_chain.py README.md MendCode_开发方案.md MendCode_全局路线图.md MendCode_TUI产品基调与交互方案.md docs/superpowers/plans/2026-04-25-provider-prompt-context-repair-contract.md
git commit -m "feat: add provider prompt repair contract"
```

Expected: commit succeeds.

---

## Self-Review

- Spec coverage: prompt context, repair contract, secret redaction, provider integration, fake repair-chain, docs, full verification, and optional real API smoke are covered.
- Scope control: no TUI, apply/discard, new provider type, streaming, config files, or required network tests.
- Type consistency: plan uses existing `AgentProviderStepInput`, `AgentObservationRecord`, `ChatMessage`, and `ProviderResponse` names.
