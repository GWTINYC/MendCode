from app.permissions.policy import (
    PermissionDecision,
    PermissionMode,
    PermissionPolicy,
    PermissionStatus,
)
from app.schemas.agent_action import ToolCallAction, UserConfirmationRequestAction
from app.workspace.shell_policy import ShellPolicyDecision

__all__ = [
    "PermissionDecision",
    "PermissionMode",
    "PermissionPolicy",
    "PermissionStatus",
    "build_confirmation_request",
    "decide_permission",
]


def decide_permission(
    action: ToolCallAction,
    mode: PermissionMode,
    *,
    shell_decision: ShellPolicyDecision | None = None,
) -> PermissionDecision:
    return PermissionPolicy(active_mode=mode).decide(
        action,
        shell_decision=shell_decision,
    )


def build_confirmation_request(
    *,
    action: ToolCallAction,
    decision: PermissionDecision,
) -> UserConfirmationRequestAction:
    return UserConfirmationRequestAction(
        type="user_confirmation_request",
        prompt=(
            f"Agent wants to run {action.action}.\n"
            f"Reason: {action.reason}\n"
            f"Permission decision: {decision.reason}"
        ),
        risk_level=decision.risk_level,
        options=["allow_once", "deny", "change_permission_mode"],
    )
