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
        content = compact_text(body.strip(), max_chars=6000)
        if not content:
            continue
        if "user" in normalized or "用户" in normalized:
            user_messages.append(content)
            continue
        if "assistant" in normalized or "mendcode" in normalized or "助手" in normalized:
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
        if "assistant" in event_type and "tool" not in event_type:
            message = _first_text(payload, ["message", "content", "text"]) or event.get("message")
            if message:
                assistant_messages.append(compact_text(message, max_chars=6000))
        if "tool_call" in event_type or event_type.endswith(".tool.call"):
            tool_calls.append(_tool_call_from_payload(payload, len(tool_calls) + 1, event))
        if "observation" in event_type or "tool_result" in event_type:
            observations.append(_observation_from_payload(payload, len(observations) + 1, event))
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
    tool_name = (
        observation.get("tool_name")
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
            observation.get("requires_confirmation")
            or observation.get("needs_user_confirmation")
        ),
        risk_level=str(observation.get("risk_level") or payload.get("risk_level") or "unknown"),
    )


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
