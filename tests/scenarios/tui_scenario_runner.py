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
                workspace_path=None,
                trace_path=None,
                changed_files=[],
                diff_stat=None,
                verification_status="not_run",
                summary="Verification command required",
                recommended_actions=[],
            ),
        )


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
    forbidden = [
        '"observation"',
        '"payload"',
        '"tool_name"',
        "{\n",
        "TraceEvent(",
        "{'observation':",
        "{'payload':",
        "'tool_name'",
        "AgentStep(",
        "Observation(",
        "ToolCallAction(",
    ]
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
    matching_steps: list[dict[str, Any]] = []
    for result in transcript.tool_results:
        for step in result.get("steps", []):
            if not isinstance(step, dict) or step.get("action") != tool_name:
                continue
            matching_steps.append(step)
            if _has_successful_meaningful_tool_evidence(step, tool_name):
                return
    if matching_steps:
        _fail(
            transcript,
            f"expected successful meaningful compact tool_result evidence for {tool_name}",
        )
    _fail(transcript, f"expected compact tool_result evidence for {tool_name}")


def _has_successful_meaningful_tool_evidence(
    step: dict[str, Any],
    tool_name: str,
) -> bool:
    status = str(step.get("status", "")).strip().lower()
    if status not in {"succeeded", "success", "successful", "passed", "pass", "ok"}:
        return False
    payload = step.get("payload")
    if isinstance(payload, dict) and payload:
        return True
    summary = str(step.get("summary", "")).strip()
    return bool(summary) and summary.lower() not in {
        tool_name.lower(),
        "succeeded",
        "success",
        "successful",
        "passed",
        "pass",
        "ok",
    }
