import asyncio
import subprocess
import threading
from pathlib import Path

import pytest

from app.agent.loop import AgentLoopResult
from app.agent.session import AgentSessionTurn, ReviewSummary, ToolCallSummary
from app.config.settings import Settings
from app.tui.app import MendCodeTextualApp
from app.tui.chat import ChatResponse
from app.workspace.review_actions import ReviewActionResult

pytestmark = pytest.mark.asyncio


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


async def test_plain_message_without_test_command_runs_general_chat(
    tmp_path: Path,
) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    chat_responder = FakeChatResponder("I can discuss the repo before tools run.")
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
        chat_responder=chat_responder,
    )

    async with app.run_test():
        app.handle_user_input("what can you do?")
        await wait_until(lambda: not app.session_state.running)

        assert app.session_state.recent_task == "what can you do?"
        assert fake_session.calls == []
        assert chat_responder.calls == ["what can you do?"]
        assert any(
            "I can discuss the repo before tools run." in message
            for message in app.message_texts
        )


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
        app.handle_user_input("fix tests")
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
        app.handle_user_input("pytest 失败了，帮我修复")
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
        app.handle_user_input("pytest 失败了，帮我修复")
        await pilot.pause()
        app.handle_user_input("取消")
        await pilot.pause()

        assert fake_session.calls == []
        assert app.session_state.pending_fix is None
        assert any("已取消" in message for message in app.message_texts)


async def test_test_command_then_general_chat_does_not_start_agent_turn(tmp_path: Path) -> None:
    repo_path = init_git_repo(tmp_path)
    fake_session = FakeSession(make_turn())
    chat_responder = FakeChatResponder("You are welcome.")
    app = MendCodeTextualApp(
        repo_path=repo_path,
        settings=make_settings(tmp_path),
        agent_session=fake_session,
        chat_responder=chat_responder,
    )

    async with app.run_test() as pilot:
        app.handle_user_input("/test python -m pytest -q")
        app.handle_user_input("thanks, what changed in the last turn?")
        await wait_until(lambda: not app.session_state.running)
        await pilot.pause()

        assert fake_session.calls == []
        assert chat_responder.calls == ["thanks, what changed in the last turn?"]
        assert any("You are welcome." in message for message in app.message_texts)


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
        app.handle_user_input("pytest 失败了，帮我修复")
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
        app.handle_user_input("fix tests")
        app.handle_user_input("yes")
        await wait_until(started.is_set)

        app.handle_user_input("/fix another task")

        assert any("already running" in message for message in app.message_texts)
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
