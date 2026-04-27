from pathlib import Path
from typing import Protocol

from app.tui.commands import ChatCommand, CommandParseError, parse_chat_input
from app.tui.state import TuiSessionState


class ConversationLogLike(Protocol):
    def append_event(self, event_type: str, payload: dict[str, object]) -> None: ...


class TuiControllerHost(Protocol):
    repo_path: Path
    session_state: TuiSessionState
    conversation_log: ConversationLogLike

    def append_message(self, role: str, message: str) -> None: ...
    def handle_pending_shell_reply(self, message: str) -> bool: ...
    def handle_pending_fix_reply(self, message: str) -> bool: ...
    def start_agent_request(self, task: str) -> None: ...
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
