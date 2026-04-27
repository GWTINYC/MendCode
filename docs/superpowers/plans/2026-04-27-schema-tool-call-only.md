# Schema Tool Call Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert normal natural-language MendCode turns to the schema tool-call path, removing rule-triggered shell/tool/chat bypasses and silent JSON/text fallback.

**Architecture:** `ToolRegistry` defines every model-callable tool, `ToolPool` scopes the schema set by permission, the OpenAI-compatible provider returns only native `ToolInvocation` objects or a `final_response` tool result, and AgentLoop acts as the Harness that validates and executes tool calls. TUI keeps slash commands and pending confirmation replies local, but sends all normal text to AgentLoop instead of rule-routing to chat, shell, or direct tool execution.

**Tech Stack:** Python 3.12, Pydantic, OpenAI-compatible Chat Completions tool calls, Textual TUI, pytest, pexpect PTY tests, ruff.

---

## File Map

- Modify `app/agent/openai_compatible.py`: remove normal JSON/text action fallback, always expose `final_response`, fail clearly when tools are unsupported or when the model returns plain text.
- Modify `app/agent/prompt_context.py`: update system contract so the model must use schema tools and must end with `final_response`.
- Modify `app/agent/provider.py`: keep `ProviderResponse` compatible while tightening expected provider output shape in tests.
- Modify `app/runtime/agent_loop.py`: keep handling `tool_invocations`; reduce reliance on `actions` to final responses only.
- Modify `app/agent/loop.py`: quarantine legacy JSON action handling and ensure native tool calls still use ToolRegistry/Harness.
- Modify `app/tui/controller.py`: stop calling intent router for normal tasks; dispatch normal user text to a unified AgentLoop request.
- Modify `app/tui/app.py`: replace chat/shell/tool natural-language worker split with one agent request path; keep slash commands and pending confirmations.
- Modify `app/tui/intent.py`: remove or stop using natural-language rule routing for normal TUI turns; keep only tests or delete after call sites are gone.
- Modify `tests/unit/test_openai_compatible_provider.py`: assert strict native tool-call behavior and provider failures.
- Modify `tests/unit/test_prompt_context.py`: assert system prompt requires tool calls and final_response.
- Modify `tests/unit/test_tui_controller.py` and `tests/unit/test_tui_app.py`: assert normal text starts AgentLoop, not chat/shell direct execution.
- Modify `tests/scenarios/*` and `tests/e2e/test_tui_pty_live.py`: assert tool evidence in conversation logs instead of shell-rule route evidence.
- Modify `README.md`, `MendCode_开发方案.md`, and `MendCode_问题记录.md`: document tool-call-only behavior and removed fallbacks.

## Task 1: Provider Strict Native Tool-Call Mode

**Files:**
- Modify: `app/agent/openai_compatible.py`
- Modify: `app/agent/prompt_context.py`
- Test: `tests/unit/test_openai_compatible_provider.py`
- Test: `tests/unit/test_prompt_context.py`

- [ ] **Step 1: Write failing provider tests for unsupported tools and plain text**

Add these tests to `tests/unit/test_openai_compatible_provider.py` near the existing unsupported-tools and wrapped-text tests:

```python
def test_openai_compatible_provider_fails_when_tools_are_unsupported() -> None:
    client = ToolsUnsupportedClient("free text should not be used")
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert "does not support tool calls" in str(response.observation.error_message)
    assert len(client.calls) == 1


def test_openai_compatible_provider_rejects_plain_text_without_tool_call() -> None:
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=FakeClient("README.md probably contains project docs."),
    )

    response = provider.next_action(step_input())

    assert response.status == "failed"
    assert response.observation is not None
    assert response.observation.error_message == (
        "Provider returned plain text instead of a schema tool call"
    )
```

- [ ] **Step 2: Write failing test that final_response is always exposed**

Add this test to `tests/unit/test_openai_compatible_provider.py`:

```python
def test_openai_compatible_provider_always_exposes_final_response_tool() -> None:
    client = FakeClient(
        "",
        tool_calls=[
            {
                "id": "call_final",
                "type": "function",
                "function": {
                    "name": "final_response",
                    "arguments": json.dumps(
                        {
                            "status": "completed",
                            "summary": "我需要更多信息。",
                            "recommended_actions": [],
                        }
                    ),
                },
            }
        ],
    )
    provider = OpenAICompatibleAgentProvider(
        model="test-model",
        api_key="secret-key",
        base_url="https://example.test/v1",
        timeout_seconds=12,
        client=client,
    )

    response = provider.next_action(step_input())

    assert response.status == "succeeded"
    assert response.action == {
        "type": "final_response",
        "status": "completed",
        "summary": "我需要更多信息。",
        "recommended_actions": [],
    }
    tool_names = [tool["function"]["name"] for tool in client.calls[0]["tools"]]
    assert "final_response" in tool_names
```

- [ ] **Step 3: Run provider tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_openai_compatible_provider.py -q
```

Expected: the new tests fail because unsupported tools currently retry without `tools`, plain text is still parsed as JSON/text action in some paths, and `final_response` is only appended after observations.

- [ ] **Step 4: Implement strict provider behavior**

In `app/agent/openai_compatible.py`, change `next_action()` so it always appends `_FINAL_RESPONSE_TOOL` and never retries without tools:

```python
tool_pool = self._tool_registry.tool_pool(
    permission_mode=step_input.permission_mode,
    allowed_tools=step_input.allowed_tools,
)
openai_tools = [*tool_pool.openai_tools(), _FINAL_RESPONSE_TOOL]
allowed_tool_names = set(tool_pool.names())
```

Replace the unsupported-tools fallback block with:

```python
except Exception as exc:
    if _looks_like_unsupported_tools_error(exc):
        return ProviderResponse.failed(
            "Configured provider does not support tool calls; "
            "MendCode requires OpenAI-compatible native tools for this workflow"
        )
    return ProviderResponse.failed(
        f"Provider request failed: {redact_secret(str(exc), self._api_key)}"
    )
```

Replace the final no-tool-call return with a failure helper:

```python
return ProviderResponse.failed(
    "Provider returned plain text instead of a schema tool call"
)
```

Do not delete `_response_from_action_text` yet; Task 4 quarantines legacy paths after TUI migration.

- [ ] **Step 5: Update prompt contract**

In `app/agent/prompt_context.py`, update `_system_prompt()` text to include these exact ideas:

```python
"Use schema tool calls for all actions. Do not answer local repository facts from memory. "
"End every completed turn by calling final_response. Do not return free-form text as the final answer."
```

Keep the existing structured-tool guidance, including `read_file` tail guidance and `run_command` verification guidance.

- [ ] **Step 6: Run focused provider and prompt tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_openai_compatible_provider.py tests/unit/test_prompt_context.py -q
```

Expected: all focused tests pass after updating old expectations that assumed fallback JSON/text behavior.

- [ ] **Step 7: Commit Task 1**

Run:

```bash
git add app/agent/openai_compatible.py app/agent/prompt_context.py tests/unit/test_openai_compatible_provider.py tests/unit/test_prompt_context.py
git commit -m "enforce native schema tool calls in provider"
```

## Task 2: TUI Normal Text Uses AgentLoop

**Files:**
- Modify: `app/tui/controller.py`
- Modify: `app/tui/app.py`
- Modify: `app/tui/intent.py`
- Test: `tests/unit/test_tui_controller.py`
- Test: `tests/unit/test_tui_app.py`

- [ ] **Step 1: Write failing controller tests**

Add tests to `tests/unit/test_tui_controller.py` showing normal text no longer routes through chat or shell:

```python
def test_controller_routes_normal_text_to_agent_request() -> None:
    host = FakeControllerHost()
    controller = TuiController(host)

    controller.handle_user_input("帮我查看当前文件夹里的文件")

    assert host.started_agent_requests == ["帮我查看当前文件夹里的文件"]
    assert host.started_chats == []
    assert host.prepared_shell_commands == []
    assert host.started_tool_requests == []


def test_controller_keeps_slash_commands_local() -> None:
    host = FakeControllerHost()
    controller = TuiController(host)

    controller.handle_user_input("/status")

    assert [command.name for command in host.handled_commands] == ["status"]
    assert host.started_agent_requests == []
```

Update the fake host in that file with:

```python
self.started_agent_requests: list[str] = []

def start_agent_request(self, task: str) -> None:
    self.started_agent_requests.append(task)
```

- [ ] **Step 2: Run controller tests and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_controller.py -q
```

Expected: fails because `TuiControllerHost` has no `start_agent_request()` and `handle_task()` still uses `IntentRouter`.

- [ ] **Step 3: Replace normal task routing in controller**

In `app/tui/controller.py`, update `TuiControllerHost`:

```python
def start_agent_request(self, task: str) -> None: ...
```

Remove these protocol methods if no tests still need them after app changes:

```python
def ensure_intent_router(self) -> IntentRouter: ...
def start_chat(self, message: str) -> None: ...
def prepare_shell_command(self, command: str, *, source: str) -> None: ...
def start_tool_request(self, task: str) -> None: ...
def prepare_fix(self, task: str, *, source: str) -> None: ...
```

Change `handle_task()` after pending checks to:

```python
self._host.conversation_log.append_event(
    "intent",
    {
        "kind": "agent",
        "source": "schema_tool_call",
        "command": None,
        "message": task,
    },
)
self._host.start_agent_request(task)
```

Remove `ProviderConfigurationError`, `IntentContext`, and `IntentRouter` imports if unused.

- [ ] **Step 4: Add TUI app agent request method**

In `app/tui/app.py`, add:

```python
def _start_agent_request(self, task: str) -> None:
    if self.session_state.running:
        self.append_message("Error", "A request is already running.")
        return
    self.session_state.mark_tool_started(task)
    self.append_message("Agent", f"Running tools: {task}")
    self._run_tool_worker(task)
```

Expose it to the controller host using the existing naming pattern:

```python
def start_agent_request(self, task: str) -> None:
    self._start_agent_request(task)
```

If public host methods already use underscored implementation names, follow the existing style in `MendCodeTextualApp`.

- [ ] **Step 5: Remove direct natural shell/chat/tool/fix call path from controller usage**

After Step 4, delete or stop using:

```python
_ensure_intent_router()
_start_chat()
_prepare_shell_command()
_start_tool_request()
_prepare_fix()
```

Keep methods temporarily if slash commands still call them:

- `/fix` can keep `_fix_task()` and `_prepare_fix()` as an explicit slash command compatibility path.
- `/test`, `/status`, `/sessions`, `/resume`, `/diff`, `/trace`, `/apply`, and `/discard` remain local commands.

Update `/help` text in `app/tui/app.py` by replacing:

```text
Natural shell - ls, pwd, git status, git diff, rg, cat/head/tail, find
```

with:

```text
Natural language asks the model to call schema tools; slash commands control the TUI.
```

- [ ] **Step 6: Run TUI unit tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_tui_controller.py tests/unit/test_tui_app.py tests/unit/test_tui_intent.py -q
```

Expected: controller/app tests pass. If `test_tui_intent.py` now tests unused natural-language routing, either remove those tests or rewrite them to assert the router is not used by normal controller tasks.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add app/tui/controller.py app/tui/app.py app/tui/intent.py tests/unit/test_tui_controller.py tests/unit/test_tui_app.py tests/unit/test_tui_intent.py
git commit -m "route natural tui text through agent tools"
```

## Task 3: AgentLoop Accepts Tool Calls and Final Responses as the Main Provider Contract

**Files:**
- Modify: `app/runtime/agent_loop.py`
- Modify: `app/agent/loop.py`
- Modify: `tests/fixtures/mock_tool_provider.py`
- Test: `tests/unit/test_agent_loop.py`
- Test: `tests/unit/test_agent_loop_tool_closure.py`

- [ ] **Step 1: Write failing test that plain action payload is legacy-only**

Add this test to `tests/unit/test_agent_loop.py`:

```python
def test_provider_json_tool_call_action_is_rejected_in_tool_only_mode(tmp_path: Path) -> None:
    provider = MockActionProvider(
        [
            {
                "type": "tool_call",
                "action": "list_dir",
                "reason": "legacy json action",
                "args": {"path": "."},
            }
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=tmp_path,
            problem_statement="list files",
            provider=provider,
            verification_commands=[],
            step_budget=4,
            use_worktree=False,
        ),
        settings_for(tmp_path),
    )

    assert result.status == "failed"
    assert "legacy JSON actions are disabled" in result.summary
```

If `MockActionProvider` does not exist, add a small local test helper:

```python
class MockActionProvider:
    def __init__(self, actions: list[dict[str, object]]) -> None:
        self.actions = actions
        self.calls = 0

    def next_action(self, step_input):
        self.calls += 1
        return ProviderResponse(status="succeeded", actions=[self.actions[self.calls - 1]])
```

- [ ] **Step 2: Run AgentLoop test and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py::test_provider_json_tool_call_action_is_rejected_in_tool_only_mode -q
```

Expected: fails because AgentLoop still accepts JSON action payloads.

- [ ] **Step 3: Restrict provider `actions` to final_response only**

In `app/runtime/agent_loop.py`, before `_handle_action_payload(...)`, add a branch:

```python
action_payload = provider_response.actions[0]
if action_payload.get("type") != "final_response":
    observation = _failed_observation(
        "Legacy JSON actions are disabled",
        "provider returned a JSON action instead of schema tool_calls",
    )
    action = FinalResponseAction(
        type="final_response",
        status="failed",
        summary="Legacy JSON actions are disabled",
    )
    handled = _handled_response(
        status="failed",
        summary=observation.summary,
        index=index,
        action=action,
        observation=observation,
    )
    record_handled_action(handled)
    status = "failed"
    summary = observation.summary
    break
```

Then call `_handle_action_payload(...)` only for `final_response`.

- [ ] **Step 4: Keep direct action-list compatibility outside provider mode**

Do not remove the `else:` branch that executes `loop_input.actions` yet. Mark it in a comment:

```python
# Legacy scripted-action compatibility path. Provider-driven user turns should use
# native ToolInvocation objects and final_response only.
```

This preserves older CLI/scripted tests while removing JSON actions from model-provider turns.

- [ ] **Step 5: Run AgentLoop closure tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_agent_loop.py tests/unit/test_agent_loop_tool_closure.py -q
```

Expected: all tests pass after updating old provider-action tests to use `ToolInvocation` or `final_response`.

- [ ] **Step 6: Commit Task 3**

Run:

```bash
git add app/runtime/agent_loop.py app/agent/loop.py tests/fixtures/mock_tool_provider.py tests/unit/test_agent_loop.py tests/unit/test_agent_loop_tool_closure.py
git commit -m "disable provider json actions in agent loop"
```

## Task 4: Final Response Tool Contract

**Files:**
- Modify: `app/agent/openai_compatible.py`
- Modify: `app/runtime/final_response_gate.py`
- Test: `tests/unit/test_openai_compatible_provider.py`
- Test: `tests/unit/test_final_response_gate.py`

- [ ] **Step 1: Write final_response grounding tests**

Add this test to `tests/unit/test_final_response_gate.py`:

```python
def test_final_response_for_local_fact_requires_prior_tool_observation() -> None:
    handled = handled_final_response(
        status="completed",
        summary="README.md contains demo text.",
    )

    status, summary = apply_final_response_gate(steps=[], handled=handled)

    assert status == "failed"
    assert "requires tool evidence" in summary
```

If helper functions differ in the file, create the final response handled object using the existing test style in `tests/unit/test_final_response_gate.py`.

- [ ] **Step 2: Run final response gate test and verify failure**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_final_response_gate.py -q
```

Expected: new test fails because the gate does not yet reject local-fact answers without observation.

- [ ] **Step 3: Add conservative grounding gate**

In `app/runtime/final_response_gate.py`, add a helper:

```python
_LOCAL_FACT_HINTS = (
    "README",
    ".md",
    ".py",
    "git",
    "文件",
    "目录",
    "仓库",
    "代码",
    "路径",
)


def _looks_like_local_fact_summary(summary: str) -> bool:
    normalized = summary.lower()
    return any(hint.lower() in normalized for hint in _LOCAL_FACT_HINTS)
```

In `apply_final_response_gate()`, before accepting completed final response:

```python
if (
    handled.status == "completed"
    and _looks_like_local_fact_summary(handled.summary)
    and not any(step.observation.status == "succeeded" for step in steps)
):
    return "failed", "final_response requires tool evidence for local repository facts"
```

Keep this conservative. It is a guardrail, not the only defense; the main defense is provider requiring tool calls.

- [ ] **Step 4: Run final response tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/unit/test_final_response_gate.py tests/unit/test_openai_compatible_provider.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit Task 4**

Run:

```bash
git add app/runtime/final_response_gate.py tests/unit/test_final_response_gate.py tests/unit/test_openai_compatible_provider.py
git commit -m "require tool evidence for local fact finals"
```

## Task 5: Scenario and PTY Test Adaptation

**Files:**
- Modify: `tests/scenarios/tui_scenario_runner.py`
- Modify: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Modify: `tests/scenarios/test_tui_file_question_scenarios.py`
- Modify: `tests/scenarios/test_tui_failure_scenarios.py`
- Modify: `tests/e2e/test_tui_pty_live.py`

- [ ] **Step 1: Rewrite scenario assertions from route to tool evidence**

In scenario tests, stop asserting shell-only route for natural-language `git status`. Replace:

```python
assert_used_only_shell_route(transcript, "git status")
```

with a tool evidence assertion:

```python
assert_used_tool_path(transcript)
assert_has_evidence_from_observation(transcript, "git")
```

If the live provider chooses `run_shell_command` instead of `git`, allow both:

```python
assert any(
    tool_name in transcript.tool_calls
    for tool_name in ["git", "run_shell_command"]
), transcript.debug_text()
```

- [ ] **Step 2: Add scenario that chat path is not used for normal local facts**

Add to `tests/scenarios/test_tui_repository_inspection_scenarios.py`:

```python
async def test_local_fact_question_never_uses_chat_path(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="local fact tool only",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["当前目录里有什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={
                        "relative_path": ".",
                        "total_entries": 1,
                        "entries": [
                            {
                                "relative_path": "README.md",
                                "name": "README.md",
                                "type": "file",
                            }
                        ],
                    },
                )
            ],
            final_summary="当前目录包含 README.md。",
        )
    )

    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "list_dir")
```

- [ ] **Step 3: Update PTY assertions to inspect conversation JSONL tool evidence**

In `tests/e2e/test_tui_pty_live.py`, for natural-language tests, assert at least one `tool_result` or agent tool event exists in saved conversation records. Use existing helper patterns in that file. If no helper exists, add:

```python
def assert_conversation_has_tool_evidence(result: LiveTuiResult, *tool_names: str) -> None:
    evidence = "\n".join(json.dumps(record, ensure_ascii=False) for record in result.records)
    for tool_name in tool_names:
        if tool_name in evidence:
            return
    raise AssertionError(f"missing tool evidence {tool_names}: {evidence}")
```

Then use:

```python
assert_conversation_has_tool_evidence(result, "list_dir")
assert_conversation_has_tool_evidence(result, "git", "run_shell_command")
assert_conversation_has_tool_evidence(result, "read_file")
```

- [ ] **Step 4: Run scenario tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/scenarios -q
```

Expected: scenario tests pass with tool evidence assertions.

- [ ] **Step 5: Run PTY live tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected: all PTY tests pass in an environment with real OpenAI-compatible provider env configured. If provider env is missing, the failure message must explicitly say the live PTY tests require real provider env.

- [ ] **Step 6: Commit Task 5**

Run:

```bash
git add tests/scenarios tests/e2e/test_tui_pty_live.py
git commit -m "adapt tui tests to schema tool evidence"
```

## Task 6: Documentation and Legacy Cleanup

**Files:**
- Modify: `README.md`
- Modify: `MendCode_开发方案.md`
- Modify: `MendCode_全局路线图.md`
- Modify: `MendCode_问题记录.md`
- Optional modify: `app/tui/intent.py`

- [ ] **Step 1: Update README current state**

In `README.md`, replace references to natural shell routing with:

```markdown
- 自然语言请求统一进入 AgentLoop，由模型通过 OpenAI-compatible `tool_calls` 调用 schema 工具。
- Slash commands 仍由 TUI 本地处理，例如 `/status`、`/sessions`、`/resume`。
- 如果 provider 不支持原生 tools，MendCode 会明确报错，不会退回普通聊天编造本地事实。
```

- [ ] **Step 2: Update development plan**

In `MendCode_开发方案.md`, update Provider and TUI sections:

```markdown
- [x] 自然语言 TUI 请求统一走 schema tool-call AgentLoop。
- [x] Provider 不再对正常用户轮次静默 fallback 到 JSON action 或 free text。
- [x] TUI 规则路由不再直接执行自然语言 shell/tool 请求。
```

Add remaining future work:

```markdown
- [ ] 删除 legacy scripted action compatibility path once CLI repair no longer uses it.
- [ ] 将 `/fix` 兼容路径迁移为纯工具化 repair flow。
```

- [ ] **Step 3: Update problem record**

In `MendCode_问题记录.md`, add a new issue:

```markdown
### 问题：规则旁路会绕开模型工具选择

状态：已修复主路径

现象：

自然语言 `ls`、`git status`、文件读取等请求曾由 TUI 规则直接执行，和模型 schema tool-call 主线并行。

根因：

规则路径最初用于补足工具能力，但在工具体系建立后变成第二套执行入口。

处理：

普通自然语言请求统一交给 AgentLoop，模型必须通过 schema tool call 获取本地事实。Slash commands 和 pending confirmation 仍作为 TUI 控制逻辑保留。

后续约束：

新增自然语言能力时，优先新增 ToolSpec 和测试，不新增 TUI 规则执行旁路。
```

- [ ] **Step 4: Remove dead intent code if unused**

Run:

```bash
rg -n "build_intent_router|IntentRouter|RuleBasedIntentRouter|plan_rule_based_shell_command|looks_like_tool_request" app tests
```

If only tests import these symbols, delete `app/tui/intent.py` and remove or rewrite those tests. If `/fix` still uses intent code, keep only fix-specific helpers and rename the module to avoid implying natural-language routing.

- [ ] **Step 5: Run full verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected: pytest and ruff pass. PTY live tests pass when provider env is configured.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add README.md MendCode_开发方案.md MendCode_全局路线图.md MendCode_问题记录.md app/tui/intent.py tests/unit/test_tui_intent.py
git commit -m "document schema tool call only runtime"
```

If `app/tui/intent.py` was not modified, omit it from `git add`.

## Task 7: Final Regression Pass

**Files:**
- No production file should change unless regression commands reveal a bug.

- [ ] **Step 1: Check git status**

Run:

```bash
git status --short --branch
```

Expected: clean working tree before final verification, or only intentional uncommitted fixes.

- [ ] **Step 2: Run full unit/integration/scenario test suite**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run lint**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: `All checks passed!`

- [ ] **Step 4: Run complete PTY live tests**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest tests/e2e/test_tui_pty_live.py -q
```

Expected: all PTY tests pass. If provider env is missing, record that exact blocker and do not claim PTY success.

- [ ] **Step 5: Inspect final commits**

Run:

```bash
git log --oneline -6
git status --short --branch
```

Expected: recent commits correspond to the tasks above and the working tree is clean.

## Self-Review Notes

- Spec coverage: The plan covers ToolPool-only provider exposure, strict native `tool_calls`, TUI normal text through AgentLoop, Harness dispatch and permission, `final_response` tool usage, tests, PTY verification, and docs.
- Legacy scope: The plan removes legacy JSON actions from provider-driven user turns first, while keeping direct `loop_input.actions` as explicit compatibility until CLI repair migration is safe.
- Safety: Slash commands and pending confirmation remain local; shell and verification semantics remain under ShellPolicy and declared verification gates.
