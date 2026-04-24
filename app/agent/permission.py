from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.agent_action import RiskLevel, ToolCallAction, UserConfirmationRequestAction

PermissionMode = Literal["safe", "guided", "full", "custom"]
PermissionStatus = Literal["allow", "confirm", "deny"]

_TOOL_RISK: dict[str, RiskLevel] = {
    "repo_status": "low",
    "detect_project": "low",
    "read_file": "low",
    "search_code": "low",
    "show_diff": "low",
    "run_command": "medium",
    "apply_patch_to_worktree": "medium",
}


class PermissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PermissionStatus
    reason: str
    risk_level: RiskLevel


def _tool_risk(action: ToolCallAction) -> RiskLevel:
    return _TOOL_RISK[action.action]


def decide_permission(action: ToolCallAction, mode: PermissionMode) -> PermissionDecision:
    risk = _tool_risk(action)
    tool_name = action.action

    if mode == "full":
        return PermissionDecision(
            status="allow",
            reason=f"full mode allows {risk}-risk tool {tool_name}",
            risk_level=risk,
        )

    if mode == "guided":
        if tool_name == "apply_patch_to_worktree":
            return PermissionDecision(
                status="allow",
                reason="guided mode allows worktree patching before user apply",
                risk_level=risk,
            )
        return PermissionDecision(
            status="allow",
            reason=f"guided mode allows {risk}-risk tool {tool_name}",
            risk_level=risk,
        )

    if mode == "safe":
        if risk == "low":
            return PermissionDecision(
                status="allow",
                reason=f"safe mode allows low-risk tool {tool_name}",
                risk_level=risk,
            )
        return PermissionDecision(
            status="confirm",
            reason=f"safe mode requires confirmation for {risk}-risk tool {tool_name}",
            risk_level=risk,
        )

    return PermissionDecision(
        status="confirm",
        reason=(
            "custom mode requires explicit configuration before "
            f"running tool {tool_name}"
        ),
        risk_level=risk,
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
