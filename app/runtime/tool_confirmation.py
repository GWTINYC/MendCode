from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.permissions.policy import PermissionDecision, RequiredPermissionMode
from app.schemas.agent_action import Observation, RiskLevel, ToolCallAction
from app.tools.schemas import build_patch_preview, build_write_preview, count_text_lines
from app.tools.structured import ToolInvocation

_MAX_PREVIEW_ITEMS = 20
_MAX_PREVIEW_CHARS = 240


class PendingToolConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"confirm-{uuid4().hex[:12]}")
    tool_call_id: str | None = None
    tool_call_group_id: str | None = None
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    risk_level: RiskLevel
    required_mode: RequiredPermissionMode
    target: str = ""
    effect: str = ""
    risk_reason: str = ""
    preview: dict[str, Any] = Field(default_factory=dict)
    source: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    consumed: bool = False

    @property
    def command(self) -> str:
        if self.tool_name != "run_shell_command":
            raise AttributeError("command is only available for pending shell commands")
        return str(self.arguments.get("command", ""))

    def safe_payload(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json", exclude={"arguments"})
        if self.tool_name in {"run_shell_command", "process_start"}:
            preview = dict(payload.get("preview", {}))
            preview.pop("command_preview", None)
            payload["preview"] = preview
            payload["target"] = ""
        return payload


def build_pending_tool_confirmation(
    *,
    action: ToolCallAction,
    decision: PermissionDecision,
    tool_invocation: ToolInvocation | None,
    source: str,
) -> PendingToolConfirmation:
    return PendingToolConfirmation(
        tool_call_id=tool_invocation.id if tool_invocation is not None else None,
        tool_call_group_id=tool_invocation.group_id if tool_invocation is not None else None,
        tool_name=action.action,
        arguments=dict(action.args),
        reason=decision.reason,
        risk_level=decision.risk_level,
        required_mode=decision.required_mode,
        target=decision.target or _target_for_tool(action.action, action.args),
        effect=decision.effect or _effect_for_tool(action.action),
        risk_reason=decision.risk_reason or decision.reason,
        preview=_preview_for_tool(action.action, action.args, decision.reason),
        source=source,
    )


def build_tool_rejected_observation(
    pending: PendingToolConfirmation,
    *,
    user_reply: str,
) -> Observation:
    return Observation(
        status="rejected",
        summary="Tool call rejected by user",
        payload={
            "confirmation_id": pending.id,
            "tool_call_id": pending.tool_call_id,
            "tool_call_group_id": pending.tool_call_group_id,
            "tool_name": pending.tool_name,
            "risk_level": pending.risk_level,
            "required_mode": pending.required_mode,
            "target": pending.target,
            "effect": pending.effect,
            "risk_reason": pending.risk_reason,
            "reason": pending.reason,
            "user_reply": user_reply,
        },
        error_message=f"user rejected tool {pending.tool_name}",
    )


def is_confirmation_match(pending: PendingToolConfirmation, confirmation_id: str) -> bool:
    return pending.id == confirmation_id and not pending.consumed


def _preview_for_tool(
    tool_name: str,
    args: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    if tool_name == "run_shell_command":
        command = str(args.get("command", ""))
        return {
            "command_preview": _bounded_string(command),
            "command_chars": len(command),
            "reason": reason,
        }
    if tool_name == "process_start":
        command = str(args.get("command", ""))
        return {
            "command_preview": _bounded_string(command),
            "command_chars": len(command),
            "cwd": str(args.get("cwd", ".")),
            "reason": reason,
        }
    if tool_name == "apply_patch":
        files = args.get("files_to_modify", [])
        paths = [str(path) for path in _bounded_list(files)]
        patch = str(args.get("patch", ""))
        return build_patch_preview(paths=paths, patch=patch, reason=reason)
    if tool_name == "write_file":
        return build_write_preview(
            paths=[str(args.get("path", ""))],
            additions=count_text_lines(str(args.get("content", ""))),
            deletions=0,
            reason=reason,
        )
    if tool_name == "edit_file":
        return build_write_preview(
            paths=[str(args.get("path", ""))],
            additions=count_text_lines(str(args.get("new_string", ""))),
            deletions=count_text_lines(str(args.get("old_string", ""))),
            reason=reason,
        )
    if tool_name == "git":
        return {
            "operation": str(args.get("operation", args.get("command", ""))),
            "path": args.get("path"),
            "reason": reason,
        }
    if tool_name == "memory_write":
        return {
            "kind": str(args.get("kind", "")),
            "title": str(args.get("title", "")),
            "tags": _bounded_list(args.get("tags", [])),
            "content_chars": len(str(args.get("content", ""))),
            "reason": reason,
        }
    if tool_name in {"review_queue_accept", "review_queue_reject"}:
        effect = "accept_candidate" if tool_name == "review_queue_accept" else "reject_candidate"
        return {
            "candidate_id": str(args.get("candidate_id", "")),
            "target_kind": str(args.get("target_kind", "")),
            "source_report": str(args.get("source_report", "")),
            "source_trace": str(args.get("source_trace", "")),
            "effect": effect,
            "reason": reason,
        }
    return {
        "argument_keys": sorted(str(key) for key in args.keys())[:_MAX_PREVIEW_ITEMS],
        "reason": reason,
    }


def _target_for_tool(tool_name: str, args: dict[str, Any]) -> str:
    if tool_name in {"run_shell_command", "process_start"}:
        return str(args.get("command", ""))
    if tool_name in {"write_file", "edit_file"}:
        return str(args.get("path", ""))
    if tool_name == "apply_patch":
        files = args.get("files_to_modify", [])
        if isinstance(files, list):
            return ", ".join(str(path) for path in files[:_MAX_PREVIEW_ITEMS])
        return ""
    if tool_name == "git":
        path = args.get("path")
        return str(path) if path not in {None, ""} else str(args.get("operation", ""))
    if tool_name in {"review_queue_accept", "review_queue_reject"}:
        return str(args.get("candidate_id", ""))
    if tool_name == "memory_write":
        return str(args.get("title", ""))
    return ""


def _effect_for_tool(tool_name: str) -> str:
    effects = {
        "run_shell_command": "run shell command",
        "process_start": "start process",
        "apply_patch": "apply patch",
        "write_file": "write file",
        "edit_file": "edit file",
        "git": "run git operation",
        "memory_write": "write memory",
        "review_queue_accept": "accept review candidate",
        "review_queue_reject": "reject review candidate",
    }
    return effects.get(tool_name, f"run {tool_name}")


def _bounded_list(value: object) -> list[object]:
    if not isinstance(value, list):
        return []
    return value[:_MAX_PREVIEW_ITEMS]


def _bounded_string(value: str) -> str:
    if len(value) <= _MAX_PREVIEW_CHARS:
        return value
    return f"{value[:_MAX_PREVIEW_CHARS]}..."
