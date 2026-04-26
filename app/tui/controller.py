from pathlib import Path
from typing import Protocol

from app.agent.provider_factory import ProviderConfigurationError
from app.tui.commands import ChatCommand, CommandParseError, parse_chat_input
from app.tui.intent import IntentContext, IntentRouter
from app.tui.state import TuiSessionState


class ConversationLogLike(Protocol):
    def append_event(self, event_type: str, payload: dict[str, object]) -> None: ...


class TuiControllerHost(Protocol):
    repo_path: Path
    session_state: TuiSessionState
    conversation_log: ConversationLogLike

    def append_message(self, role: str, message: str) -> None: ...
    def ensure_intent_router(self) -> IntentRouter: ...
    def handle_pending_shell_reply(self, message: str) -> bool: ...
    def handle_pending_fix_reply(self, message: str) -> bool: ...
    def start_chat(self, message: str) -> None: ...
    def prepare_shell_command(self, command: str, *, source: str) -> None: ...
    def start_tool_request(self, task: str) -> None: ...
    def prepare_fix(self, task: str, *, source: str) -> None: ...
    def handle_command(self, command: ChatCommand) -> None: ...


class TuiController:
    def __init__(self, host: TuiControllerHost) -> None:
        self._host = host

    def handle_user_input(self, raw_text: str) -> None:
        text = raw_text.strip()
        if not text:
            return
        self._host.append_message("You", text)
        try:
            parsed = parse_chat_input(text)
        except CommandParseError as exc:
            self._host.append_message("Error", str(exc))
            return

        if parsed.kind == "empty":
            return
        if parsed.kind == "task":
            assert parsed.task_text is not None
            self.handle_task(parsed.task_text)
            return

        assert parsed.command is not None
        self._host.handle_command(parsed.command)

    def handle_task(self, task: str) -> None:
        self._host.session_state.recent_task = task
        if self._host.session_state.running:
            self._host.append_message("Error", "A request is already running.")
            return
        if self._host.handle_pending_shell_reply(task):
            return
        if self._host.handle_pending_fix_reply(task):
            return

        try:
            router = self._host.ensure_intent_router()
            decision = router.route(
                task,
                IntentContext(
                    repo_path=self._host.repo_path,
                    verification_command=self._host.session_state.verification_command,
                ),
            )
            self._host.conversation_log.append_event(
                "intent",
                {
                    "kind": decision.kind,
                    "source": decision.source,
                    "command": decision.command,
                    "message": task,
                },
            )
        except ProviderConfigurationError as exc:
            self._host.append_message("Error", str(exc))
            return

        if decision.kind == "chat":
            self._host.start_chat(task)
            return
        if decision.kind == "shell":
            if not decision.command:
                self._host.start_chat(task)
                return
            self._host.prepare_shell_command(decision.command, source=decision.source)
            return
        if decision.kind == "tool":
            self._host.start_tool_request(task)
            return
        self._host.prepare_fix(task, source=decision.source)
