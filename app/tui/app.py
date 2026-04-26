import subprocess
from pathlib import Path
from typing import Callable, Protocol

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Input, RichLog, Static

from app.agent.loop import AgentLoopInput, AgentLoopResult, run_agent_loop
from app.agent.prompt_context import ChatMessage
from app.agent.provider_factory import ProviderConfigurationError, build_agent_provider
from app.agent.session import AgentSession, AgentSessionTurn
from app.config.settings import Settings
from app.runtime.session_store import SessionNotFoundError, SessionStore
from app.tui.chat import ChatContext, ChatResponder, ChatResponse, build_chat_responder
from app.tui.commands import ChatCommand
from app.tui.controller import TuiController
from app.tui.conversation_log import ConversationLog
from app.tui.intent import IntentRouter, build_intent_router
from app.tui.log_summarizer import compact_agent_loop_result, compact_agent_session_turn
from app.tui.state import TuiSessionState
from app.workspace.project_detection import detect_project
from app.workspace.review_actions import (
    ReviewActionResult,
    apply_worktree_changes,
    discard_worktree,
    view_trace,
    view_worktree_diff,
)
from app.workspace.shell_executor import ShellCommandResult, execute_shell_command
from app.workspace.shell_policy import ShellPolicy

READ_ONLY_TOOL_AGENT_TOOLS = {
    "glob_file_search",
    "git",
    "list_dir",
    "read_file",
    "rg",
    "search_code",
}

ReviewActionExecutor = Callable[[str, AgentSessionTurn], ReviewActionResult]
ToolAgentRunner = Callable[..., AgentLoopResult]

_CONFIRM_TERMS = {"start", "yes", "y", "confirm", "开始", "确认", "可以", "执行", "好", "好的"}
_CANCEL_TERMS = {"cancel", "no", "n", "stop", "取消", "不用", "停止", "算了"}


class AgentSessionLike(Protocol):
    def run_turn(
        self,
        *,
        problem_statement: str,
        verification_commands: list[str],
        step_budget: int = 12,
    ) -> AgentSessionTurn:
        ...


class ShellExecutor(Protocol):
    def __call__(
        self,
        *,
        command: str,
        cwd: Path,
        policy: ShellPolicy,
        confirmed: bool = False,
    ) -> ShellCommandResult:
        ...


def _git_value(repo_path: Path, args: list[str], fallback: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return fallback
    if completed.returncode != 0:
        return fallback
    return completed.stdout.strip() or fallback


def _repo_dirty_status(repo_path: Path) -> str:
    status_lines = _git_value(repo_path, ["status", "--short"], "").splitlines()
    return f"dirty, {len(status_lines)} modified" if status_lines else "clean"


def _build_header_text(repo_path: Path, settings: Settings) -> str:
    branch = _git_value(repo_path, ["branch", "--show-current"], "unknown")
    provider = settings.provider_model or settings.provider
    return "\n".join(
        [
            "MendCode",
            f"repo: {repo_path}",
            f"branch: {branch}",
            f"status: {_repo_dirty_status(repo_path)}",
            "mode: guided",
            f"provider: {provider}",
        ]
    )


def _available_review_actions(turn: AgentSessionTurn) -> list[str]:
    actions = set(turn.review.recommended_actions)
    if turn.review.workspace_path is None:
        actions.difference_update({"view_diff", "apply", "discard"})
    if turn.review.trace_path is None:
        actions.discard("view_trace")
    ordered = ["view_diff", "view_trace", "apply", "discard"]
    return [action for action in ordered if action in actions]


def _review_action_unavailable(action: str, message: str) -> ReviewActionResult:
    return ReviewActionResult(
        action=action,
        status="failed",
        summary=f"Unable to {action.replace('_', ' ')}",
        error_message=message,
    )


def execute_review_action(
    *,
    action: str,
    repo_path: Path,
    turn: AgentSessionTurn,
) -> ReviewActionResult:
    workspace_path = Path(turn.review.workspace_path) if turn.review.workspace_path else None
    trace_path = Path(turn.review.trace_path) if turn.review.trace_path else None

    if action == "view_diff":
        if workspace_path is None:
            return _review_action_unavailable("view_diff", "workspace path is unavailable")
        return view_worktree_diff(workspace_path=workspace_path)
    if action == "view_trace":
        if trace_path is None:
            return _review_action_unavailable("view_trace", "trace path is unavailable")
        return view_trace(trace_path=trace_path)
    if action == "apply":
        if workspace_path is None:
            return _review_action_unavailable("apply", "workspace path is unavailable")
        return apply_worktree_changes(repo_path=repo_path, workspace_path=workspace_path)
    if action == "discard":
        if workspace_path is None:
            return _review_action_unavailable("discard", "workspace path is unavailable")
        return discard_worktree(repo_path=repo_path, workspace_path=workspace_path)
    return ReviewActionResult(
        action=action,
        status="rejected",
        summary="Action not available",
        error_message=f"Action not available: {action}",
    )


class MendCodeTextualApp(App[None]):
    TITLE = "MendCode"
    CSS = """
    Screen {
        layout: vertical;
    }

    #repo-header {
        height: auto;
        padding: 0 1;
        border-bottom: solid $primary;
    }

    #chat-log {
        height: 1fr;
        padding: 0 1;
        border-bottom: solid $primary;
    }

    #chat-input {
        dock: bottom;
    }
    """

    def __init__(
        self,
        *,
        repo_path: Path,
        settings: Settings,
        agent_session: AgentSessionLike | None = None,
        chat_responder: ChatResponder | None = None,
        intent_router: IntentRouter | None = None,
        review_action_executor: ReviewActionExecutor | None = None,
        shell_executor: ShellExecutor | None = None,
        tool_agent_runner: ToolAgentRunner | None = None,
    ) -> None:
        super().__init__()
        self.repo_path = repo_path
        self.settings = settings
        self.session_state = TuiSessionState()
        self.header_text = _build_header_text(repo_path, settings)
        self.message_texts: list[str] = []
        self._agent_session = agent_session
        self._chat_responder = chat_responder
        self._intent_router = intent_router
        self._review_action_executor = review_action_executor
        self._shell_executor = shell_executor
        self._tool_agent_runner = tool_agent_runner
        self._conversation_log = ConversationLog.create(
            data_dir=settings.data_dir,
            repo_path=repo_path,
        )
        self._controller = TuiController(self)
        self.session_state.set_conversation_paths(
            markdown_path=self._conversation_log.markdown_path,
            jsonl_path=self._conversation_log.jsonl_path,
        )

    def compose(self) -> ComposeResult:
        yield Static(self.header_text, id="repo-header")
        yield RichLog(id="chat-log", wrap=True, highlight=False)
        yield Input(placeholder="Message or /help", id="chat-input")

    def on_mount(self) -> None:
        self.append_message(
            "System",
            "Tell me what is broken, or ask for a safe shell inspection like ls or git status. "
            "Type /help for precise commands.",
        )
        self.query_one("#chat-input", Input).focus()

    @on(Input.Submitted, "#chat-input")
    def on_chat_submitted(self, event: Input.Submitted) -> None:
        value = event.value
        event.input.value = ""
        self.handle_user_input(value)

    def append_message(self, role: str, message: str) -> None:
        line = f"{role}: {message}"
        self.message_texts.append(line)
        self._conversation_log.append_message(role, message)
        try:
            chat_log = self.query_one("#chat-log", RichLog)
        except NoMatches:
            return
        chat_log.write(Text(line))

    def handle_user_input(self, raw_text: str) -> None:
        self._controller.handle_user_input(raw_text)

    @property
    def conversation_log(self) -> ConversationLog:
        return self._conversation_log

    def ensure_intent_router(self) -> IntentRouter:
        return self._ensure_intent_router()

    def handle_pending_shell_reply(self, message: str) -> bool:
        return self._handle_pending_shell_reply(message)

    def handle_pending_fix_reply(self, message: str) -> bool:
        return self._handle_pending_fix_reply(message)

    def start_chat(self, message: str) -> None:
        self._start_chat(message)

    def prepare_shell_command(self, command: str, *, source: str) -> None:
        self._prepare_shell_command(command, source=source)

    def start_tool_request(self, task: str) -> None:
        self._start_tool_request(task)

    def prepare_fix(self, task: str, *, source: str) -> None:
        self._prepare_fix(task, source=source)

    def handle_command(self, command: ChatCommand) -> None:
        self._handle_command(command)

    def _handle_command(self, command: ChatCommand) -> None:
        if command.name == "help":
            self.append_message("System", self._help_text())
            return
        if command.name == "status":
            self.append_message("System", self._status_text())
            return
        if command.name == "test":
            self._set_verification_command(command.args)
            return
        if command.name == "fix":
            self._fix_task(command.args)
            return
        if command.name in {"diff", "trace", "apply", "discard"}:
            self._run_review_action(command.name)
            return
        if command.name == "sessions":
            self._show_sessions()
            return
        if command.name == "resume":
            self._show_resume_context(command.args)
            return
        if command.name == "exit":
            self.exit()

    def _help_text(self) -> str:
        return "\n".join(
            [
                "Commands:",
                "/help - show commands",
                "/status - show repo and turn status",
                "/test <command> - set or override verification command",
                "/fix [problem] - prepare a fix with the argument or recent task",
                "Natural shell - ls, pwd, git status, git diff, rg, cat/head/tail, find",
                "/diff - show latest worktree diff",
                "/trace - show latest trace excerpt",
                "/sessions - list saved conversation sessions",
                "/resume [session_id] - show compact context from a saved session",
                "/apply - apply latest verified worktree changes",
                "/discard - discard latest worktree",
                "/exit - exit",
            ]
        )

    def _status_text(self) -> str:
        command = self.session_state.verification_command or "not set"
        recent_task = self.session_state.recent_task or "none"
        last_turn = (
            f"turn {self.session_state.last_turn.index}: {self.session_state.last_turn_status}"
            if self.session_state.last_turn is not None
            else self.session_state.last_turn_status
        )
        pending_shell = (
            self.session_state.pending_shell.command
            if self.session_state.pending_shell
            else "none"
        )
        conversation_log = self.session_state.conversation_markdown_path or "not set"
        return "\n".join(
            [
                f"repo: {self.repo_path}",
                f"branch: {_git_value(self.repo_path, ['branch', '--show-current'], 'unknown')}",
                f"status: {_repo_dirty_status(self.repo_path)}",
                f"verification_command: {command}",
                f"recent_task: {recent_task}",
                f"running: {self.session_state.running}",
                f"running_kind: {self.session_state.running_kind or 'none'}",
                f"pending_fix: {self.session_state.pending_fix is not None}",
                f"pending_shell: {pending_shell}",
                f"last_turn: {last_turn}",
                f"conversation_log: {conversation_log}",
            ]
        )

    def _session_store(self) -> SessionStore:
        return SessionStore(data_dir=self.settings.data_dir)

    def _show_sessions(self) -> None:
        sessions = self._session_store().list_sessions()
        if not sessions:
            self.append_message("System", "Session List\nNo saved sessions.")
            return
        lines = ["Session List"]
        for session in sessions[:10]:
            lines.append(
                " | ".join(
                    [
                        session.session_id,
                        session.updated_at or "",
                        session.repo_path or "",
                        f"events={session.event_count}",
                    ]
                )
            )
        self.append_message("System", "\n".join(lines))

    def _show_resume_context(self, session_id: str) -> None:
        target_session = session_id.strip() or None
        try:
            context = self._session_store().build_resume_context(target_session)
        except SessionNotFoundError as exc:
            self.append_message("Error", str(exc))
            return
        self._conversation_log.append_event(
            "session_resume",
            {"session_id": target_session or "latest"},
        )
        self.session_state.chat_history.append(
            ChatMessage(role="system", content="Resume Context\n" + context)
        )
        self.append_message("System", "Resume Context\n" + context)

    def _set_verification_command(self, command: str) -> None:
        try:
            self.session_state.set_verification_command(command)
        except ValueError as exc:
            self.append_message("Error", str(exc))
            return
        self.append_message("System", f"Verification command set: {command.strip()}")
        if self.session_state.pending_fix is not None:
            self.append_message(
                "System",
                f"已更新待确认修复的验证命令：{command.strip()}。回复“开始”后执行。",
            )

    def _fix_task(self, command_args: str) -> None:
        if self.session_state.running:
            self.append_message("Error", "A request is already running.")
            return
        task = command_args.strip() or self.session_state.recent_task
        if not task:
            self.append_message(
                "Error",
                "No task available. Describe a task or pass /fix <problem>.",
            )
            return
        self._prepare_fix(task, source="/fix")

    def _ensure_agent_session(self) -> AgentSessionLike:
        if self._agent_session is None:
            provider = build_agent_provider(self.settings)
            self._agent_session = AgentSession(
                repo_path=self.repo_path,
                provider=provider,
                settings=self.settings,
            )
        return self._agent_session

    def _ensure_chat_responder(self) -> ChatResponder:
        if self._chat_responder is None:
            self._chat_responder = build_chat_responder(self.settings)
        return self._chat_responder

    def _ensure_intent_router(self) -> IntentRouter:
        if self._intent_router is None:
            self._intent_router = build_intent_router(self.settings)
        return self._intent_router

    def _prepare_fix(self, task: str, *, source: str) -> None:
        command = self.session_state.verification_command
        if command is None:
            command = detect_project(self.repo_path).suggested_test
        if command is None:
            self.append_message(
                "System",
                "我无法自动推测验证命令。请提供验证命令，例如 /test <command>。",
            )
            return

        self.session_state.set_pending_fix(
            problem_statement=task,
            suggested_verification_command=command,
            source=source,
        )
        self.append_message(
            "System",
            f"我建议用 `{command}` 验证。回复“开始”或 yes 后，我会在隔离 worktree 中修复。",
        )

    def _handle_pending_fix_reply(self, message: str) -> bool:
        pending = self.session_state.pending_fix
        if pending is None:
            return False
        normalized = message.strip().lower()
        if normalized in _CANCEL_TERMS:
            self.session_state.clear_pending_fix()
            self.append_message("System", "已取消待确认的修复。")
            return True
        if normalized in _CONFIRM_TERMS:
            self.session_state.clear_pending_fix()
            self.session_state.set_verification_command(pending.suggested_verification_command)
            self._start_turn(
                pending.problem_statement,
                verification_command=pending.suggested_verification_command,
            )
            return True
        return False

    def _handle_pending_shell_reply(self, message: str) -> bool:
        pending = self.session_state.pending_shell
        if pending is None:
            return False
        normalized = message.strip().lower()
        if normalized in _CANCEL_TERMS:
            self.session_state.clear_pending_shell()
            self.append_message("System", "已取消待确认的 shell 命令。")
            return True
        if normalized in _CONFIRM_TERMS:
            command = pending.command
            self.session_state.clear_pending_shell()
            self._start_shell_command(command, confirmed=True)
            return True
        return False

    def _shell_policy(self) -> ShellPolicy:
        return ShellPolicy(
            allowed_root=self.repo_path,
            timeout_seconds=self.settings.verification_timeout_seconds,
        )

    def _prepare_shell_command(self, command: str, *, source: str) -> None:
        policy = self._shell_policy()
        decision = policy.evaluate(command, self.repo_path)
        if decision.requires_confirmation:
            self.session_state.set_pending_shell(
                command=command,
                risk_level=decision.risk_level,
                reason=decision.reason or "command requires confirmation",
                source=source,
            )
            self.append_message(
                "System",
                "\n".join(
                    [
                        "Shell 命令需要确认后执行。",
                        f"command: {command}",
                        f"risk_level: {decision.risk_level}",
                        f"reason: {decision.reason or 'command requires confirmation'}",
                        "回复“确认”或 yes 执行，回复“取消”放弃。",
                    ]
                ),
            )
            return
        if not decision.allowed:
            self.append_message(
                "Error",
                f"Shell command rejected: {decision.reason or 'command rejected by policy'}",
            )
            return
        self._start_shell_command(command, confirmed=False)

    def _start_turn(self, task: str, verification_command: str | None = None) -> None:
        if self.session_state.running:
            self.append_message("Error", "A request is already running.")
            return
        command = verification_command or self.session_state.verification_command
        if command is None:
            self.append_message(
                "System",
                "请先设置验证命令，例如 /test <command>。",
            )
            return

        try:
            self._ensure_agent_session()
        except ProviderConfigurationError as exc:
            self.append_message("Error", str(exc))
            return

        self.session_state.mark_turn_started(task)
        self.append_message("Agent", f"Running fix: {task}")
        self._run_turn_worker(task, command)

    def _start_shell_command(self, command: str, *, confirmed: bool) -> None:
        if self.session_state.running:
            self.append_message("Error", "A request is already running.")
            return
        self.session_state.mark_shell_started(command)
        self.append_message("Shell", f"Running command: {command}")
        self._run_shell_worker(command, confirmed)

    def _start_chat(self, message: str) -> None:
        if self.session_state.running:
            self.append_message("Error", "A request is already running.")
            return
        try:
            self._ensure_chat_responder()
        except ProviderConfigurationError as exc:
            self.append_message("Error", str(exc))
            return
        self.session_state.mark_chat_started()
        self._run_chat_worker(message)

    def _start_tool_request(self, task: str) -> None:
        if self.session_state.running:
            self.append_message("Error", "A request is already running.")
            return
        self.session_state.mark_tool_started(task)
        self.append_message("Agent", f"Running tools: {task}")
        self._run_tool_worker(task)

    @work(thread=True, exclusive=True, exit_on_error=False)
    def _run_turn_worker(self, task: str, verification_command: str) -> None:
        try:
            session = self._ensure_agent_session()
            turn = session.run_turn(
                problem_statement=task,
                verification_commands=[verification_command],
            )
        except Exception as exc:  # pragma: no cover - exercised through UI behavior
            self.call_from_thread(self._complete_turn_error, exc)
            return
        self.call_from_thread(self._complete_turn, turn)

    @work(thread=True, exclusive=True, exit_on_error=False)
    def _run_shell_worker(self, command: str, confirmed: bool) -> None:
        try:
            executor = self._shell_executor or execute_shell_command
            result = executor(
                command=command,
                cwd=self.repo_path,
                policy=self._shell_policy(),
                confirmed=confirmed,
            )
        except Exception as exc:  # pragma: no cover - exercised through UI behavior
            self.call_from_thread(self._complete_shell_error, exc)
            return
        self.call_from_thread(self._complete_shell, result)

    @work(thread=True, exclusive=True, exit_on_error=False)
    def _run_tool_worker(self, task: str) -> None:
        try:
            runner = self._tool_agent_runner or self._run_tool_agent_loop
            result = runner(problem_statement=task)
        except Exception as exc:  # pragma: no cover - exercised through UI behavior
            self.call_from_thread(self._complete_tool_error, exc)
            return
        self.call_from_thread(self._complete_tool_request, result)

    def _run_tool_agent_loop(self, *, problem_statement: str) -> AgentLoopResult:
        return run_agent_loop(
            AgentLoopInput(
                repo_path=self.repo_path,
                problem_statement=problem_statement,
                provider=build_agent_provider(self.settings),
                verification_commands=[],
                allowed_tools=READ_ONLY_TOOL_AGENT_TOOLS,
                permission_mode="guided",
                step_budget=8,
                use_worktree=False,
            ),
            self.settings,
        )

    def _complete_shell_error(self, exc: Exception) -> None:
        self.session_state.mark_shell_failed()
        self._conversation_log.append_event("shell_error", {"error": str(exc)})
        self.append_message("Error", str(exc))

    def _complete_shell(self, result: ShellCommandResult) -> None:
        if result.status == "passed":
            self.session_state.mark_shell_completed()
        else:
            self.session_state.mark_shell_failed()
        self._conversation_log.append_event(
            "shell_result",
            result.model_dump(mode="json"),
        )
        self._render_shell_result(result)

    def _complete_tool_error(self, exc: Exception) -> None:
        self.session_state.mark_tool_failed()
        self._conversation_log.append_event("tool_error", {"error": str(exc)})
        self.append_message("Error", str(exc))

    def _complete_tool_request(self, result: AgentLoopResult) -> None:
        self.session_state.mark_tool_completed(result.status)
        self._conversation_log.append_event(
            "tool_result",
            compact_agent_loop_result(result),
        )
        self._render_tool_result(result)

    def _complete_turn_error(self, exc: Exception) -> None:
        self.session_state.mark_turn_failed()
        self._conversation_log.append_event("turn_error", {"error": str(exc)})
        self.append_message("Error", str(exc))

    def _complete_turn(self, turn: AgentSessionTurn) -> None:
        self.session_state.mark_turn_completed(turn)
        self._conversation_log.append_event(
            "turn_result",
            compact_agent_session_turn(turn),
        )
        self._render_turn(turn)

    @work(thread=True, exclusive=True, exit_on_error=False)
    def _run_chat_worker(self, message: str) -> None:
        try:
            responder = self._ensure_chat_responder()
            response = responder.respond(
                message,
                ChatContext(
                    repo_path=self.repo_path,
                    verification_command=self.session_state.verification_command,
                    history=list(self.session_state.chat_history),
                    last_turn_status=self.session_state.last_turn_status,
                ),
            )
        except Exception as exc:  # pragma: no cover - exercised through UI behavior
            self.call_from_thread(self._complete_chat_error, exc)
            return
        self.call_from_thread(self._complete_chat, message, response)

    def _complete_chat_error(self, exc: Exception) -> None:
        self.session_state.mark_chat_failed()
        self._conversation_log.append_event("chat_error", {"error": str(exc)})
        self.append_message("Error", str(exc))

    def _complete_chat(self, message: str, response: ChatResponse) -> None:
        self.session_state.mark_chat_completed(
            user_message=message,
            assistant_message=response.content,
        )
        self._conversation_log.append_event(
            "chat_result",
            {
                "message": message,
                "response": response.content,
            },
        )
        self.append_message("MendCode", response.content)

    def _render_shell_result(self, result: ShellCommandResult) -> None:
        lines = [
            f"command: {result.command}",
            f"cwd: {result.cwd}",
            f"status: {result.status}",
            f"exit_code: {result.exit_code}",
            f"risk_level: {result.risk_level}",
            f"requires_confirmation: {result.requires_confirmation}",
            f"duration_ms: {result.duration_ms}",
        ]
        if result.stdout_excerpt:
            lines.extend(["stdout:", result.stdout_excerpt])
        if result.stderr_excerpt:
            lines.extend(["stderr:", result.stderr_excerpt])
        self.append_message("Shell", "Shell Result\n" + "\n".join(lines))

    def _render_tool_result(self, result: AgentLoopResult) -> None:
        lines = [
            f"status: {result.status}",
            f"summary: {result.summary}",
            f"trace_path: {result.trace_path or ''}",
        ]
        for step in result.steps:
            if step.action.type != "tool_call":
                continue
            action_name = getattr(step.action, "action", "tool_call")
            lines.append(
                f"{step.index}. {action_name}: "
                f"{step.observation.status} - {step.observation.summary}"
            )
            entries = step.observation.payload.get("entries")
            if isinstance(entries, list):
                for entry in entries[:20]:
                    if not isinstance(entry, dict):
                        continue
                    relative_path = entry.get("relative_path")
                    entry_type = entry.get("type")
                    if relative_path is not None:
                        lines.append(f"  - {relative_path} ({entry_type or 'unknown'})")
            content = step.observation.payload.get("content")
            if isinstance(content, str) and content:
                lines.append(content)
            stdout = step.observation.payload.get("stdout_excerpt")
            if isinstance(stdout, str) and stdout:
                lines.extend(["stdout:", stdout])
        self.append_message("Agent", "Tool Result\n" + "\n".join(lines))

    def _render_turn(self, turn: AgentSessionTurn) -> None:
        if turn.tool_summaries:
            tool_lines = [
                f"{item.index}. {item.action}: {item.status} - {item.summary}"
                for item in turn.tool_summaries
            ]
        else:
            tool_lines = ["No tool calls recorded."]
        self.append_message("Agent", "Tool Summary\n" + "\n".join(tool_lines))

        review_lines = [
            f"status: {turn.review.status}",
            f"summary: {turn.result.summary}",
            f"verification_status: {turn.review.verification_status}",
            f"workspace_path: {turn.review.workspace_path or ''}",
            f"trace_path: {turn.review.trace_path or ''}",
            f"changed_files: {', '.join(turn.review.changed_files)}",
        ]
        self.append_message("Agent", "Review Summary\n" + "\n".join(review_lines))

        actions = _available_review_actions(turn)
        if actions:
            command_names = {
                "view_diff": "/diff",
                "view_trace": "/trace",
                "apply": "/apply",
                "discard": "/discard",
            }
            self.append_message(
                "System",
                "Available actions: "
                + ", ".join(command_names[action] for action in actions),
            )

    def _run_review_action(self, command_name: str) -> None:
        if self.session_state.running:
            self.append_message("Error", "A request is already running.")
            return
        turn = self.session_state.last_turn
        if turn is None:
            self.append_message("Error", "No turn available for review action.")
            return

        action_name = {
            "diff": "view_diff",
            "trace": "view_trace",
            "apply": "apply",
            "discard": "discard",
        }[command_name]
        if action_name not in _available_review_actions(turn):
            self.append_message("Error", f"Action not available: /{command_name}")
            return

        executor = self._review_action_executor or (
            lambda action, latest_turn: execute_review_action(
                action=action,
                repo_path=self.repo_path,
                turn=latest_turn,
            )
        )
        result = executor(action_name, turn)
        self.session_state.last_review_action = result
        self._render_review_action_result(result)

    def _render_review_action_result(self, result: ReviewActionResult) -> None:
        lines = [
            f"action: {result.action}",
            f"status: {result.status}",
            f"summary: {result.summary}",
        ]
        if result.error_message is not None:
            lines.append(f"error: {result.error_message}")
        changed_files = result.payload.get("changed_files")
        if isinstance(changed_files, list):
            lines.append("changed_files: " + ", ".join(str(item) for item in changed_files))
        diff_stat = result.payload.get("diff_stat")
        if isinstance(diff_stat, str) and diff_stat:
            lines.append(diff_stat)
        if result.action == "view_diff":
            diff = result.payload.get("diff")
            if isinstance(diff, str) and diff:
                lines.append(diff)
        if result.action == "view_trace":
            content = result.payload.get("content")
            if isinstance(content, str) and content:
                lines.append(content)
        self.append_message("Agent", "Review Action Result\n" + "\n".join(lines))
