from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from app.runtime.session_analysis.models import (
    ObservationEvent,
    SessionTranscript,
    ToolCallEvent,
    compact_json,
    compact_text,
)

_HEADING_RE = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")
_TOOL_RE = re.compile(r"tool\s*[:=]\s*(?P<tool>[A-Za-z0-9_./-]+)", re.IGNORECASE)
_STATUS_RE = re.compile(r"status\s*[:=]\s*(?P<status>[A-Za-z0-9_./-]+)", re.IGNORECASE)
_STDERR_RE = re.compile(r"stderr\s*[:=]\s*(?P<stderr>.*)", re.IGNORECASE | re.DOTALL)


def parse_session_file(path: Path) -> SessionTranscript:
    resolved = path.expanduser()
    if not resolved.exists():
        raise FileNotFoundError(resolved)
    if resolved.suffix.lower() == ".md":
        return _parse_markdown(resolved)
    if resolved.suffix.lower() == ".jsonl":
        return _parse_jsonl(resolved)
    raise ValueError(f"unsupported session file type: {resolved.suffix}")


def _parse_markdown(path: Path) -> SessionTranscript:
    sections = _split_markdown_sections(path.read_text(encoding="utf-8"))
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    tool_calls: list[ToolCallEvent] = []
    observations: list[ObservationEvent] = []

    for title, body in sections:
        normalized = title.casefold()
        content = compact_text(_markdown_section_body(body), max_chars=6000)
        if not content:
            continue
        if _is_markdown_user_heading(normalized):
            user_messages.append(content)
            continue
        if _is_markdown_assistant_heading(normalized):
            assistant_messages.append(content)
            continue
        if "tool" in normalized or "工具" in normalized or "command" in normalized:
            tool_name = _extract_regex(_TOOL_RE, content, "tool") or "unknown"
            status = _extract_regex(_STATUS_RE, content, "status") or "unknown"
            stderr = _extract_regex(_STDERR_RE, content, "stderr") or ""
            call_index = len(tool_calls) + 1
            tool_calls.append(
                ToolCallEvent(
                    tool_name=tool_name,
                    arguments={},
                    call_index=call_index,
                    status=status,
                    raw_excerpt=content,
                )
            )
            observations.append(
                ObservationEvent(
                    tool_name=tool_name,
                    status=status,
                    stderr_excerpt=stderr,
                    raw_excerpt=content,
                    call_index=call_index,
                )
            )

    final_answer = assistant_messages[-1] if assistant_messages else ""
    return SessionTranscript(
        session_id=path.stem,
        source_path=path,
        input_kind="conversation_markdown",
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tool_calls=tool_calls,
        observations=observations,
        final_answer=final_answer,
    )


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_title = "document"
    current_lines: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            sections.append((current_title, current_lines))
            current_title = match.group("title")
            current_lines = []
        else:
            current_lines.append(line)
    sections.append((current_title, current_lines))
    return [(title, "\n".join(lines)) for title, lines in sections]


def _parse_jsonl(path: Path) -> SessionTranscript:
    user_messages: list[str] = []
    assistant_messages: list[str] = []
    tool_calls: list[ToolCallEvent] = []
    observations: list[ObservationEvent] = []
    final_answer = ""

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("event_type") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        payload = payload if isinstance(payload, dict) else {}

        if "user" in event_type:
            message = _first_text(
                payload, ["message", "content", "user_message"]
            ) or event.get("message")
            if message:
                user_messages.append(compact_text(message, max_chars=6000))
        if event_type == "agent.run.started":
            message = _first_text(payload, ["problem_statement"])
            if message:
                user_messages.append(compact_text(message, max_chars=6000))
        if "assistant" in event_type and "tool" not in event_type:
            message = _first_text(payload, ["message", "content", "text"]) or event.get("message")
            if message:
                assistant_messages.append(compact_text(message, max_chars=6000))
        if "tool_call" in event_type or event_type.endswith(".tool.call"):
            tool_calls.append(_tool_call_from_payload(payload, len(tool_calls) + 1, event))
        if "observation" in event_type or "tool_result" in event_type:
            observations.append(_observation_from_payload(payload, len(observations) + 1, event))
        if event_type == "agent.action.completed":
            call_index = _optional_int(payload.get("index")) or len(tool_calls) + 1
            tool_calls.append(_tool_call_from_action_payload(payload, call_index, event))
            observations.append(_observation_from_payload(payload, call_index, event))
        if "final" in event_type or event_type == "agent.run.completed":
            text = _first_text(payload, ["content", "final_response", "response", "summary"])
            if text:
                final_answer = compact_text(text, max_chars=6000)

    if not final_answer and assistant_messages:
        final_answer = assistant_messages[-1]

    return SessionTranscript(
        session_id=path.stem,
        source_path=path,
        input_kind="jsonl_trace",
        user_messages=user_messages,
        assistant_messages=assistant_messages,
        tool_calls=tool_calls,
        observations=observations,
        final_answer=final_answer,
    )


def _tool_call_from_payload(
    payload: dict[str, Any],
    call_index: int,
    raw_event: dict[str, Any],
) -> ToolCallEvent:
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    arguments = payload.get("arguments")
    if arguments is None and isinstance(action, dict):
        arguments = action.get("args") or action.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    tool_name = (
        _first_text(payload, ["tool_name", "name", "action"])
        or _first_text(action if isinstance(action, dict) else {}, ["tool_name", "name", "type"])
        or "unknown"
    )
    return ToolCallEvent(
        tool_name=tool_name,
        arguments=arguments,
        call_index=call_index,
        status=str(payload.get("status") or "unknown"),
        requires_confirmation=bool(
            payload.get("requires_confirmation")
            or payload.get("needs_user_confirmation")
        ),
        risk_level=str(payload.get("risk_level") or "unknown"),
        duration_ms=_optional_int(payload.get("duration_ms")),
        raw_excerpt=compact_json(raw_event),
    )


def _tool_call_from_action_payload(
    payload: dict[str, Any],
    call_index: int,
    raw_event: dict[str, Any],
) -> ToolCallEvent:
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    observation = (
        payload.get("observation") if isinstance(payload.get("observation"), dict) else {}
    )
    observation_payload = (
        observation.get("payload") if isinstance(observation.get("payload"), dict) else {}
    )
    permission_decision = _permission_decision_from(observation_payload)
    arguments = action.get("args") or action.get("arguments") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    return ToolCallEvent(
        tool_name=str(action.get("tool_name") or action.get("type") or "unknown"),
        arguments=arguments,
        call_index=call_index,
        status=str(observation.get("status") or payload.get("status") or "unknown"),
        requires_confirmation=bool(
            permission_decision.get("requires_confirmation")
            or observation.get("requires_confirmation")
            or observation.get("needs_user_confirmation")
        ),
        risk_level=str(
            permission_decision.get("risk_level")
            or observation.get("risk_level")
            or payload.get("risk_level")
            or "unknown"
        ),
        duration_ms=_optional_int(payload.get("duration_ms")),
        raw_excerpt=compact_json(raw_event),
    )


def _observation_from_payload(
    payload: dict[str, Any],
    call_index: int,
    raw_event: dict[str, Any],
) -> ObservationEvent:
    observation = payload.get("observation")
    if not isinstance(observation, dict):
        observation = payload
    nested_payload = (
        observation.get("payload") if isinstance(observation.get("payload"), dict) else {}
    )
    action = payload.get("action") if isinstance(payload.get("action"), dict) else {}
    permission_decision = _permission_decision_from(nested_payload)
    tool_name = (
        observation.get("tool_name")
        or action.get("tool_name")
        or payload.get("tool_name")
        or payload.get("action")
        or "unknown"
    )
    stdout = nested_payload.get("stdout") or observation.get("stdout") or ""
    stderr = nested_payload.get("stderr") or observation.get("stderr") or ""
    content = nested_payload if nested_payload else observation.get("content") or ""
    error_message = observation.get("error_message") or payload.get("error_message") or ""
    return ObservationEvent(
        tool_name=str(tool_name),
        status=str(observation.get("status") or payload.get("status") or "unknown"),
        stdout_excerpt=compact_text(stdout),
        stderr_excerpt=compact_text(stderr),
        content_excerpt=compact_json(content),
        exit_code=_optional_int(nested_payload.get("exit_code") or observation.get("exit_code")),
        error_excerpt=compact_text(error_message),
        raw_excerpt=compact_json(raw_event),
        call_index=call_index,
        requires_confirmation=bool(
            permission_decision.get("requires_confirmation")
            or nested_payload.get("pending_confirmation")
            or nested_payload.get("shell_policy_decision") == "confirm"
            or nested_payload.get("permission_decision") == "confirm"
            or observation.get("requires_confirmation")
            or observation.get("needs_user_confirmation")
        ),
        risk_level=str(
            permission_decision.get("risk_level")
            or observation.get("risk_level")
            or payload.get("risk_level")
            or "unknown"
        ),
    )


def _markdown_section_body(body: str) -> str:
    lines = body.strip().splitlines()
    if lines and lines[0].startswith("timestamp:"):
        lines = lines[1:]
    while lines and not lines[0].strip():
        lines = lines[1:]
    if len(lines) >= 2 and lines[0].startswith("```"):
        closing_index = _closing_fence_index(lines[1:])
        if closing_index is not None:
            return "\n".join(lines[1:closing_index]).strip()
    return body.strip()


def _closing_fence_index(lines_after_opening: list[str]) -> int | None:
    for index, line in enumerate(lines_after_opening, start=1):
        if line.startswith("```"):
            return index
    return None


def _is_markdown_user_heading(normalized: str) -> bool:
    return (
        "user" in normalized
        or "用户" in normalized
        or normalized.endswith(" - you")
        or normalized.endswith("- you")
    )


def _is_markdown_assistant_heading(normalized: str) -> bool:
    return (
        "assistant" in normalized
        or "助手" in normalized
        or normalized.endswith(" - agent")
        or normalized.endswith("- agent")
    )


def _permission_decision_from(payload: dict[str, Any]) -> dict[str, Any]:
    permission_decision = payload.get("permission_decision")
    if isinstance(permission_decision, dict):
        return permission_decision
    shell_decision = payload.get("shell_policy_decision")
    if isinstance(shell_decision, dict):
        return shell_decision
    return {}


def _extract_regex(pattern: re.Pattern[str], text: str, group: str) -> str | None:
    match = pattern.search(text)
    if match is None:
        return None
    return match.group(group).strip()


def _first_text(payload: dict[str, Any], keys: list[str]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
