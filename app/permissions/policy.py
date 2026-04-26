from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.agent_action import RiskLevel, ToolCallAction
from app.tools.registry import default_tool_registry
from app.tools.structured import ToolRegistry, ToolRisk
from app.workspace.shell_policy import ShellPolicyDecision

PermissionMode = Literal[
    "safe",
    "guided",
    "full",
    "custom",
    "read-only",
    "workspace-write",
    "danger-full-access",
]
RequiredPermissionMode = Literal["read-only", "workspace-write", "danger-full-access"]
PermissionStatus = Literal["allow", "confirm", "deny"]

_MODE_RANK: dict[RequiredPermissionMode, int] = {
    "read-only": 1,
    "workspace-write": 2,
    "danger-full-access": 3,
}
_LEGACY_MODE_MAP: dict[str, RequiredPermissionMode | Literal["custom"]] = {
    "safe": "read-only",
    "guided": "workspace-write",
    "full": "danger-full-access",
    "custom": "custom",
}
_REGISTRY_RISK_MAP: dict[ToolRisk, RiskLevel] = {
    ToolRisk.READ_ONLY: "low",
    ToolRisk.WRITE_WORKTREE: "medium",
    ToolRisk.SHELL_RESTRICTED: "medium",
    ToolRisk.DANGEROUS: "high",
}
_REGISTRY_REQUIRED_MODE_MAP: dict[ToolRisk, RequiredPermissionMode] = {
    ToolRisk.READ_ONLY: "read-only",
    ToolRisk.WRITE_WORKTREE: "workspace-write",
    ToolRisk.SHELL_RESTRICTED: "danger-full-access",
    ToolRisk.DANGEROUS: "danger-full-access",
}
_TOOL_REQUIRED_MODE_OVERRIDES: dict[str, RequiredPermissionMode] = {
    "run_command": "workspace-write",
    "apply_patch_to_worktree": "workspace-write",
}
_BUILTIN_TOOL_RISK: dict[str, RiskLevel] = {
    "apply_patch_to_worktree": "medium",
}


class PermissionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: PermissionStatus
    reason: str
    risk_level: RiskLevel
    required_mode: RequiredPermissionMode = "read-only"


def normalize_permission_mode(
    mode: PermissionMode,
) -> RequiredPermissionMode | Literal["custom"]:
    return _LEGACY_MODE_MAP.get(mode, mode)  # type: ignore[return-value]


class PermissionPolicy:
    def __init__(
        self,
        *,
        active_mode: PermissionMode,
        tool_registry: ToolRegistry | None = None,
        allow_tools: Iterable[str] | None = None,
        deny_tools: Iterable[str] | None = None,
        ask_tools: Iterable[str] | None = None,
    ) -> None:
        self.active_mode = active_mode
        self.normalized_mode = normalize_permission_mode(active_mode)
        self.tool_registry = tool_registry or default_tool_registry()
        self.allow_tools = set(allow_tools or [])
        self.deny_tools = set(deny_tools or [])
        self.ask_tools = set(ask_tools or [])

    def decide(
        self,
        action: ToolCallAction,
        *,
        shell_decision: ShellPolicyDecision | None = None,
    ) -> PermissionDecision:
        tool_name = action.action
        required_mode = self.required_mode_for(tool_name)
        risk_level = self.risk_level_for(tool_name)

        if shell_decision is not None:
            shell_override = self._decision_from_shell_classifier(
                tool_name=tool_name,
                shell_decision=shell_decision,
                fallback_required_mode=required_mode,
            )
            if shell_override is not None:
                return shell_override

        if tool_name in self.deny_tools:
            return PermissionDecision(
                status="deny",
                reason=f"tool {tool_name} denied by permission rule",
                risk_level=risk_level,
                required_mode=required_mode,
            )
        if tool_name in self.ask_tools:
            return PermissionDecision(
                status="confirm",
                reason=f"tool {tool_name} requires confirmation by permission rule",
                risk_level=risk_level,
                required_mode=required_mode,
            )
        if tool_name in self.allow_tools:
            return PermissionDecision(
                status="allow",
                reason=f"tool {tool_name} allowed by permission rule",
                risk_level=risk_level,
                required_mode=required_mode,
            )

        if self.normalized_mode == "custom":
            return PermissionDecision(
                status="confirm",
                reason=(
                    "custom mode requires explicit configuration before "
                    f"running tool {tool_name}"
                ),
                risk_level=risk_level,
                required_mode=required_mode,
            )

        active_mode = self.normalized_mode
        if _MODE_RANK[active_mode] >= _MODE_RANK[required_mode]:
            return PermissionDecision(
                status="allow",
                reason=(
                    f"{self.active_mode} mode allows {risk_level}-risk tool {tool_name}"
                ),
                risk_level=risk_level,
                required_mode=required_mode,
            )

        if active_mode == "workspace-write" and required_mode == "danger-full-access":
            return PermissionDecision(
                status="confirm",
                reason=(
                    f"tool {tool_name} requires danger-full-access permission; "
                    "current mode is workspace-write"
                ),
                risk_level=risk_level,
                required_mode=required_mode,
            )

        return PermissionDecision(
            status="deny",
            reason=(
                f"tool {tool_name} requires {required_mode} permission; "
                f"current mode is {active_mode}"
            ),
            risk_level=risk_level,
            required_mode=required_mode,
        )

    def required_mode_for(self, tool_name: str) -> RequiredPermissionMode:
        if tool_name in _TOOL_REQUIRED_MODE_OVERRIDES:
            return _TOOL_REQUIRED_MODE_OVERRIDES[tool_name]
        if tool_name in _BUILTIN_TOOL_RISK:
            return "workspace-write"
        return _REGISTRY_REQUIRED_MODE_MAP[self.tool_registry.get(tool_name).risk_level]

    def risk_level_for(self, tool_name: str) -> RiskLevel:
        if tool_name in _BUILTIN_TOOL_RISK:
            return _BUILTIN_TOOL_RISK[tool_name]
        return _REGISTRY_RISK_MAP[self.tool_registry.get(tool_name).risk_level]

    def _decision_from_shell_classifier(
        self,
        *,
        tool_name: str,
        shell_decision: ShellPolicyDecision,
        fallback_required_mode: RequiredPermissionMode,
    ) -> PermissionDecision | None:
        if shell_decision.risk_level == "critical":
            return PermissionDecision(
                status="deny",
                reason=shell_decision.reason or "critical shell command denied",
                risk_level="critical",
                required_mode="danger-full-access",
            )
        if shell_decision.requires_confirmation:
            return PermissionDecision(
                status="confirm",
                reason=shell_decision.reason or "shell command requires confirmation",
                risk_level=shell_decision.risk_level,
                required_mode="danger-full-access",
            )
        if shell_decision.allowed and shell_decision.risk_level == "low":
            return PermissionDecision(
                status="allow",
                reason=shell_decision.reason or f"low-risk shell command allows {tool_name}",
                risk_level="low",
                required_mode="read-only",
            )
        if not shell_decision.allowed:
            return PermissionDecision(
                status="deny",
                reason=shell_decision.reason or "shell command denied by policy",
                risk_level=shell_decision.risk_level,
                required_mode=fallback_required_mode,
            )
        return None
