from app.agent.permission import (
    PermissionDecision,
    build_confirmation_request,
    decide_permission,
)
from app.permissions.policy import PermissionPolicy
from app.schemas.agent_action import ToolCallAction
from app.workspace.shell_policy import ShellPolicyDecision


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
    assert decision.required_mode == "workspace-write"


def test_safe_mode_denies_run_command():
    decision = decide_permission(tool_call("run_command"), mode="safe")

    assert decision.status == "deny"
    assert decision.risk_level == "medium"
    assert decision.required_mode == "workspace-write"


def test_safe_mode_denies_restricted_shell_tools_without_shell_classifier() -> None:
    decision = decide_permission(tool_call("run_shell_command"), mode="safe")

    assert decision.status == "deny"
    assert decision.risk_level == "medium"
    assert decision.required_mode == "danger-full-access"
    assert "run_shell_command" in decision.reason


def test_safe_mode_denies_apply_patch() -> None:
    decision = decide_permission(tool_call("apply_patch"), mode="safe")

    assert decision.status == "deny"
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


def test_read_only_allows_read_tools_and_denies_write_tools() -> None:
    policy = PermissionPolicy(active_mode="read-only")

    read_decision = policy.decide(tool_call("read_file"))
    write_decision = policy.decide(tool_call("apply_patch"))

    assert read_decision.status == "allow"
    assert read_decision.required_mode == "read-only"
    assert write_decision.status == "deny"
    assert write_decision.required_mode == "workspace-write"
    assert "requires workspace-write permission" in write_decision.reason


def test_workspace_write_prompts_for_dangerous_shell() -> None:
    policy = PermissionPolicy(active_mode="workspace-write")
    shell_decision = ShellPolicyDecision(
        allowed=False,
        requires_confirmation=True,
        risk_level="high",
        reason="shell command requires confirmation",
    )

    decision = policy.decide(tool_call("run_shell_command"), shell_decision=shell_decision)

    assert decision.status == "confirm"
    assert decision.risk_level == "high"
    assert decision.required_mode == "danger-full-access"
    assert "shell command requires confirmation" in decision.reason


def test_danger_full_access_allows_registered_tools() -> None:
    policy = PermissionPolicy(active_mode="danger-full-access")

    decision = policy.decide(tool_call("apply_patch"))

    assert decision.status == "allow"
    assert decision.required_mode == "workspace-write"
    assert "danger-full-access mode allows" in decision.reason


def test_low_risk_shell_decision_allows_shell_in_read_only_mode() -> None:
    policy = PermissionPolicy(active_mode="read-only")
    shell_decision = ShellPolicyDecision(
        allowed=True,
        requires_confirmation=False,
        risk_level="low",
        reason="low-risk read-only command",
    )

    decision = policy.decide(tool_call("run_shell_command"), shell_decision=shell_decision)

    assert decision.status == "allow"
    assert decision.required_mode == "read-only"
    assert decision.risk_level == "low"


def test_critical_shell_decision_denies_even_in_danger_full_access() -> None:
    policy = PermissionPolicy(active_mode="danger-full-access")
    shell_decision = ShellPolicyDecision(
        allowed=False,
        requires_confirmation=False,
        risk_level="critical",
        reason="redirection target escapes allowed workspace root",
    )

    decision = policy.decide(tool_call("run_shell_command"), shell_decision=shell_decision)

    assert decision.status == "deny"
    assert decision.risk_level == "critical"
    assert "redirection target escapes allowed workspace root" in decision.reason
