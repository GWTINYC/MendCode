# TUI Experience Scenario Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic TUI scenario test system that simulates common user conversations and catches routing mistakes, fabricated answers, noisy output, and poor answer quality.

**Architecture:** Add a `tests/scenarios/` harness around `MendCodeTextualApp.run_test()` with fake chat/tool/shell dependencies and a stable `ScenarioTranscript` read model. Scenario tests assert route events, tool evidence, visible answer quality, and compact conversation logs without using real models or network calls.

**Tech Stack:** Python 3.12, pytest, pytest-asyncio, Textual `run_test()`, existing `MendCodeTextualApp`, Pydantic agent result models.

---

## File Structure

- Create: `tests/scenarios/__init__.py`
  - Marks scenario tests as a package.
- Create: `tests/scenarios/tui_scenario_runner.py`
  - Owns repo fixture creation, fake dependencies, `TuiScenario`, `ScenarioTranscript`, and shared experience assertions.
- Create: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
  - Covers common repository inspection questions such as directory listing, `git status`, diff, and project detection.
- Create: `tests/scenarios/test_tui_file_question_scenarios.py`
  - Covers file discovery, file reading, and no-fabrication assertions for local file questions.
- Create: `tests/scenarios/test_tui_failure_scenarios.py`
  - Covers missing file, dangerous shell confirmation, repeated equivalent tool calls, and concise failure messages.
- Create: `tests/scenarios/test_tui_resume_scenarios.py`
  - Covers `/sessions`, `/resume`, and follow-up questions using compact restored context.
- Modify: `MendCode_开发方案.md`
  - Record the scenario test system and current coverage after implementation.

## Task 1: Scenario Runner Harness

**Files:**
- Create: `tests/scenarios/__init__.py`
- Create: `tests/scenarios/tui_scenario_runner.py`
- Test: `tests/scenarios/test_tui_repository_inspection_scenarios.py`

- [ ] **Step 1: Create package marker**

Create `tests/scenarios/__init__.py`:

```python
"""Scenario-level TUI experience tests."""
```

- [ ] **Step 2: Write the first failing smoke scenario**

Create `tests/scenarios/test_tui_repository_inspection_scenarios.py`:

```python
import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_has_evidence_from_observation,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_directory_listing_is_tool_backed_and_concise(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="directory listing",
            repo_files={
                "README.md": "MendCode\n",
                "app/main.py": "print('hello')\n",
            },
            user_inputs=["帮我查看当前文件夹里的文件"],
            tool_steps=[
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={
                        "relative_path": ".",
                        "total_entries": 2,
                        "entries": [
                            {"relative_path": "README.md", "name": "README.md", "type": "file"},
                            {"relative_path": "app", "name": "app", "type": "directory"},
                        ],
                    },
                )
            ],
            final_summary="当前文件夹包含 README.md 和 app。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "list_dir")
    assert_visible_answer_contains(transcript, "README.md")
    assert_visible_answer_contains(transcript, "app")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)
```

- [ ] **Step 3: Run the smoke scenario and verify it fails**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios/test_tui_repository_inspection_scenarios.py::test_directory_listing_is_tool_backed_and_concise
```

Expected: fail during import with `No module named 'tests.scenarios.tui_scenario_runner'`.

- [ ] **Step 4: Implement `tui_scenario_runner.py` data models and fakes**

Create `tests/scenarios/tui_scenario_runner.py` with:

```python
import asyncio
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.session import AgentSessionTurn, ReviewSummary
from app.config.settings import Settings
from app.schemas.agent_action import FinalResponseAction, Observation, ToolCallAction
from app.tui.app import MendCodeTextualApp
from app.tui.chat import ChatResponse
from app.workspace.shell_executor import ShellCommandResult


@dataclass(frozen=True)
class ScenarioToolStep:
    action: str
    status: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    args: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class TuiScenario:
    name: str
    user_inputs: list[str]
    repo_files: dict[str, str] = field(default_factory=dict)
    tool_steps: list[ScenarioToolStep] = field(default_factory=list)
    final_summary: str = "完成。"
    chat_response: str = "chat response"
    shell_stdout: str = "README.md\n"


@dataclass(frozen=True)
class ScenarioTranscript:
    scenario_name: str
    user_inputs: list[str]
    visible_messages: list[str]
    jsonl_records: list[dict[str, Any]]
    chat_calls: list[str]
    tool_calls: list[str]
    shell_calls: list[tuple[str, Path, bool]]

    @property
    def visible_text(self) -> str:
        return "\n".join(self.visible_messages)

    @property
    def route_events(self) -> list[dict[str, Any]]:
        return [
            record["payload"]
            for record in self.jsonl_records
            if record.get("event_type") == "intent"
        ]

    @property
    def tool_results(self) -> list[dict[str, Any]]:
        return [
            record["payload"]
            for record in self.jsonl_records
            if record.get("event_type") == "tool_result"
        ]

    def debug_text(self) -> str:
        return "\n".join(
            [
                f"scenario: {self.scenario_name}",
                f"inputs: {self.user_inputs}",
                "visible:",
                self.visible_text,
                f"routes: {self.route_events}",
                f"chat_calls: {self.chat_calls}",
                f"tool_calls: {self.tool_calls}",
                f"shell_calls: {self.shell_calls}",
                f"tool_results: {self.tool_results}",
            ]
        )


class FakeChatResponder:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[str] = []

    def respond(self, message: str, context) -> ChatResponse:
        self.calls.append(message)
        return ChatResponse(content=self.response)


class FakeShellExecutor:
    def __init__(self, stdout: str) -> None:
        self.stdout = stdout
        self.calls: list[tuple[str, Path, bool]] = []

    def __call__(self, *, command, cwd, policy, confirmed=False) -> ShellCommandResult:
        self.calls.append((command, cwd, confirmed))
        return ShellCommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=0,
            status="passed",
            stdout_excerpt=self.stdout,
            stderr_excerpt="",
            duration_ms=1,
            risk_level="low",
            requires_confirmation=False,
        )


class FakeToolAgentRunner:
    def __init__(self, scenario: TuiScenario, repo_path: Path) -> None:
        self.scenario = scenario
        self.repo_path = repo_path
        self.calls: list[str] = []

    def __call__(self, *, problem_statement: str) -> AgentLoopResult:
        self.calls.append(problem_statement)
        steps: list[AgentStep] = []
        for index, item in enumerate(self.scenario.tool_steps, start=1):
            error_message = item.error_message
            if item.status in {"failed", "rejected"} and error_message is None:
                error_message = item.summary
            steps.append(
                AgentStep(
                    index=index,
                    action=ToolCallAction(
                        type="tool_call",
                        action=item.action,
                        reason="scenario tool step",
                        args=item.args,
                    ),
                    observation=Observation(
                        status=item.status,
                        summary=item.summary,
                        payload={"tool_name": item.action, **item.payload},
                        error_message=error_message,
                    ),
                )
            )
        steps.append(
            AgentStep(
                index=len(steps) + 1,
                action=FinalResponseAction(
                    type="final_response",
                    status="completed",
                    summary=self.scenario.final_summary,
                ),
                observation=Observation(
                    status="succeeded",
                    summary="Recorded agent action",
                    payload={},
                ),
            )
        )
        return AgentLoopResult(
            run_id=f"scenario-{self.scenario.name.replace(' ', '-')}",
            status="completed",
            summary=self.scenario.final_summary,
            trace_path=str(self.repo_path / "data" / "traces" / "scenario.jsonl"),
            workspace_path=str(self.repo_path),
            steps=steps,
        )


class FakeSession:
    def run_turn(
        self,
        *,
        problem_statement: str,
        verification_commands: list[str],
        step_budget: int = 12,
    ) -> AgentSessionTurn:
        result = AgentLoopResult(
            run_id="scenario-fix",
            status="needs_user_confirmation",
            summary="Verification command required",
            trace_path=None,
            workspace_path=None,
            steps=[],
        )
        return AgentSessionTurn(
            index=1,
            problem_statement=problem_statement,
            result=result,
            review=ReviewSummary(
                status="needs_user_confirmation",
                verification_status="not_run",
                summary="Verification command required",
            ),
        )
```

- [ ] **Step 5: Implement repo creation and runner**

Append this code to `tests/scenarios/tui_scenario_runner.py`:

```python
def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="MendCode",
        app_version="0.0.0",
        project_root=tmp_path,
        data_dir=tmp_path / "data",
        traces_dir=tmp_path / "data" / "traces",
        workspace_root=tmp_path / ".worktrees",
        verification_timeout_seconds=60,
        cleanup_success_workspace=False,
        provider="scripted",
    )


def init_git_repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo_path = tmp_path / "repo"
    repo_path.mkdir()
    subprocess.run(["git", "init"], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    if not files:
        files = {"README.md": "demo\n"}
    for relative_path, content in files.items():
        target = repo_path / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


async def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


class TuiScenarioRunner:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path

    async def run(self, scenario: TuiScenario) -> ScenarioTranscript:
        repo_path = init_git_repo(self.tmp_path, scenario.repo_files)
        settings = make_settings(self.tmp_path)
        chat_responder = FakeChatResponder(scenario.chat_response)
        shell_executor = FakeShellExecutor(scenario.shell_stdout)
        tool_runner = FakeToolAgentRunner(scenario, repo_path)
        app = MendCodeTextualApp(
            repo_path=repo_path,
            settings=settings,
            agent_session=FakeSession(),
            chat_responder=chat_responder,
            shell_executor=shell_executor,
            tool_agent_runner=tool_runner,
        )

        async with app.run_test() as pilot:
            await pilot.pause()
            for user_input in scenario.user_inputs:
                app.handle_user_input(user_input)
                await wait_until(lambda: not app.session_state.running)
                await pilot.pause()

        records: list[dict[str, Any]] = []
        jsonl_path = app.session_state.conversation_jsonl_path
        if jsonl_path is not None and jsonl_path.exists():
            records = [
                json.loads(line)
                for line in jsonl_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        return ScenarioTranscript(
            scenario_name=scenario.name,
            user_inputs=scenario.user_inputs,
            visible_messages=list(app.message_texts),
            jsonl_records=records,
            chat_calls=list(chat_responder.calls),
            tool_calls=list(tool_runner.calls),
            shell_calls=list(shell_executor.calls),
        )
```

- [ ] **Step 6: Implement experience assertions**

Append this code to `tests/scenarios/tui_scenario_runner.py`:

```python
def _fail(transcript: ScenarioTranscript, message: str) -> None:
    raise AssertionError(f"{message}\n\n{transcript.debug_text()}")


def assert_used_tool_path(transcript: ScenarioTranscript) -> None:
    if not transcript.tool_calls:
        _fail(transcript, "expected scenario to call the tool agent")
    if not any(event.get("kind") == "tool" for event in transcript.route_events):
        _fail(transcript, "expected an intent route with kind=tool")


def assert_did_not_use_chat(transcript: ScenarioTranscript) -> None:
    if transcript.chat_calls:
        _fail(transcript, f"expected no chat calls, got {transcript.chat_calls}")


def assert_visible_answer_contains(transcript: ScenarioTranscript, text: str) -> None:
    if text not in transcript.visible_text:
        _fail(transcript, f"expected visible transcript to contain {text!r}")


def assert_no_raw_trace_or_large_json_dump(transcript: ScenarioTranscript) -> None:
    forbidden = ['"observation"', '"payload"', '"tool_name"', "{\n", "TraceEvent("]
    for token in forbidden:
        if token in transcript.visible_text:
            _fail(transcript, f"visible transcript contains raw internals: {token}")


def assert_answer_is_concise(
    transcript: ScenarioTranscript,
    *,
    max_lines: int,
    max_chars: int,
) -> None:
    latest_message = transcript.visible_messages[-1] if transcript.visible_messages else ""
    lines = latest_message.splitlines()
    if len(lines) > max_lines:
        _fail(transcript, f"latest visible answer has {len(lines)} lines, limit is {max_lines}")
    if len(latest_message) > max_chars:
        _fail(
            transcript,
            f"latest visible answer has {len(latest_message)} chars, limit is {max_chars}",
        )


def assert_has_evidence_from_observation(
    transcript: ScenarioTranscript,
    tool_name: str,
) -> None:
    for result in transcript.tool_results:
        for step in result.get("steps", []):
            if step.get("action") == tool_name:
                return
    _fail(transcript, f"expected compact tool_result evidence for {tool_name}")
```

- [ ] **Step 7: Run the smoke scenario and verify it passes**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios/test_tui_repository_inspection_scenarios.py::test_directory_listing_is_tool_backed_and_concise
```

Expected: pass.

- [ ] **Step 8: Commit Task 1**

Run:

```bash
git add tests/scenarios/__init__.py tests/scenarios/tui_scenario_runner.py tests/scenarios/test_tui_repository_inspection_scenarios.py
git commit -m "Add TUI scenario runner"
```

## Task 2: Repository Inspection Scenario Coverage

**Files:**
- Modify: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Modify: `tests/scenarios/tui_scenario_runner.py`

- [ ] **Step 1: Add shell-path assertion helper**

Add this function to `tests/scenarios/tui_scenario_runner.py`:

```python
def assert_used_shell_command(transcript: ScenarioTranscript, command: str) -> None:
    commands = [call[0] for call in transcript.shell_calls]
    if command not in commands:
        _fail(transcript, f"expected shell command {command!r}, got {commands!r}")
```

- [ ] **Step 2: Add `git status` scenario**

Append this test to `tests/scenarios/test_tui_repository_inspection_scenarios.py`:

```python
from tests.scenarios.tui_scenario_runner import assert_used_shell_command


async def test_git_status_request_uses_safe_shell_and_stays_compact(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="git status",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["看下 git status"],
            shell_stdout=" M README.md\n",
        )
    )

    assert_used_shell_command(transcript, "git status")
    assert_visible_answer_contains(transcript, "git status")
    assert_answer_is_concise(transcript, max_lines=12, max_chars=900)
    assert_no_raw_trace_or_large_json_dump(transcript)
```

- [ ] **Step 3: Add project detection scenario**

Append this test:

```python
async def test_project_stack_question_is_tool_backed(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="project stack",
            repo_files={
                "pyproject.toml": "[project]\nname = 'demo'\n",
                "app/main.py": "print('hello')\n",
            },
            user_inputs=["项目是什么技术栈"],
            tool_steps=[
                ScenarioToolStep(
                    action="detect_project",
                    status="succeeded",
                    summary="Detected project",
                    payload={
                        "project_type": "python",
                        "verification_commands": ["python -m pytest -q"],
                    },
                )
            ],
            final_summary="这是 Python 项目。",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "detect_project")
    assert_visible_answer_contains(transcript, "Python")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)
```

- [ ] **Step 4: Run repository inspection scenarios**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios/test_tui_repository_inspection_scenarios.py
```

Expected: all repository inspection scenarios pass.

- [ ] **Step 5: Commit Task 2**

Run:

```bash
git add tests/scenarios/tui_scenario_runner.py tests/scenarios/test_tui_repository_inspection_scenarios.py
git commit -m "Add repository inspection scenarios"
```

## Task 3: File Question Scenario Coverage

**Files:**
- Create: `tests/scenarios/test_tui_file_question_scenarios.py`
- Modify: `tests/scenarios/tui_scenario_runner.py`

- [ ] **Step 1: Add no-fabrication assertion helper**

Add this function to `tests/scenarios/tui_scenario_runner.py`:

```python
def assert_no_fabricated_command_claims(transcript: ScenarioTranscript) -> None:
    bad_phrases = [
        "正在搜索",
        "我来查看",
        "命令 | 结果",
        "docs/mendcode-dev-plan.md",
        "MendCode 是一款基于 AI 的代码开发助手",
    ]
    for phrase in bad_phrases:
        if phrase in transcript.visible_text:
            _fail(transcript, f"visible transcript contains known fabricated phrase: {phrase}")
```

- [ ] **Step 2: Add file first-line scenario**

Create `tests/scenarios/test_tui_file_question_scenarios.py`:

```python
import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_did_not_use_chat,
    assert_has_evidence_from_observation,
    assert_no_fabricated_command_claims,
    assert_no_raw_trace_or_large_json_dump,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_file_first_line_question_reads_actual_file(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="file first line",
            repo_files={
                "MendCode_开发方案.md": "# MendCode 开发方案\n\n## 1. 文档职责\n",
            },
            user_inputs=["MendCode_开发方案第一句话是什么"],
            tool_steps=[
                ScenarioToolStep(
                    action="read_file",
                    status="succeeded",
                    summary="Read MendCode_开发方案.md",
                    payload={
                        "relative_path": "MendCode_开发方案.md",
                        "content_excerpt": "# MendCode 开发方案\n\n## 1. 文档职责\n",
                        "content_length": 28,
                        "content_truncated": False,
                    },
                    args={"path": "MendCode_开发方案.md", "end_line": 3},
                )
            ],
            final_summary="第一句话是：# MendCode 开发方案",
        )
    )

    assert_used_tool_path(transcript)
    assert_did_not_use_chat(transcript)
    assert_has_evidence_from_observation(transcript, "read_file")
    assert_visible_answer_contains(transcript, "MendCode 开发方案")
    assert_no_fabricated_command_claims(transcript)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=10, max_chars=600)
```

- [ ] **Step 3: Add provider config search scenario**

Append this test:

```python
async def test_provider_config_question_uses_code_search(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="provider config search",
            repo_files={
                "app/config/settings.py": "MENDCODE_PROVIDER = 'scripted'\n",
                "README.md": "export MENDCODE_PROVIDER=scripted\n",
            },
            user_inputs=["帮我找一下配置 provider 的地方"],
            tool_steps=[
                ScenarioToolStep(
                    action="rg",
                    status="succeeded",
                    summary="Found provider config references",
                    payload={
                        "query": "MENDCODE_PROVIDER",
                        "total_matches": 2,
                        "matches": [
                            {"relative_path": "README.md", "line_number": 1},
                            {"relative_path": "app/config/settings.py", "line_number": 1},
                        ],
                    },
                    args={"query": "MENDCODE_PROVIDER"},
                )
            ],
            final_summary="provider 配置主要在 README.md 和 app/config/settings.py。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_evidence_from_observation(transcript, "rg")
    assert_visible_answer_contains(transcript, "README.md")
    assert_visible_answer_contains(transcript, "app/config/settings.py")
    assert_answer_is_concise(transcript, max_lines=10, max_chars=700)
```

- [ ] **Step 4: Run file question scenarios**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios/test_tui_file_question_scenarios.py
```

Expected: all file question scenarios pass.

- [ ] **Step 5: Commit Task 3**

Run:

```bash
git add tests/scenarios/tui_scenario_runner.py tests/scenarios/test_tui_file_question_scenarios.py
git commit -m "Add file question scenarios"
```

## Task 4: Failure And Verbosity Scenarios

**Files:**
- Create: `tests/scenarios/test_tui_failure_scenarios.py`
- Modify: `tests/scenarios/tui_scenario_runner.py`

- [ ] **Step 1: Add repeated-tool assertion helper**

Add this function to `tests/scenarios/tui_scenario_runner.py`:

```python
def assert_no_repeated_equivalent_tool_calls(
    transcript: ScenarioTranscript,
    *,
    limit: int,
) -> None:
    counts: dict[tuple[str, str], int] = {}
    for result in transcript.tool_results:
        for step in result.get("steps", []):
            action = str(step.get("action"))
            payload = step.get("payload", {})
            relative_path = "."
            if isinstance(payload, dict):
                relative_path = str(payload.get("relative_path", "."))
            key = (action, relative_path)
            counts[key] = counts.get(key, 0) + 1
    repeated = {key: count for key, count in counts.items() if count > limit}
    if repeated:
        _fail(transcript, f"repeated equivalent tool calls exceeded limit {limit}: {repeated}")
```

- [ ] **Step 2: Add missing-file scenario**

Create `tests/scenarios/test_tui_failure_scenarios.py`:

```python
import pytest

from tests.scenarios.tui_scenario_runner import (
    ScenarioToolStep,
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_has_evidence_from_observation,
    assert_no_fabricated_command_claims,
    assert_no_raw_trace_or_large_json_dump,
    assert_no_repeated_equivalent_tool_calls,
    assert_used_tool_path,
    assert_visible_answer_contains,
)

pytestmark = pytest.mark.asyncio


async def test_missing_file_response_is_short_and_honest(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="missing file",
            repo_files={"README.md": "demo\n"},
            user_inputs=["读取 missing.md"],
            tool_steps=[
                ScenarioToolStep(
                    action="read_file",
                    status="rejected",
                    summary="Unable to read missing.md",
                    payload={"relative_path": "missing.md"},
                    error_message="file does not exist",
                    args={"path": "missing.md"},
                )
            ],
            final_summary="没有找到 missing.md，无法读取该文件。",
        )
    )

    assert_used_tool_path(transcript)
    assert_has_evidence_from_observation(transcript, "read_file")
    assert_visible_answer_contains(transcript, "无法读取")
    assert_no_fabricated_command_claims(transcript)
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=8, max_chars=500)
```

- [ ] **Step 3: Add repeated-list-dir regression scenario**

Append this test:

```python
async def test_repeated_equivalent_tool_calls_are_flagged_by_assertion(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="repeated list dir",
            repo_files={"README.md": "demo\n"},
            user_inputs=["帮我查看当前文件夹里的文件"],
            tool_steps=[
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={"relative_path": ".", "entries": [], "total_entries": 0},
                ),
                ScenarioToolStep(
                    action="list_dir",
                    status="succeeded",
                    summary="Listed .",
                    payload={"relative_path": ".", "entries": [], "total_entries": 0},
                ),
            ],
            final_summary="当前目录为空。",
        )
    )

    assert_no_repeated_equivalent_tool_calls(transcript, limit=2)
```

This scenario should pass with two calls. A future regression test can lower the limit or add a third step to verify failure messaging if needed.

- [ ] **Step 4: Add dangerous shell scenario**

Append this test:

```python
async def test_dangerous_shell_requests_confirmation_without_execution(tmp_path):
    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="dangerous shell",
            repo_files={"README.md": "demo\n"},
            user_inputs=["rm README.md"],
        )
    )

    if transcript.shell_calls:
        raise AssertionError(transcript.debug_text())
    assert_visible_answer_contains(transcript, "需要确认")
    assert_answer_is_concise(transcript, max_lines=8, max_chars=700)
```

- [ ] **Step 5: Run failure scenarios**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios/test_tui_failure_scenarios.py
```

Expected: all failure scenarios pass.

- [ ] **Step 6: Commit Task 4**

Run:

```bash
git add tests/scenarios/tui_scenario_runner.py tests/scenarios/test_tui_failure_scenarios.py
git commit -m "Add TUI failure experience scenarios"
```

## Task 5: Resume Scenario Coverage

**Files:**
- Create: `tests/scenarios/test_tui_resume_scenarios.py`
- Modify: `tests/scenarios/tui_scenario_runner.py`

- [ ] **Step 1: Add saved conversation helper**

Add this function to `tests/scenarios/tui_scenario_runner.py`:

```python
def write_saved_conversation(
    data_dir: Path,
    *,
    stem: str,
    records: list[dict[str, object]],
) -> None:
    conversations_dir = data_dir / "conversations"
    conversations_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = conversations_dir / f"{stem}.jsonl"
    markdown_path = conversations_dir / f"{stem}.md"
    jsonl_path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(
        "\n".join(
            [
                "# MendCode Conversation",
                "",
                "repo: /repo/old",
                "started_at: 2026-04-26T10:00:00+08:00",
                f"run_id: {stem.rsplit('-', 1)[-1]}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def message_record(sequence: int, timestamp: str, role: str, message: str) -> dict[str, object]:
    return {
        "sequence": sequence,
        "timestamp": timestamp,
        "event_type": "message",
        "payload": {"role": role, "message": message},
    }
```

- [ ] **Step 2: Add resume command scenario**

Create `tests/scenarios/test_tui_resume_scenarios.py`:

```python
import pytest

from tests.scenarios.tui_scenario_runner import (
    TuiScenario,
    TuiScenarioRunner,
    assert_answer_is_concise,
    assert_no_raw_trace_or_large_json_dump,
    assert_visible_answer_contains,
    message_record,
    write_saved_conversation,
)

pytestmark = pytest.mark.asyncio


async def test_resume_restores_compact_context_for_followup(tmp_path):
    data_dir = tmp_path / "data"
    full_content = "large content\n" * 500
    write_saved_conversation(
        data_dir,
        stem="2026-04-26_100000-oldrun",
        records=[
            message_record(1, "2026-04-26T10:00:00+08:00", "You", "读取 README"),
            {
                "sequence": 2,
                "timestamp": "2026-04-26T10:00:01+08:00",
                "event_type": "tool_result",
                "payload": {
                    "status": "completed",
                    "summary": "Read README.md",
                    "trace_path": "/tmp/trace.jsonl",
                    "steps": [
                        {
                            "index": 1,
                            "action": {"type": "tool_call", "action": "read_file"},
                            "observation": {
                                "status": "succeeded",
                                "summary": "Read README.md",
                                "payload": {
                                    "relative_path": "README.md",
                                    "content": full_content,
                                },
                            },
                        }
                    ],
                },
            },
            message_record(
                3,
                "2026-04-26T10:00:02+08:00",
                "MendCode",
                "README 第一行是 MendCode。",
            ),
        ],
    )

    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="resume followup",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["/resume oldrun"],
        )
    )

    assert_visible_answer_contains(transcript, "session_id: oldrun")
    assert_visible_answer_contains(transcript, "README 第一行是 MendCode")
    assert "large content" not in transcript.visible_text
    assert_no_raw_trace_or_large_json_dump(transcript)
    assert_answer_is_concise(transcript, max_lines=18, max_chars=1500)
```

- [ ] **Step 3: Add sessions list scenario**

Append this test:

```python
async def test_sessions_lists_saved_conversation_ids(tmp_path):
    data_dir = tmp_path / "data"
    write_saved_conversation(
        data_dir,
        stem="2026-04-26_100000-oldrun",
        records=[
            message_record(1, "2026-04-26T10:00:00+08:00", "You", "old task"),
        ],
    )

    transcript = await TuiScenarioRunner(tmp_path).run(
        TuiScenario(
            name="sessions list",
            repo_files={"README.md": "MendCode\n"},
            user_inputs=["/sessions"],
        )
    )

    assert_visible_answer_contains(transcript, "Session List")
    assert_visible_answer_contains(transcript, "oldrun")
    assert_answer_is_concise(transcript, max_lines=8, max_chars=700)
```

- [ ] **Step 4: Run resume scenarios**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios/test_tui_resume_scenarios.py
```

Expected: all resume scenarios pass.

- [ ] **Step 5: Commit Task 5**

Run:

```bash
git add tests/scenarios/tui_scenario_runner.py tests/scenarios/test_tui_resume_scenarios.py
git commit -m "Add resume experience scenarios"
```

## Task 6: Common Question Coverage And Documentation

**Files:**
- Modify: `tests/scenarios/test_tui_repository_inspection_scenarios.py`
- Modify: `tests/scenarios/test_tui_file_question_scenarios.py`
- Modify: `tests/scenarios/test_tui_failure_scenarios.py`
- Modify: `MendCode_开发方案.md`

- [ ] **Step 1: Add scenario coverage registry comment**

At the top of `tests/scenarios/tui_scenario_runner.py`, add:

```python
# Scenario tests intentionally cover common user questions rather than isolated
# functions. Keep failures readable: route, visible answer, tool evidence, and
# verbosity should be obvious from ScenarioTranscript.debug_text().
```

- [ ] **Step 2: Ensure at least 10 common user questions are represented**

Count these scenarios after Tasks 1-5:

```text
1. 帮我查看当前文件夹里的文件
2. 看下 git status
3. 项目是什么技术栈
4. MendCode_开发方案第一句话是什么
5. 帮我找一下配置 provider 的地方
6. 读取 missing.md
7. rm README.md
8. /resume oldrun
9. /sessions
10. repeated list_dir regression
```

If any listed scenario is missing, add the missing test before continuing.

- [ ] **Step 3: Update development document**

In `MendCode_开发方案.md`, add a new testing status item under `## 5. 测试策略`:

```markdown
- TUI 体验场景测试：`tests/scenarios/` 覆盖常见用户问题，断言 route、tool evidence、简洁输出和 no-fabrication。
```

Under `### 3.5 TUI`, add:

```markdown
- [x] 第一批 TUI experience scenario tests 覆盖目录查看、文件问题、失败场景和 resume。
```

- [ ] **Step 4: Run scenario suite**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q tests/scenarios
```

Expected: all scenario tests pass.

- [ ] **Step 5: Run full verification**

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
```

Expected: all tests pass and ruff reports `All checks passed!`.

- [ ] **Step 6: Commit Task 6**

Run:

```bash
git add tests/scenarios MendCode_开发方案.md
git commit -m "Document TUI experience scenario coverage"
```

## Final Verification

Run:

```bash
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m pytest -q
PYTHONPATH=. uv run --isolated --python 3.12 --with-requirements requirements.txt python -m ruff check .
git status --short
```

Expected:

- pytest exits 0
- ruff exits 0 with `All checks passed!`
- `git status --short` shows no uncommitted changes after the final commit

