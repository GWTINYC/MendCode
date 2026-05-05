from app.permissions.policy import PermissionDecision
from app.runtime.tool_confirmation import (
    PendingToolConfirmation,
    build_pending_tool_confirmation,
    build_tool_rejected_observation,
    is_confirmation_match,
)
from app.schemas.agent_action import ToolCallAction
from app.tools.structured import ToolInvocation


def test_build_pending_tool_confirmation_for_shell_command() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="run_shell_command",
        reason="Need to inspect generated files",
        args={"command": "find . -maxdepth 2 -type f"},
    )
    invocation = ToolInvocation(
        id="call_shell",
        name="run_shell_command",
        args={"command": "find . -maxdepth 2 -type f"},
        source="openai_tool_call",
        group_id="provider-1",
    )
    decision = PermissionDecision(
        status="confirm",
        reason="command is not in the low-risk allowlist",
        risk_level="medium",
        required_mode="danger-full-access",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=invocation,
        source="agent_loop",
    )

    assert pending.tool_name == "run_shell_command"
    assert pending.tool_call_id == "call_shell"
    assert pending.arguments == {"command": "find . -maxdepth 2 -type f"}
    assert pending.preview["command_preview"] == "find . -maxdepth 2 -type f"
    assert pending.preview["command_chars"] == len("find . -maxdepth 2 -type f")
    assert pending.preview["reason"] == "command is not in the low-risk allowlist"
    assert pending.risk_level == "medium"
    assert pending.required_mode == "danger-full-access"


def test_build_pending_tool_confirmation_bounds_large_patch_preview() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="apply_patch",
        reason="Need to change implementation",
        args={
            "files_to_modify": ["app/example.py"],
            "patch": "x" * 5000,
        },
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool apply_patch requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )

    assert pending.preview["files_to_modify"] == ["app/example.py"]
    assert pending.preview["patch_chars"] == 5000
    assert pending.preview["reason"] == "tool apply_patch requires confirmation"
    assert "patch" not in pending.preview


def test_build_pending_tool_confirmation_bounds_shell_command_preview() -> None:
    command = "python -c " + "x" * 1000
    action = ToolCallAction(
        type="tool_call",
        action="run_shell_command",
        reason="Need to run shell",
        args={"command": command},
    )
    decision = PermissionDecision(
        status="confirm",
        reason="shell command requires confirmation",
        risk_level="high",
        required_mode="danger-full-access",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )

    assert pending.preview["command_chars"] == len(command)
    assert len(str(pending.preview["command_preview"])) < len(command)
    assert "command" not in pending.preview


def test_rejected_observation_mentions_tool_and_decision() -> None:
    pending = PendingToolConfirmation(
        id="confirm-123",
        tool_call_id="call_123",
        tool_name="memory_write",
        arguments={"title": "lesson", "content": "body", "kind": "failure_lesson"},
        reason="tool memory_write requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
        preview={"title": "lesson", "kind": "failure_lesson"},
        source="agent_loop",
    )

    observation = build_tool_rejected_observation(pending, user_reply="cancel")

    assert observation.status == "rejected"
    assert observation.summary == "Tool call rejected by user"
    assert observation.payload["tool_name"] == "memory_write"
    assert observation.payload["confirmation_id"] == "confirm-123"
    assert observation.error_message == "user rejected tool memory_write"


def test_confirmation_match_prevents_replay() -> None:
    pending = PendingToolConfirmation(
        id="confirm-123",
        tool_call_id=None,
        tool_name="write_file",
        arguments={"path": "README.md", "content": "hello"},
        reason="requires workspace write",
        risk_level="medium",
        required_mode="workspace-write",
        preview={"path": "README.md", "content_chars": 5},
        source="tui",
        consumed=False,
    )

    assert is_confirmation_match(pending, "confirm-123") is True
    consumed = pending.model_copy(update={"consumed": True})
    assert is_confirmation_match(consumed, "confirm-123") is False
