from pathlib import Path

from app.tui.commands import ChatCommand
from app.tui.controller import TuiController
from app.tui.intent import IntentDecision
from app.tui.state import TuiSessionState


class FakeConversationLog:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def append_event(self, event_type: str, payload: dict[str, object]) -> None:
        self.events.append((event_type, payload))


class FakeIntentRouter:
    def __init__(self, decision: IntentDecision) -> None:
        self.decision = decision
        self.calls: list[str] = []

    def route(self, message: str, context) -> IntentDecision:
        self.calls.append(message)
        return self.decision


class FakeHost:
    def __init__(self, decision: IntentDecision | None = None) -> None:
        self.repo_path = Path("/repo")
        self.session_state = TuiSessionState()
        self.conversation_log = FakeConversationLog()
        self.router = FakeIntentRouter(
            decision
            or IntentDecision(kind="chat", source="rule", command=None)
        )
        self.messages: list[tuple[str, str]] = []
        self.commands: list[ChatCommand] = []
        self.started_chat: list[str] = []
        self.prepared_shell: list[tuple[str, str]] = []
        self.started_tool: list[str] = []
        self.prepared_fix: list[tuple[str, str]] = []
        self.pending_shell_replies: list[str] = []
        self.pending_fix_replies: list[str] = []

    def append_message(self, role: str, message: str) -> None:
        self.messages.append((role, message))

    def ensure_intent_router(self):
        return self.router

    def handle_pending_shell_reply(self, message: str) -> bool:
        self.pending_shell_replies.append(message)
        return False

    def handle_pending_fix_reply(self, message: str) -> bool:
        self.pending_fix_replies.append(message)
        return False

    def start_chat(self, message: str) -> None:
        self.started_chat.append(message)

    def prepare_shell_command(self, command: str, *, source: str) -> None:
        self.prepared_shell.append((command, source))

    def start_tool_request(self, task: str) -> None:
        self.started_tool.append(task)

    def prepare_fix(self, task: str, *, source: str) -> None:
        self.prepared_fix.append((task, source))

    def handle_command(self, command: ChatCommand) -> None:
        self.commands.append(command)


def test_controller_routes_plain_chat_to_chat_start() -> None:
    host = FakeHost(IntentDecision(kind="chat", source="rule", command=None))

    TuiController(host).handle_user_input("what can you do?")

    assert host.started_chat == ["what can you do?"]
    assert host.router.calls == ["what can you do?"]
    assert host.conversation_log.events[0][0] == "intent"
    assert host.conversation_log.events[0][1]["kind"] == "chat"


def test_controller_routes_shell_decision_to_shell_preparation() -> None:
    host = FakeHost(IntentDecision(kind="shell", source="rule", command="ls"))

    TuiController(host).handle_user_input("ls")

    assert host.prepared_shell == [("ls", "rule")]
    assert host.started_chat == []


def test_controller_dispatches_slash_commands_without_intent_router() -> None:
    host = FakeHost()

    TuiController(host).handle_user_input("/status")

    assert host.commands[0].name == "status"
    assert host.router.calls == []
