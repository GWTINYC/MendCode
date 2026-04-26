from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.agent.prompt_context import ChatMessage
from app.agent.session import AgentSessionTurn
from app.workspace.review_actions import ReviewActionResult

RunningKind = Literal["agent", "chat", "shell", "tool"]


@dataclass
class PendingFix:
    problem_statement: str
    suggested_verification_command: str
    source: str
    awaiting_confirmation: bool = True


@dataclass
class PendingShell:
    command: str
    risk_level: str
    reason: str
    source: str
    awaiting_confirmation: bool = True


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
    pending_fix: PendingFix | None = None
    pending_shell: PendingShell | None = None
    conversation_markdown_path: Path | None = None
    conversation_jsonl_path: Path | None = None

    def set_conversation_paths(self, *, markdown_path: Path, jsonl_path: Path) -> None:
        self.conversation_markdown_path = markdown_path
        self.conversation_jsonl_path = jsonl_path

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
        if self.pending_fix is not None:
            self.pending_fix.suggested_verification_command = stripped

    def set_pending_fix(
        self,
        *,
        problem_statement: str,
        suggested_verification_command: str,
        source: str,
    ) -> None:
        self.pending_fix = PendingFix(
            problem_statement=problem_statement,
            suggested_verification_command=suggested_verification_command,
            source=source,
        )

    def clear_pending_fix(self) -> None:
        self.pending_fix = None

    def set_pending_shell(
        self,
        *,
        command: str,
        risk_level: str,
        reason: str,
        source: str,
    ) -> None:
        self.pending_shell = PendingShell(
            command=command,
            risk_level=risk_level,
            reason=reason,
            source=source,
        )

    def clear_pending_shell(self) -> None:
        self.pending_shell = None

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

    def mark_shell_started(self, command: str) -> None:
        self.recent_task = command
        self.running = True
        self.running_kind = "shell"
        self.last_turn_status = "running_shell"

    def mark_shell_completed(self) -> None:
        self.running = False
        self.running_kind = None
        self.last_turn_status = "shell_completed"

    def mark_shell_failed(self) -> None:
        self.running = False
        self.running_kind = None
        self.last_turn_status = "shell_failed"

    def mark_tool_started(self, task: str) -> None:
        self.recent_task = task
        self.running = True
        self.running_kind = "tool"
        self.last_turn_status = "running_tool"

    def mark_tool_completed(self, status: str) -> None:
        self.running = False
        self.running_kind = None
        self.last_turn_status = status

    def mark_tool_failed(self) -> None:
        self.running = False
        self.running_kind = None
        self.last_turn_status = "tool_failed"
