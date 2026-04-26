from __future__ import annotations

from typing import Any, Literal

from app.schemas.agent_action import Observation, ObservationStatus
from app.tools.schemas import ToolResult

ToolResultStatus = Literal["passed", "failed", "rejected"]
_ENVELOPE_KEYS = frozenset(
    {
        "tool_name",
        "status",
        "summary",
        "is_error",
        "payload",
        "truncated",
        "next_offset",
        "stdout_excerpt",
        "stderr_excerpt",
        "duration_ms",
    }
)


def _observation_status(status: ObservationStatus | ToolResultStatus) -> ObservationStatus:
    if status == "passed":
        return "succeeded"
    return status


def tool_observation(
    *,
    tool_name: str,
    status: ObservationStatus | ToolResultStatus,
    summary: str,
    payload: dict[str, Any] | None = None,
    error_message: str | None = None,
    truncated: bool | None = None,
    next_offset: int | None = None,
    stdout_excerpt: str | None = None,
    stderr_excerpt: str | None = None,
    duration_ms: int | None = None,
) -> Observation:
    """Build an observation with reserved envelope keys at the top level.

    Tool-specific values that collide with reserved envelope keys are preserved
    under nested ``payload``. Non-reserved payload keys are also copied to the
    top level for compatibility with existing consumers.
    """
    observation_status = _observation_status(status)
    tool_payload = dict(payload or {})
    payload_truncated = tool_payload.get("truncated")
    truncated_value = (
        truncated
        if truncated is not None
        else payload_truncated
        if isinstance(payload_truncated, bool)
        else False
    )
    stdout_value = stdout_excerpt
    if stdout_value is None:
        stdout_value = str(tool_payload.get("stdout_excerpt", "") or "")
    stderr_value = stderr_excerpt
    if stderr_value is None:
        stderr_value = str(tool_payload.get("stderr_excerpt", "") or "")

    envelope: dict[str, Any] = {
        "tool_name": tool_name,
        "status": observation_status,
        "summary": summary,
        "is_error": observation_status != "succeeded",
        "payload": tool_payload,
        "truncated": truncated_value,
        "next_offset": next_offset if next_offset is not None else tool_payload.get("next_offset"),
        "stdout_excerpt": stdout_value,
        "stderr_excerpt": stderr_value,
        "duration_ms": duration_ms if duration_ms is not None else tool_payload.get("duration_ms"),
    }
    for key, value in tool_payload.items():
        if key not in _ENVELOPE_KEYS:
            envelope[key] = value

    return Observation(
        status=observation_status,
        summary=summary,
        payload=envelope,
        error_message=error_message,
    )


def observation_from_tool_result(result: ToolResult) -> Observation:
    truncated = result.payload.get("truncated")
    return tool_observation(
        tool_name=result.tool_name,
        status=result.status,
        summary=result.summary,
        payload=result.payload,
        error_message=result.error_message,
        truncated=truncated if isinstance(truncated, bool) else None,
    )
