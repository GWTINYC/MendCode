from app.agent.permission import (
    PermissionDecision,
    build_confirmation_request,
    decide_permission,
)
from app.schemas.agent_action import ToolCallAction


def tool_call(action: str) -> ToolCallAction:
    return ToolCallAction(
        type="tool_call",
        action=action,
        reason=f"Need to call {action}",
        args={},
    )


def test_guided_mode_allows_read_only_tools():
    decision = decide_permission(tool_call("read_file"), mode="guided")

    assert decision == PermissionDecision(
        status="allow",
        reason="guided mode allows low-risk tool read_file",
        risk_level="low",
    )


def test_guided_mode_allows_worktree_patch_but_not_main_workspace_apply():
    decision = decide_permission(tool_call("apply_patch_to_worktree"), mode="guided")

    assert decision.status == "allow"
    assert decision.risk_level == "medium"
    assert "worktree" in decision.reason


def test_guided_mode_allows_structured_apply_patch_in_worktree() -> None:
    decision = decide_permission(tool_call("apply_patch"), mode="guided")

    assert decision.status == "allow"
    assert decision.risk_level == "medium"
    assert "worktree patching" in decision.reason


def test_safe_mode_requires_confirmation_for_run_command():
    decision = decide_permission(tool_call("run_command"), mode="safe")

    assert decision.status == "confirm"
    assert decision.risk_level == "medium"
    assert "safe mode requires confirmation" in decision.reason


def test_safe_mode_requires_confirmation_for_apply_patch() -> None:
    decision = decide_permission(tool_call("apply_patch"), mode="safe")

    assert decision.status == "confirm"
    assert decision.risk_level == "medium"


def test_full_mode_allows_known_tools():
    decision = decide_permission(tool_call("run_command"), mode="full")

    assert decision.status == "allow"
    assert decision.risk_level == "medium"
    assert "full mode allows" in decision.reason


def test_custom_mode_requires_confirmation_by_default():
    decision = decide_permission(tool_call("search_code"), mode="custom")

    assert decision.status == "confirm"
    assert decision.risk_level == "low"
    assert "custom mode requires explicit configuration" in decision.reason


def test_build_confirmation_request_includes_action_reason_and_risk():
    action = tool_call("run_command")
    decision = decide_permission(action, mode="safe")

    request = build_confirmation_request(action=action, decision=decision)

    assert request.type == "user_confirmation_request"
    assert request.risk_level == "medium"
    assert "run_command" in request.prompt
    assert "Need to call run_command" in request.prompt
    assert request.options == ["allow_once", "deny", "change_permission_mode"]
