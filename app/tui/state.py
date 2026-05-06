from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from app.agent.loop import AgentLoopResult
from app.agent.prompt_context import ChatMessage
from app.agent.session import AgentSessionTurn
from app.permissions.policy import PermissionMode
from app.runtime.tool_confirmation import PendingToolConfirmation
from app.workspace.review_actions import ReviewActionResult

RunningKind = Literal["agent", "chat", "shell", "tool"]
_MAX_COMMAND_PREVIEW_CHARS = 240


@dataclass
class PendingFix:
    problem_statement: str
    suggested_verification_command: str
    source: str
    awaiting_confirmation: bool = True


@dataclass
class TuiSessionState:
    permission_mode: PermissionMode = "guided"
    verification_command: str | None = None
    recent_task: str | None = None
    last_turn: AgentSessionTurn | None = None
    running: bool = False
    running_kind: RunningKind | None = None
    last_turn_status: str = "idle"
    last_review_action: ReviewActionResult | None = None
    last_tool_result: AgentLoopResult | None = None
    chat_history: list[ChatMessage] = field(default_factory=list)
    pending_fix: PendingFix | None = None
    pending_tool: PendingToolConfirmation | None = None
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

    def set_pending_tool(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        risk_level: str,
        reason: str,
        source: str,
        required_mode: str = "danger-full-access",
        preview: dict[str, object] | None = None,
        tool_call_id: str | None = None,
        tool_call_group_id: str | None = None,
        confirmation_id: str | None = None,
    ) -> None:
        payload = {
            "tool_call_id": tool_call_id,
            "tool_call_group_id": tool_call_group_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "reason": reason,
            "risk_level": risk_level,
            "required_mode": required_mode,
            "preview": preview or {},
            "source": source,
        }
        if confirmation_id is not None:
            payload["id"] = confirmation_id
        self.pending_tool = PendingToolConfirmation.model_validate(payload)

    def clear_pending_tool(self) -> None:
        self.pending_tool = None

    def set_pending_shell(
        self,
        *,
        command: str,
        risk_level: str,
        reason: str,
        source: str,
    ) -> None:
        self.set_pending_tool(
            tool_name="run_shell_command",
            arguments={"command": command},
            risk_level=risk_level,
            reason=reason,
            source=source,
            required_mode="danger-full-access",
            preview={
                "command_preview": _bounded_command_preview(command),
                "command_chars": len(command),
                "reason": reason,
            },
        )

    def clear_pending_shell(self) -> None:
        self.clear_pending_tool()

    @property
    def pending_shell(self) -> PendingToolConfirmation | None:
        if self.pending_tool is None or self.pending_tool.tool_name != "run_shell_command":
            return None
        return self.pending_tool

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

    def set_last_tool_result(self, result: AgentLoopResult) -> None:
        self.last_tool_result = result

    def mark_tool_failed(self) -> None:
        self.running = False
        self.running_kind = None
        self.last_turn_status = "tool_failed"


def _bounded_command_preview(command: str) -> str:
    if len(command) <= _MAX_COMMAND_PREVIEW_CHARS:
        return command
    return f"{command[:_MAX_COMMAND_PREVIEW_CHARS]}..."
