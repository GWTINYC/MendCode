from dataclasses import dataclass, field
from typing import Literal

from app.agent.prompt_context import ChatMessage
from app.agent.session import AgentSessionTurn
from app.workspace.review_actions import ReviewActionResult

RunningKind = Literal["agent", "chat"]


@dataclass
class TuiSessionState:
    verification_command: str | None = None
    recent_task: str | None = None
    last_turn: AgentSessionTurn | None = None
    running: bool = False
    running_kind: RunningKind | None = None
    last_turn_status: str = "idle"
    last_review_action: ReviewActionResult | None = None
    chat_history: list[ChatMessage] = field(default_factory=list)

    @property
    def verification_commands(self) -> list[str]:
        if self.verification_command is None:
            return []
        return [self.verification_command]

    def set_verification_command(self, command: str) -> None:
        stripped = command.strip()
        if not stripped:
            raise ValueError("verification command is required")
        self.verification_command = stripped

    def mark_turn_started(self, task: str) -> None:
        self.recent_task = task
        self.running = True
        self.running_kind = "agent"
        self.last_turn_status = "running"

    def mark_turn_completed(self, turn: AgentSessionTurn) -> None:
        self.last_turn = turn
        self.running = False
        self.running_kind = None
        self.last_turn_status = turn.review.status

    def mark_turn_failed(self) -> None:
        self.running = False
        self.running_kind = None
        self.last_turn_status = "failed"

    def mark_chat_started(self) -> None:
        self.running = True
        self.running_kind = "chat"

    def mark_chat_completed(self, *, user_message: str, assistant_message: str) -> None:
        self.running = False
        self.running_kind = None
        self.chat_history.extend(
            [
                ChatMessage(role="user", content=user_message),
                ChatMessage(role="assistant", content=assistant_message),
            ]
        )

    def mark_chat_failed(self) -> None:
        self.running = False
        self.running_kind = None
