import asyncio
import inspect
import json
import subprocess
import threading
from pathlib import Path

import pytest

from app.agent.loop import AgentLoopInput, AgentLoopResult, AgentStep, run_agent_loop
from app.agent.openai_compatible import (
    ChatMessage,
    OpenAICompatibleAgentProvider,
    OpenAICompletion,
    OpenAIToolCall,
)
from app.agent.provider import AgentProviderStepInput, ProviderResponse
from app.agent.session import AgentSessionTurn, ReviewSummary, ToolCallSummary
from app.config.settings import Settings
from app.schemas.agent_action import FinalResponseAction, Observation, ToolCallAction
from app.tools.structured import ToolInvocation
from app.tui.app import (
    READ_ONLY_TOOL_AGENT_TOOLS,
    MendCodeTextualApp,
    _format_chat_line,
    _is_tool_availability_question,
    _status_bar_text,
)
from app.tui.chat import ChatResponse
from app.workspace.review_actions import ReviewActionResult
from app.workspace.shell_executor import ShellCommandResult

pytestmark = pytest.mark.asyncio


class NativeToolProvider:
    def __init__(self, batches: list[list[ToolInvocation]]) -> None:
        self.batches = batches
        self.calls: list[AgentProviderStepInput] = []

    def next_action(self, step_input: AgentProviderStepInput) -> ProviderResponse:
        self.calls.append(step_input)
        return ProviderResponse(
            status="succeeded",
            tool_invocations=self.batches[len(self.calls) - 1],
        )


def init_git_repo(path: Path) -> Path:
    repo_path = path / "repo"
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
    (repo_path / "README.md").write_text("demo\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "README.md"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
    )
    return repo_path


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


def make_turn() -> AgentSessionTurn:
    result = AgentLoopResult(
        run_id="agent-test",
        status="completed",
        summary="repair verified",
        trace_path="/tmp/trace.jsonl",
        workspace_path="/tmp/worktree",
        steps=[],
    )
    review = ReviewSummary(
        status="verified",
        workspace_path="/tmp/worktree",
        trace_path="/tmp/trace.jsonl",
        changed_files=["calculator.py"],
        diff_stat=" calculator.py | 2 +-\n",
        verification_status="passed",
        summary="repair verified",
        recommended_actions=["view_diff", "view_trace", "discard", "apply"],
    )
    return AgentSessionTurn(
        index=1,
        problem_statement="fix tests",
        result=result,
        review=review,
        tool_summaries=[
            ToolCallSummary(
                index=1,
                action="run_command",
                status="succeeded",
                summary="Ran command",
            )
        ],
    )


def write_conversation(
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


class FakeSession:
    def __init__(
        self,
        turn: AgentSessionTurn,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.turn = turn
        self.started = started
        self.release = release
        self.calls: list[tuple[str, list[str]]] = []

    def run_turn(
        self,
        *,
        problem_statement: str,
        verification_commands: list[str],
        step_budget: int = 12,
    ) -> AgentSessionTurn:
        self.calls.append((problem_statement, verification_commands))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=5)
        return self.turn


class FakeChatResponder:
    def __init__(self, response: str = "chat response") -> None:
        self.response = response
        self.calls: list[str] = []

    def respond(self, message: str, context) -> ChatResponse:
        self.calls.append(message)
        return ChatResponse(content=self.response)


class FakeShellExecutor:
    def __init__(
        self,
        result: ShellCommandResult | None = None,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.result = result
        self.started = started
        self.release = release
        self.calls: list[tuple[str, Path, bool]] = []

    def __call__(self, *, command, cwd, policy, confirmed=False) -> ShellCommandResult:
        self.calls.append((command, cwd, confirmed))
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=5)
        return self.result or ShellCommandResult(
            command=command,
            cwd=str(cwd),
            exit_code=0,
            status="passed",
            stdout_excerpt="README.md\n",
            stderr_excerpt="",
            duration_ms=1,
            risk_level="low",
            requires_confirmation=False,
        )


class FakeToolAgentRunner:
    def __init__(
        self,
        *,
        started: threading.Event | None = None,
        release: threading.Event | None = None,
    ) -> None:
        self.started = started
        self.release = release
        self.calls: list[str] = []

    def __call__(self, *, problem_statement: str) -> AgentLoopResult:
        self.calls.append(problem_statement)
        if self.started is not None:
            self.started.set()
        if self.release is not None:
            self.release.wait(timeout=5)
        return AgentLoopResult(
            run_id="agent-tool-test",
            status="completed",
            summary="当前文件夹包含 README.md。",
            trace_path="/tmp/tool-trace.jsonl",
            workspace_path="/tmp/repo",
            steps=[
                AgentStep(
                    index=1,
                    action=ToolCallAction(
                        type="tool_call",
                        action="list_dir",
                        reason="inspect current directory",
                        args={"path": "."},
                    ),
                    observation=Observation(
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
                                    "size_bytes": 5,
                                }
                            ],
                        },
                        error_message=None,
                    ),
                ),
                AgentStep(
                    index=2,
                    action=FinalResponseAction(
                        type="final_response",
                        status="completed",
                        summary="当前文件夹包含 README.md。",
                    ),
                    observation=Observation(
                        status="succeeded",
                        summary="Recorded agent action",
                        payload={},
                        error_message=None,
                    ),
                ),
            ],
        )


class LastSentenceOpenAIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def complete(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        tools: list[dict[str, object]],
        timeout_seconds: int,
    ) -> OpenAICompletion:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "tools": tools,
                "timeout_seconds": timeout_seconds,
            }
        )
        if len(self.calls) == 1:
            return OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call_glob",
                        name="glob_file_search",
                        arguments='{"pattern":"**/*问题记录*"}',
                    )
                ]
            )
        if len(self.calls) == 2:
            return OpenAICompletion(
                tool_calls=[
                    OpenAIToolCall(
                        id="call_read",
                        name="read_file",
                        arguments='{"path":"MendCode_问题记录.md","tail_lines":10}',
                    )
                ]
            )
        return OpenAICompletion(
            tool_calls=[
                OpenAIToolCall(
                    id="call_final",
                    name="final_response",
                    arguments='{"summary":"最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。"}',
                )
            ]
        )


class AgentLoopToolRunner:
    def __init__(self, *, repo_path: Path, settings: Settings) -> None:
        self.repo_path = repo_path
        self.settings = settings
        self.client = LastSentenceOpenAIClient()
        self.calls: list[str] = []

    def __call__(self, *, problem_statement: str) -> AgentLoopResult:
        self.calls.append(problem_statement)
        provider = OpenAICompatibleAgentProvider(
            model="test-model",
            api_key="secret-key",
            base_url="https://example.test/v1",
            timeout_seconds=12,
            client=self.client,
        )
        return run_agent_loop(
            AgentLoopInput(
                repo_path=self.repo_path,
                problem_statement=problem_statement,
                provider=provider,
                verification_commands=[],
                allowed_tools={"glob_file_search", "read_file"},
                permission_mode="guided",
                step_budget=12,
                use_worktree=False,
            ),
            self.settings,
        )


async def wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


async def test_app_starts_with_repo_header_and_help_hint(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
    )

    async with app.run_test() as pilot:
        await pilot.pause()

        assert "repo:" in app.header_text
        assert str(repo_path) in app.header_text
        assert "branch: master" in app.header_text or "branch: main" in app.header_text
        assert any("/help" in message for message in app.message_texts)
        assert app.session_state.conversation_markdown_path is not None
        assert app.session_state.conversation_jsonl_path is not None
        assert "Message 1 - System" in app.session_state.conversation_markdown_path.read_text(
            encoding="utf-8"
        )


async def test_app_renders_claude_style_status_and_message_prefix(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))

    async with app.run_test() as pilot:
        await pilot.pause()

        assert "mode guided" in _status_bar_text(app.session_state)
        assert "running idle" in _status_bar_text(app.session_state)
        assert "test not set" in _status_bar_text(app.session_state)
        assert _format_chat_line("You", "hello").plain == "You\nhello"
        assert _format_chat_line("Agent", "done").plain == "MendCode\ndone"


async def test_app_exposes_only_agent_request_for_normal_text_path(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=FakeToolAgentRunner(),
    )

    assert "intent_router" not in inspect.signature(MendCodeTextualApp).parameters
    assert not hasattr(app, "ensure_intent_router")
    assert not hasattr(app, "start_tool_request")
    assert hasattr(app, "start_agent_request")


async def test_status_shows_conversation_log_path(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=FakeSession(make_turn()),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_user_input("/status")
        await pilot.pause()

        assert app.session_state.conversation_markdown_path is not None
        assert any("conversation_log:" in message for message in app.message_texts)
        assert any(
            str(app.session_state.conversation_markdown_path) in message
            for message in app.message_texts
        )


async def test_sessions_command_lists_conversation_sessions(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    settings = make_settings(tmp_path)
    write_conversation(
        settings.data_dir,
        stem="2026-04-26_100000-oldrun",
        records=[
            message_record(1, "2026-04-26T10:00:00+08:00", "You", "old task"),
        ],
    )
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=settings,
        agent_session=FakeSession(make_turn()),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_user_input("/sessions")
        await pilot.pause()

        assert any("Session List" in message for message in app.message_texts)
        assert any("oldrun" in message for message in app.message_texts)


async def test_resume_command_renders_compact_previous_session_context(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    settings = make_settings(tmp_path)
    full_content = "readme content\n" * 500
    write_conversation(
        settings.data_dir,
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
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=settings,
        agent_session=FakeSession(make_turn()),
    )

    async with app.run_test() as pilot:
        await pilot.pause()
        app.handle_user_input("/resume oldrun")
        await pilot.pause()

        rendered = "\n".join(app.message_texts)
        assert "Resume Context" in rendered
        assert "session_id: oldrun" in rendered
        assert "MendCode: README 第一行是 MendCode。" in rendered
        assert "read_file: succeeded - Read README.md" in rendered
        assert full_content not in rendered
        assert any(
            history.role == "system" and "session_id: oldrun" in history.content
            for history in app.session_state.chat_history
        )


async def test_plain_message_without_test_command_runs_agent_tools_not_chat(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    chat_responder = FakeChatResponder("I can discuss the repo before tools run.")
    tool_agent_runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
        chat_responder=chat_responder,
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test():
        app.handle_user_input("what can you do?")
        await wait_until(lambda: not app.session_state.running)

        assert app.session_state.recent_task == "what can you do?"
        assert fake_session.calls == []
        assert chat_responder.calls == []
        assert tool_agent_runner.calls == ["what can you do?"]
        assert any("Running tools: what can you do?" in message for message in app.message_texts)
        assert app.session_state.conversation_jsonl_path is not None
        records = [
            json.loads(line)
            for line in app.session_state.conversation_jsonl_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        event_types = [record["event_type"] for record in records]
        assert "tool_result" in event_types
        assert "chat_result" not in event_types


async def test_direct_shell_text_runs_agent_tools_not_shell_executor(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    shell_executor = FakeShellExecutor()
    tool_agent_runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        shell_executor=shell_executor,
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test():
        app.handle_user_input("ls")
        await wait_until(lambda: not app.session_state.running)

        assert tool_agent_runner.calls == ["ls"]
        assert shell_executor.calls == []
        assert app.session_state.pending_shell is None
        assert any("README.md" in message for message in app.message_texts)
        assert app.session_state.conversation_jsonl_path is not None
        records = [
            json.loads(line)
            for line in app.session_state.conversation_jsonl_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        event_types = [record["event_type"] for record in records]
        assert "tool_result" in event_types
        assert "shell_result" not in event_types


async def test_natural_language_shell_request_runs_planned_command(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    shell_executor = FakeShellExecutor()
    tool_agent_runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        shell_executor=shell_executor,
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test():
        app.handle_user_input("列一下当前目录")
        await wait_until(lambda: not app.session_state.running)

        assert tool_agent_runner.calls == ["列一下当前目录"]
        assert shell_executor.calls == []


async def test_natural_language_file_listing_uses_tool_agent_not_chat_or_shell(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    shell_executor = FakeShellExecutor()
    chat_responder = FakeChatResponder("fabricated answer")
    tool_agent_runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        chat_responder=chat_responder,
        shell_executor=shell_executor,
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test():
        app.handle_user_input("帮我查看当前文件夹里的文件")
        await wait_until(lambda: not app.session_state.running)

        assert tool_agent_runner.calls == ["帮我查看当前文件夹里的文件"]
        assert chat_responder.calls == []
        assert shell_executor.calls == []
        assert any("list_dir" in message for message in app.message_texts)
        assert any("README.md" in message for message in app.message_texts)
        assert all("/tmp/tool-trace.jsonl" not in message for message in app.message_texts)
        assert all("trace_path" not in message for message in app.message_texts)
        assert app.session_state.conversation_markdown_path is not None
        markdown = app.session_state.conversation_markdown_path.read_text(encoding="utf-8")
        assert "intent" in markdown
        assert '"kind": "agent"' in markdown
        assert '"source": "schema_tool_call"' in markdown
        assert "Tool Result" in markdown
        assert "README.md" in markdown
        assert "/tmp/tool-trace.jsonl" in markdown
        assert app.session_state.conversation_jsonl_path is not None
        records = [
            json.loads(line)
            for line in app.session_state.conversation_jsonl_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        assert "tool_result" in [record["event_type"] for record in records]
        tool_payload = next(
            record["payload"] for record in records if record["event_type"] == "tool_result"
        )
        assert tool_payload["trace_path"] == "/tmp/tool-trace.jsonl"
        assert tool_payload["step_count"] == 2
        assert tool_payload["steps"][0]["action"] == "list_dir"
        assert "observation" not in tool_payload["steps"][0]


async def test_tool_availability_answer_uses_actual_read_only_tool_pool(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    settings = make_settings(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=settings)

    result = app._run_tool_agent_loop(problem_statement="现在你能用哪些工具")

    assert result.status == "completed"
    assert "glob_file_search" in result.summary
    assert "session_status" in result.summary
    assert result.steps[0].tool_invocation is not None
    assert result.steps[0].tool_invocation.source == "openai_tool_call"


async def test_tui_tool_agent_allows_evolution_rule_review_tools() -> None:
    assert {
        "evolution_rule_list",
        "evolution_rule_view",
        "evolution_rule_accept",
        "evolution_rule_reject",
        "evolution_rule_accept_with_edits",
    }.issubset(READ_ONLY_TOOL_AGENT_TOOLS)


async def test_evolution_rule_accept_reaches_permission_confirmation(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    settings = make_settings(tmp_path)
    provider = NativeToolProvider(
        [
            [
                ToolInvocation(
                    id="call_evolution_rule_accept",
                    name="evolution_rule_accept",
                    args={"candidate_id": "rule-candidate-1"},
                    source="openai_tool_call",
                )
            ]
        ]
    )

    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="接受第一条规则",
            provider=provider,
            permission_mode="guided",
            allowed_tools=READ_ONLY_TOOL_AGENT_TOOLS,
            use_worktree=False,
        ),
        settings,
    )

    assert result.status == "needs_user_confirmation"
    assert result.steps[0].action.type == "user_confirmation_request"
    assert result.steps[0].action.tool_name == "evolution_rule_accept"


async def test_tool_availability_detection_does_not_hijack_repo_stack_question() -> None:
    assert not _is_tool_availability_question("what tools does this project use?")
    assert _is_tool_availability_question("what tools can you use?")


async def test_tui_last_sentence_question_completes_after_final_response_tool_call(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "MendCode_问题记录.md").write_text(
        "# MendCode 问题记录\n\n"
        "新增问题必须满足至少一条：\n\n"
        "- 影响工具闭环正确性\n"
        "- 影响权限边界\n"
        "- 影响会话可复盘性\n"
        "- 影响验证结论可信度\n"
        "- 影响长期架构方向\n\n"
        "不再记录纯讨论、一次性环境噪声、旧路线细枝末节。\n",
        encoding="utf-8",
    )
    settings = make_settings(tmp_path)
    tool_runner = AgentLoopToolRunner(repo_path=repo_path, settings=settings)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=settings,
        tool_agent_runner=tool_runner,
    )

    async with app.run_test():
        app.handle_user_input("Mendcode问题记录的最后一句话是什么")
        await wait_until(lambda: not app.session_state.running)

        rendered = "\n".join(app.message_texts)
        assert "Provider failed" not in rendered
        assert "最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。" in rendered
        assert tool_runner.calls == ["Mendcode问题记录的最后一句话是什么"]
        assert len(tool_runner.client.calls) == 3
        assert app.session_state.conversation_jsonl_path is not None
        records = [
            json.loads(line)
            for line in app.session_state.conversation_jsonl_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        tool_payload = next(
            record["payload"] for record in records if record["event_type"] == "tool_result"
        )
        assert tool_payload["status"] == "completed"
        assert (
            tool_payload["summary"]
            == "最后一句是：不再记录纯讨论、一次性环境噪声、旧路线细枝末节。"
        )


async def test_pending_shell_reply_can_cancel_without_agent_request(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    shell_executor = FakeShellExecutor()
    tool_agent_runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        shell_executor=shell_executor,
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test() as pilot:
        app.session_state.set_pending_shell(
            command="rm README.md",
            risk_level="high",
            reason="test pending shell",
            source="test",
        )

        app.handle_user_input("取消")
        await pilot.pause()

        assert shell_executor.calls == []
        assert tool_agent_runner.calls == []
        assert app.session_state.pending_shell is None


async def test_pending_tool_cancel_records_rejection(tmp_path: Path) -> None:
    calls: list[AgentLoopInput] = []

    def runner(
        *, problem_statement: str, initial_observations=None
    ) -> AgentLoopResult:
        calls.append(
            AgentLoopInput(
                repo_path=tmp_path,
                problem_statement=problem_statement,
                initial_observations=initial_observations or [],
            )
        )
        return AgentLoopResult(
            run_id="agent-test",
            status="completed",
            summary="已取消。",
            trace_path=None,
            workspace_path=str(tmp_path),
            steps=[],
        )

    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=runner,
    )
    app.session_state.recent_task = "写入记忆"

    async with app.run_test() as pilot:
        app.session_state.set_pending_tool(
            tool_name="memory_write",
            arguments={"kind": "failure_lesson", "title": "lesson", "content": "body"},
            risk_level="medium",
            reason="tool memory_write requires confirmation",
            source="agent_loop",
            required_mode="workspace-write",
            preview={"title": "lesson"},
            tool_call_id="call_memory",
            tool_call_group_id="provider-1",
        )

        app.handle_user_input("取消")
        await pilot.pause()

        assert app.session_state.pending_tool is None
        assert "已取消待确认的工具调用" in "\n".join(app.message_texts)
        assert app.session_state.conversation_jsonl_path is not None
        records = [
            json.loads(line)
            for line in app.session_state.conversation_jsonl_path.read_text(
                encoding="utf-8"
            ).splitlines()
        ]
        assert any(
            record["event_type"] == "tool_confirmation_rejected"
            for record in records
        )
        assert calls
        rejection = calls[0].initial_observations[0]
        assert rejection.tool_invocation is not None
        assert rejection.tool_invocation.name == "memory_write"
        assert rejection.tool_invocation.group_id == "provider-1"
        assert rejection.observation.status == "rejected"
        assert rejection.observation.error_message == "user rejected tool memory_write"


async def test_confirmed_tool_result_is_passed_back_to_agent_loop(tmp_path: Path) -> None:
    calls: list[AgentLoopInput] = []

    def runner(
        *, problem_statement: str, initial_observations=None
    ) -> AgentLoopResult:
        calls.append(
            AgentLoopInput(
                repo_path=tmp_path,
                problem_statement=problem_statement,
                initial_observations=initial_observations or [],
            )
        )
        return AgentLoopResult(
            run_id="agent-test",
            status="completed",
            summary="工具已执行。",
            trace_path=None,
            workspace_path=str(tmp_path),
            steps=[],
        )

    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=runner,
    )
    app.session_state.recent_task = "写入记忆"
    app.session_state.set_pending_tool(
        tool_name="memory_write",
        arguments={"kind": "failure_lesson", "title": "lesson", "content": "body"},
        risk_level="medium",
        reason="tool memory_write requires confirmation",
        source="agent_loop",
        required_mode="workspace-write",
        preview={"title": "lesson"},
        tool_call_id="call_memory",
        tool_call_group_id="provider-1",
    )

    async with app.run_test() as pilot:
        app.handle_user_input("确认")
        await pilot.pause()

    assert calls
    assert calls[0].problem_statement == "写入记忆"
    assert calls[0].initial_observations
    record = calls[0].initial_observations[0]
    assert record.action is not None
    assert record.action.type == "tool_call"
    assert record.action.action == "memory_write"
    assert record.action.args == {
        "kind": "failure_lesson",
        "title": "lesson",
        "content": "body",
    }
    assert record.tool_invocation is not None
    assert record.tool_invocation.id == "call_memory"
    assert record.tool_invocation.name == "memory_write"
    assert record.tool_invocation.args == record.action.args
    assert record.tool_invocation.source == "openai_tool_call"
    assert record.tool_invocation.group_id == "provider-1"
    assert record.observation.status == "succeeded"
    assert record.observation.payload["kind"] == "failure_lesson"
    assert record.observation.payload["title"] == "lesson"


async def test_pending_tool_change_mode_updates_permission_and_resumes(
    tmp_path: Path,
) -> None:
    calls: list[AgentLoopInput] = []

    def runner(
        *, problem_statement: str, initial_observations=None
    ) -> AgentLoopResult:
        calls.append(
            AgentLoopInput(
                repo_path=tmp_path,
                problem_statement=problem_statement,
                initial_observations=initial_observations or [],
            )
        )
        return AgentLoopResult(
            run_id="agent-test",
            status="completed",
            summary="权限模式已切换。",
            trace_path=None,
            workspace_path=str(tmp_path),
            steps=[],
        )

    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=runner,
    )
    app.session_state.recent_task = "查看会话状态"
    app.session_state.set_pending_tool(
        tool_name="session_status",
        arguments={"include_tools": False, "include_recent_steps": False},
        risk_level="medium",
        reason="tool requires higher permission",
        source="agent_loop",
        required_mode="danger-full-access",
        preview={"reason": "tool requires higher permission"},
        tool_call_id="call_status",
        tool_call_group_id="provider-1",
    )

    async with app.run_test() as pilot:
        app.handle_user_input("切换模式")
        await pilot.pause()

    assert app.session_state.permission_mode == "danger-full-access"
    assert calls
    record = calls[0].initial_observations[0]
    assert record.tool_invocation is not None
    assert record.tool_invocation.name == "session_status"
    assert record.tool_invocation.group_id == "provider-1"
    assert record.observation.status == "succeeded"
    assert record.observation.payload["permission_mode"] == "danger-full-access"
    assert any("权限模式已切换为 danger-full-access" in message for message in app.message_texts)


async def test_agent_loop_shell_confirmation_resumes_with_tool_observation(
    tmp_path: Path,
) -> None:
    calls: list[AgentLoopInput] = []
    repo_path = init_git_repo(tmp_path)

    def runner(
        *, problem_statement: str, initial_observations=None
    ) -> AgentLoopResult:
        calls.append(
            AgentLoopInput(
                repo_path=repo_path,
                problem_statement=problem_statement,
                initial_observations=initial_observations or [],
            )
        )
        return AgentLoopResult(
            run_id="agent-test",
            status="completed",
            summary="命令已执行。",
            trace_path=None,
            workspace_path=str(repo_path),
            steps=[],
        )

    shell_executor = FakeShellExecutor()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        shell_executor=shell_executor,
        tool_agent_runner=runner,
    )
    app.session_state.recent_task = "运行命令"
    app.session_state.set_pending_tool(
        tool_name="run_shell_command",
        arguments={"command": "python -c 'print(123)'"},
        risk_level="medium",
        reason="command is not in the low-risk allowlist",
        source="agent_loop",
        required_mode="danger-full-access",
        preview={"command_preview": "python -c 'print(123)'"},
        tool_call_id="call_shell",
        tool_call_group_id="provider-1",
    )

    async with app.run_test() as pilot:
        app.handle_user_input("确认")
        await pilot.pause()

    assert shell_executor.calls == []
    assert calls
    record = calls[0].initial_observations[0]
    assert record.tool_invocation is not None
    assert record.tool_invocation.name == "run_shell_command"
    assert record.tool_invocation.group_id == "provider-1"
    assert record.observation.status == "succeeded"
    assert record.observation.payload["payload"]["status"] == "passed"


async def test_pending_tool_blocks_new_task_until_resolved(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=runner,
    )

    async with app.run_test():
        app.session_state.set_pending_tool(
            tool_name="memory_write",
            arguments={"kind": "failure_lesson", "title": "lesson", "content": "body"},
            risk_level="medium",
            reason="tool memory_write requires confirmation",
            source="agent_loop",
            required_mode="workspace-write",
            preview={"title": "lesson"},
        )

        app.handle_user_input("帮我查看当前目录")

    assert runner.calls == []
    assert app.session_state.pending_tool is not None
    assert "请先确认、取消或切换模式来处理待执行的工具调用" in "\n".join(
        app.message_texts
    )


async def test_json_action_pending_confirmation_recovers_arguments(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))
    result = run_agent_loop(
        AgentLoopInput(
            repo_path=repo_path,
            problem_statement="remember this",
            actions=[
                {
                    "type": "tool_call",
                    "action": "memory_write",
                    "reason": "Store a lesson",
                    "args": {
                        "kind": "failure_lesson",
                        "title": "lesson",
                        "content": "body",
                    },
                }
            ],
            permission_mode="custom",
            use_worktree=False,
        ),
        make_settings(tmp_path),
    )

    async with app.run_test():
        assert app._store_pending_tool_from_result(result) is True

    pending = app.session_state.pending_tool
    assert pending is not None
    assert pending.arguments == {
        "kind": "failure_lesson",
        "title": "lesson",
        "content": "body",
    }


async def test_pending_shell_compatibility_exposes_command_and_bounded_preview(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    command = "python -c " + "x" * 1000
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
    )

    async with app.run_test():
        app.session_state.set_pending_shell(
            command=command,
            risk_level="high",
            reason="test pending shell",
            source="test",
        )

        pending_shell = app.session_state.pending_shell
        assert pending_shell is not None
        assert pending_shell.command == command
        assert pending_shell.preview["command_chars"] == len(command)
        assert len(str(pending_shell.preview["command_preview"])) < len(command)
        assert "command" not in pending_shell.preview


async def test_pending_shell_confirmation_runs_command(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    shell_executor = FakeShellExecutor(
        ShellCommandResult(
            command="rm README.md",
            cwd=str(repo_path),
            exit_code=0,
            status="passed",
            stdout_excerpt="",
            stderr_excerpt="",
            duration_ms=1,
            risk_level="high",
            requires_confirmation=True,
        )
    )
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        shell_executor=shell_executor,
        tool_agent_runner=FakeToolAgentRunner(),
    )

    async with app.run_test():
        app.session_state.set_pending_shell(
            command="rm README.md",
            risk_level="high",
            reason="test pending shell",
            source="test",
        )
        app.handle_user_input("确认")
        await wait_until(lambda: not app.session_state.running)

        assert shell_executor.calls == [("rm README.md", repo_path, True)]
        assert app.session_state.pending_shell is None
        assert any("risk_level: high" in message for message in app.message_texts)


async def test_pending_shell_confirmation_still_runs_command(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    shell_executor = FakeShellExecutor()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        shell_executor=shell_executor,
        tool_agent_runner=FakeToolAgentRunner(),
    )

    async with app.run_test():
        app.session_state.set_pending_shell(
            command="printf hello",
            risk_level="medium",
            reason="test pending shell",
            source="test",
        )
        app.handle_user_input("确认")
        await wait_until(lambda: not app.session_state.running)

        assert app.session_state.pending_tool is None
        rendered = "\n".join(app.message_texts)
        assert "Running command: printf hello" in rendered or shell_executor.calls == [
            ("printf hello", repo_path, True)
        ]


async def test_malformed_pending_tool_result_does_not_crash(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))
    result = AgentLoopResult(
        run_id="agent-test",
        status="needs_user_confirmation",
        summary="User confirmation required",
        trace_path=None,
        workspace_path=str(repo_path),
        steps=[
            AgentStep(
                index=1,
                action=FinalResponseAction(
                    type="final_response",
                    status="needs_user_confirmation",
                    summary="User confirmation required",
                ),
                observation=Observation(
                    status="rejected",
                    summary="User confirmation required",
                    payload={"pending_confirmation": {"tool_name": "memory_write"}},
                    error_message="missing fields",
                ),
            )
        ],
    )

    async with app.run_test():
        app._complete_tool_request(result)

    assert app.session_state.pending_tool is None
    assert any("pending confirmation is invalid" in message for message in app.message_texts)


async def test_status_displays_pending_tool(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    app = MendCodeTextualApp(repo_path=repo_path, settings=make_settings(tmp_path))

    async with app.run_test():
        app.session_state.set_pending_tool(
            tool_name="memory_write",
            arguments={"title": "lesson"},
            risk_level="medium",
            reason="tool memory_write requires confirmation",
            source="test",
            required_mode="workspace-write",
            preview={"title": "lesson"},
        )

        app.handle_user_input("/status")

    assert "pending_tool: memory_write" in "\n".join(app.message_texts)


async def test_natural_fix_request_waits_for_confirmation_then_runs_with_set_test(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/test python -m pytest -q")
        app.handle_user_input("/fix fix tests")
        await pilot.pause()

        assert fake_session.calls == []
        assert app.session_state.pending_fix is not None
        assert any("python -m pytest -q" in message for message in app.message_texts)

        app.handle_user_input("start")
        await wait_until(lambda: not app.session_state.running)
        await pilot.pause()

        assert fake_session.calls == [("fix tests", ["python -m pytest -q"])]
        assert app.session_state.last_turn is not None
        assert any("Tool Summary" in message for message in app.message_texts)
        assert any("Review Summary" in message for message in app.message_texts)
        assert all("/tmp/trace.jsonl" not in message for message in app.message_texts)
        assert all("trace_path" not in message for message in app.message_texts)
        assert app.session_state.conversation_markdown_path is not None
        markdown = app.session_state.conversation_markdown_path.read_text(encoding="utf-8")
        assert "/tmp/trace.jsonl" in markdown


async def test_natural_fix_request_suggests_verification_command_before_running(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    fake_session = FakeSession(make_turn())
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/fix pytest 失败了，帮我修复")
        await pilot.pause()

        assert fake_session.calls == []
        assert app.session_state.pending_fix is not None
        assert app.session_state.pending_fix.suggested_verification_command == (
            "python -m pytest -q"
        )
        assert any("回复“开始”" in message for message in app.message_texts)

        app.handle_user_input("开始")
        await wait_until(lambda: not app.session_state.running)
        await pilot.pause()

        assert fake_session.calls == [("pytest 失败了，帮我修复", ["python -m pytest -q"])]
        assert app.session_state.pending_fix is None


async def test_pending_fix_can_be_cancelled_before_running(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    fake_session = FakeSession(make_turn())
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/fix pytest 失败了，帮我修复")
        await pilot.pause()
        app.handle_user_input("取消")
        await pilot.pause()

        assert fake_session.calls == []
        assert app.session_state.pending_fix is None
        assert any("已取消" in message for message in app.message_texts)


async def test_test_command_then_normal_text_starts_agent_tools_not_chat(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    chat_responder = FakeChatResponder("You are welcome.")
    tool_agent_runner = FakeToolAgentRunner()
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
        chat_responder=chat_responder,
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/test python -m pytest -q")
        app.handle_user_input("thanks, what changed in the last turn?")
        await wait_until(lambda: not app.session_state.running)
        await pilot.pause()

        assert fake_session.calls == []
        assert chat_responder.calls == []
        assert tool_agent_runner.calls == ["thanks, what changed in the last turn?"]
        assert any(
            "Running tools: thanks, what changed in the last turn?" in message
            for message in app.message_texts
        )


async def test_fix_command_without_test_command_prompts_for_verification_command(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
        chat_responder=FakeChatResponder(),
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/fix fix tests")
        await pilot.pause()

        assert fake_session.calls == []
        assert any("提供验证命令" in message for message in app.message_texts)


async def test_test_command_overrides_pending_fix_suggestion(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    (repo_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    fake_session = FakeSession(make_turn())
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/fix pytest 失败了，帮我修复")
        await pilot.pause()
        app.handle_user_input("/test python -m pytest tests/unit -q")
        app.handle_user_input("yes")
        await wait_until(lambda: not app.session_state.running)

        assert fake_session.calls == [
            ("pytest 失败了，帮我修复", ["python -m pytest tests/unit -q"])
        ]


async def test_running_worker_rejects_second_fix_request(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    started = threading.Event()
    release = threading.Event()
    fake_session = FakeSession(make_turn(), started=started, release=release)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/test python -m pytest -q")
        app.handle_user_input("/fix fix tests")
        app.handle_user_input("yes")
        await wait_until(started.is_set)

        app.handle_user_input("/fix another task")

        assert any("already running" in message for message in app.message_texts)
        release.set()
        await wait_until(lambda: not app.session_state.running)
        await pilot.pause()


async def test_running_agent_tool_request_rejects_second_normal_request(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    started = threading.Event()
    release = threading.Event()
    tool_agent_runner = FakeToolAgentRunner(started=started, release=release)
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        tool_agent_runner=tool_agent_runner,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("ls")
        await wait_until(started.is_set)

        app.handle_user_input("pwd")

        assert any("already running" in message for message in app.message_texts)
        assert tool_agent_runner.calls == ["ls"]
        release.set()
        await wait_until(lambda: not app.session_state.running)
        await pilot.pause()


async def test_review_action_commands_target_latest_turn(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    calls: list[str] = []

    def execute_action(action: str, turn: AgentSessionTurn) -> ReviewActionResult:
        calls.append(action)
        return ReviewActionResult(
            action=action,
            status="succeeded",
            summary=f"{action} succeeded",
            payload={"turn_index": turn.index},
        )

    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
        review_action_executor=execute_action,
    )

    async with app.run_test() as pilot:
        app.session_state.last_turn = make_turn()
        app.handle_user_input("/diff")
        app.handle_user_input("/trace")
        app.handle_user_input("/apply")
        app.handle_user_input("/discard")
        await pilot.pause()

        assert calls == ["view_diff", "view_trace", "apply", "discard"]
        assert any("view_diff succeeded" in message for message in app.message_texts)
        assert any("discard succeeded" in message for message in app.message_texts)
