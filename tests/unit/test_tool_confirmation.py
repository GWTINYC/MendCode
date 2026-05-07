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
    assert pending.tool_call_group_id == "provider-1"
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

    assert pending.preview["paths"] == ["app/example.py"]
    assert pending.preview["diff_stat"] == {"files": 1, "additions": 0, "deletions": 0}
    assert pending.preview["requires_confirmation"] is True
    assert pending.preview["reason"] == "tool apply_patch requires confirmation"
    assert "patch" not in pending.preview


def test_build_pending_tool_confirmation_uses_write_preview_shape() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="edit_file",
        reason="Need to edit file",
        args={
            "path": "README.md",
            "old_string": "alpha\n",
            "new_string": "beta\ngamma\n",
        },
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool edit_file requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )

    assert pending.preview["paths"] == ["README.md"]
    assert pending.preview["diff_stat"] == {"files": 1, "additions": 2, "deletions": 1}
    assert pending.preview["requires_confirmation"] is True
    assert pending.preview["reason"] == "tool edit_file requires confirmation"
    assert "old_string" not in pending.preview
    assert "new_string" not in pending.preview


def test_pending_confirmation_payload_omits_raw_arguments() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="write_file",
        reason="Need to write file",
        args={"path": "secret.txt", "content": "x" * 5000},
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool write_file requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )
    payload = pending.safe_payload()

    assert "arguments" not in payload
    assert payload["preview"]["paths"] == ["secret.txt"]
    assert payload["preview"]["diff_stat"] == {"files": 1, "additions": 1, "deletions": 0}
    assert payload["preview"]["requires_confirmation"] is True
    assert payload["target"] == "secret.txt"
    assert payload["effect"] == "write file"
    assert payload["risk_reason"] == "tool write_file requires confirmation"


def test_pending_confirmation_payload_includes_edit_target_and_effect() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="edit_file",
        reason="Need to edit file",
        args={"path": "README.md", "old_string": "old", "new_string": "new"},
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool edit_file requires confirmation",
        risk_level="medium",
        required_mode="workspace-write",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )
    payload = pending.safe_payload()

    assert payload["target"] == "README.md"
    assert payload["effect"] == "edit file"
    assert payload["risk_reason"] == "tool edit_file requires confirmation"


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


def test_shell_confirmation_preview_omits_full_short_command() -> None:
    command = "rm README.md"
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
    assert pending.preview["command_preview"] == command
    assert "command_preview" not in pending.safe_payload()["preview"]
    assert command not in str(pending.safe_payload())


def test_build_pending_tool_confirmation_bounds_process_start_preview() -> None:
    command = "python -c " + "x" * 1000
    action = ToolCallAction(
        type="tool_call",
        action="process_start",
        reason="Need to start process",
        args={"command": command, "cwd": "app"},
    )
    decision = PermissionDecision(
        status="confirm",
        reason="process command requires confirmation",
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
    assert "command_preview" not in pending.safe_payload()["preview"]
    assert pending.preview["cwd"] == "app"
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


def test_review_queue_accept_preview_includes_effect_and_source() -> None:
    action = ToolCallAction(
        type="tool_call",
        action="review_queue_accept",
        reason="Accept skill candidate",
        args={
            "candidate_id": "candidate-1",
            "target_kind": "skill",
            "source_report": "data/analysis-reports/run.json",
            "source_trace": "data/traces/run.jsonl",
        },
    )
    decision = PermissionDecision(
        status="confirm",
        reason="tool review_queue_accept requires confirmation",
        risk_level="high",
        required_mode="workspace-write",
    )

    pending = build_pending_tool_confirmation(
        action=action,
        decision=decision,
        tool_invocation=None,
        source="agent_loop",
    )

    assert pending.preview["candidate_id"] == "candidate-1"
    assert pending.preview["target_kind"] == "skill"
    assert pending.preview["source_report"] == "data/analysis-reports/run.json"
    assert pending.preview["source_trace"] == "data/traces/run.jsonl"
    assert pending.preview["effect"] == "accept_candidate"


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
