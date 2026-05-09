import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_TEXT_EXCERPT_LIMIT = 800
_COLLECTION_SAMPLE_LIMIT = 20


class SessionNotFoundError(LookupError):
    pass


@dataclass(frozen=True)
class SessionIndexEntry:
    session_id: str
    jsonl_path: Path
    markdown_path: Path | None
    repo_path: str | None
    started_at: str | None
    updated_at: str | None
    event_count: int
    message_count: int
    last_event_type: str | None


@dataclass(frozen=True)
class TraceToolEvent:
    index: int
    tool_name: str
    status: str
    summary: str
    payload_excerpt: str
    payload_truncated: bool
    full_payload: dict[str, Any]


@dataclass(frozen=True)
class TraceView:
    trace_path: Path
    event_count: int
    tool_events: list[TraceToolEvent]


@dataclass(frozen=True)
class TraceSummary:
    event_count: int
    tool_names: list[str]
    failed_tools: list[str]
    tool_events: list[dict[str, object]]
    truncated: bool


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if isinstance(value, dict):
            records.append(value)
    return records


def _session_id_from_jsonl_path(path: Path) -> str:
    return path.stem.rsplit("-", 1)[-1]


def _read_markdown_header(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    header: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines()[:10]:
        if raw_line.startswith("repo: "):
            header["repo_path"] = raw_line.removeprefix("repo: ").strip()
        elif raw_line.startswith("started_at: "):
            header["started_at"] = raw_line.removeprefix("started_at: ").strip()
        elif raw_line.startswith("run_id: "):
            header["run_id"] = raw_line.removeprefix("run_id: ").strip()
    return header


def _timestamp_sort_key(value: str | None, fallback_path: Path) -> tuple[str, float]:
    if value:
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone().isoformat(), 0.0
        except ValueError:
            return value, 0.0
    return "", fallback_path.stat().st_mtime


def _text_excerpt(value: object, *, max_chars: int = _TEXT_EXCERPT_LIMIT) -> dict[str, object]:
    text = str(value)
    truncated = len(text) > max_chars
    return {
        "excerpt": text[:max_chars] + ("...[truncated]" if truncated else ""),
        "length": len(text),
        "truncated": truncated,
    }


def _compact_collection(
    values: list[Any],
    *,
    sample_key: str,
    count_key: str,
    truncated_key: str,
) -> dict[str, object]:
    return {
        count_key: len(values),
        sample_key: values[:_COLLECTION_SAMPLE_LIMIT],
        truncated_key: len(values) > _COLLECTION_SAMPLE_LIMIT,
    }


def _compact_payload(payload: dict[str, Any]) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key in [
        "command",
        "status",
        "exit_code",
        "relative_path",
        "file_path",
        "pattern",
        "summary",
        "trace_path",
        "workspace_path",
        "step_count",
        "total_entries",
        "total_matches",
        "truncated",
        "stdout_excerpt",
        "stderr_excerpt",
        "content_excerpt",
        "content_length",
        "content_truncated",
    ]:
        if key in payload:
            compact[key] = payload[key]

    if "content" in payload:
        excerpt = _text_excerpt(payload["content"])
        compact["content_excerpt"] = excerpt["excerpt"]
        compact["content_length"] = excerpt["length"]
        compact["content_truncated"] = excerpt["truncated"]

    entries = payload.get("entries")
    if isinstance(entries, list):
        compact.update(
            _compact_collection(
                entries,
                sample_key="entries_sample",
                count_key="entries_count",
                truncated_key="entries_truncated",
            )
        )

    matches = payload.get("matches")
    if isinstance(matches, list):
        compact.update(
            _compact_collection(
                matches,
                sample_key="matches_sample",
                count_key="matches_count",
                truncated_key="matches_truncated",
            )
        )

    nested_payload = payload.get("payload")
    if isinstance(nested_payload, dict):
        compact["payload"] = _compact_payload(nested_payload)

    return compact


def _action_name(action: object) -> str:
    if isinstance(action, dict):
        return str(action.get("action") or action.get("type") or "unknown")
    return str(action)


def _step_summary(step: object) -> str | None:
    if not isinstance(step, dict):
        return None
    observation = step.get("observation")
    if isinstance(observation, dict):
        status = observation.get("status", "unknown")
        summary = observation.get("summary", "")
        line = f"{_action_name(step.get('action'))}: {status} - {summary}".rstrip()
        payload = observation.get("payload")
        if isinstance(payload, dict):
            compact_payload = _compact_payload(payload)
            if compact_payload:
                line += f" ({_format_inline_payload(compact_payload)})"
        return line
    status = step.get("status", "unknown")
    summary = step.get("summary", "")
    line = f"{_action_name(step.get('action'))}: {status} - {summary}".rstrip()
    payload = step.get("payload")
    if isinstance(payload, dict):
        compact_payload = _compact_payload(payload)
        if compact_payload:
            line += f" ({_format_inline_payload(compact_payload)})"
    return line


def _format_inline_payload(payload: dict[str, object]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            rendered = (
                str(value)
                .replace("\r\n", "\\n")
                .replace("\n", "\\n")
                .replace("\r", "\\n")
            )
        if len(rendered) > 120:
            rendered = rendered[:120] + "...[truncated]"
        parts.append(f"{key}={rendered}")
    return ", ".join(parts)


def _trace_payload_excerpt(
    payload: dict[str, Any],
    *,
    max_excerpt_chars: int,
) -> tuple[str, bool]:
    compact_payload = _compact_payload(payload)
    text = json.dumps(compact_payload or payload, ensure_ascii=False, sort_keys=True)
    truncated = len(text) > max_excerpt_chars
    if truncated:
        text = text[:max_excerpt_chars] + "...[truncated]"
    return text, truncated


def _redact_sensitive_text(text: str) -> str:
    replacements = [
        (r"sk-[A-Za-z0-9_\-]{6,}", "sk-[redacted]"),
        (r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", r"\1[redacted]"),
        (r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?bearer\s+)[^\"'\s,}]+", r"\1[redacted]"),
    ]
    redacted = text
    for pattern, replacement in replacements:
        redacted = re.sub(pattern, replacement, redacted)
    return redacted


def _safe_trace_excerpt(event: TraceToolEvent, *, max_excerpt_chars: int) -> tuple[str, bool]:
    payload = event.full_payload
    observation = payload.get("observation")
    observation_payload = observation.get("payload") if isinstance(observation, dict) else None
    compact: dict[str, object] = {
        "index": event.index,
        "tool_name": event.tool_name,
        "status": event.status,
        "summary": event.summary,
    }
    if isinstance(observation_payload, dict):
        compact_payload = _compact_payload(observation_payload)
        for hidden_key in ["trace_path", "workspace_path"]:
            compact_payload.pop(hidden_key, None)
        if compact_payload:
            compact["payload"] = compact_payload
    text = _redact_sensitive_text(json.dumps(compact, ensure_ascii=False, sort_keys=True))
    truncated = len(text) > max_excerpt_chars or event.payload_truncated
    if len(text) > max_excerpt_chars:
        text = text[:max_excerpt_chars] + "...[truncated]"
    return text, truncated


class SessionStore:
    def __init__(self, *, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.conversations_dir = data_dir / "conversations"

    def list_sessions(self) -> list[SessionIndexEntry]:
        entries = [self._index_jsonl(path) for path in self.conversations_dir.glob("*.jsonl")]
        return sorted(
            entries,
            key=lambda item: _timestamp_sort_key(item.updated_at, item.jsonl_path),
            reverse=True,
        )

    def latest_session(self) -> SessionIndexEntry:
        sessions = self.list_sessions()
        if not sessions:
            raise SessionNotFoundError("no conversation sessions found")
        return sessions[0]

    def get_session(self, session_id: str) -> SessionIndexEntry:
        for session in self.list_sessions():
            if session.session_id == session_id:
                return session
        raise SessionNotFoundError(f"session not found: {session_id}")

    def build_resume_context(
        self,
        session_id: str | None = None,
        *,
        max_events: int = 30,
    ) -> str:
        session = self.latest_session() if session_id is None else self.get_session(session_id)
        records = _read_jsonl(session.jsonl_path)[-max_events:]
        lines = [
            "Previous MendCode session:",
            f"session_id: {session.session_id}",
            f"repo_path: {session.repo_path or ''}",
            f"started_at: {session.started_at or ''}",
            f"updated_at: {session.updated_at or ''}",
            "recent_messages:",
        ]
        for record in records:
            if record.get("event_type") != "message":
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            role = str(payload.get("role", "unknown"))
            message = str(payload.get("message", ""))
            excerpt = _text_excerpt(message, max_chars=1000)
            lines.append(f"- {role}: {excerpt['excerpt']}")

        tool_lines = self._tool_summary_lines(records)
        if tool_lines:
            lines.append("tool_summaries:")
            lines.extend(f"- {line}" for line in tool_lines)
        return "\n".join(lines)

    def _index_jsonl(self, jsonl_path: Path) -> SessionIndexEntry:
        records = _read_jsonl(jsonl_path)
        markdown_path = jsonl_path.with_suffix(".md")
        if not markdown_path.exists():
            markdown_path = None
        header = _read_markdown_header(markdown_path)
        session_id = header.get("run_id") or _session_id_from_jsonl_path(jsonl_path)
        messages = [record for record in records if record.get("event_type") == "message"]
        first_timestamp = str(records[0].get("timestamp")) if records else None
        last_timestamp = str(records[-1].get("timestamp")) if records else None
        return SessionIndexEntry(
            session_id=session_id,
            jsonl_path=jsonl_path,
            markdown_path=markdown_path,
            repo_path=header.get("repo_path"),
            started_at=header.get("started_at") or first_timestamp,
            updated_at=last_timestamp or header.get("started_at"),
            event_count=len(records),
            message_count=len(messages),
            last_event_type=str(records[-1].get("event_type")) if records else None,
        )

    def _tool_summary_lines(self, records: list[dict[str, Any]]) -> list[str]:
        lines: list[str] = []
        for record in records:
            event_type = record.get("event_type")
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            if event_type in {"tool_result", "turn_result"}:
                lines.extend(_summarize_tool_payload(payload))
            elif event_type == "shell_result":
                compact = _compact_payload(payload)
                lines.append(
                    f"shell: {payload.get('status', 'unknown')} "
                    f"({_format_inline_payload(compact)})"
                )
        return lines

    def read_trace_summary(
        self,
        session_id: str | None = None,
        *,
        trace_path: Path | None = None,
        max_tool_events: int = 20,
        max_excerpt_chars: int = 600,
    ) -> TraceSummary:
        if trace_path is None:
            session = self.latest_session() if session_id is None else self.get_session(session_id)
            trace_path = session.jsonl_path
        view = read_trace_view(trace_path, max_excerpt_chars=max_excerpt_chars)
        limited_events = view.tool_events[-max_tool_events:]
        tool_names = _dedupe_preserve_order([event.tool_name for event in limited_events])
        failed_tools = _dedupe_preserve_order(
            [
                event.tool_name
                for event in limited_events
                if event.status not in {"succeeded", "passed"}
            ]
        )
        event_payloads: list[dict[str, object]] = []
        truncated = len(view.tool_events) > len(limited_events)
        for event in limited_events:
            excerpt, excerpt_truncated = _safe_trace_excerpt(
                event,
                max_excerpt_chars=max_excerpt_chars,
            )
            truncated = truncated or excerpt_truncated
            event_payloads.append(
                {
                    "index": event.index,
                    "tool_name": event.tool_name,
                    "status": event.status,
                    "summary": event.summary,
                    "payload_excerpt": excerpt,
                    "payload_truncated": excerpt_truncated,
                }
            )
        return TraceSummary(
            event_count=view.event_count,
            tool_names=tool_names,
            failed_tools=failed_tools,
            tool_events=event_payloads,
            truncated=truncated,
        )


def _summarize_tool_payload(payload: dict[str, Any]) -> list[str]:
    result_payload = payload
    if isinstance(payload.get("result"), dict):
        result_payload = payload["result"]
    lines: list[str] = []
    status = result_payload.get("status")
    summary = result_payload.get("summary")
    if status or summary:
        head = f"result: {status or 'unknown'}"
        if summary:
            head += f" - {summary}"
        lines.append(head)

    steps = result_payload.get("steps")
    if isinstance(steps, list):
        for step in steps:
            line = _step_summary(step)
            if line is not None:
                lines.append(line)

    tool_summaries = payload.get("tool_summaries")
    if isinstance(tool_summaries, list):
        for summary_item in tool_summaries:
            if not isinstance(summary_item, dict):
                continue
            lines.append(
                f"{summary_item.get('action', 'tool')}: "
                f"{summary_item.get('status', 'unknown')} - "
                f"{summary_item.get('summary', '')}".rstrip()
            )
    return lines


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def read_trace_view(trace_path: Path, *, max_excerpt_chars: int = 1200) -> TraceView:
    records = _read_jsonl(trace_path)
    tool_events: list[TraceToolEvent] = []
    for record in records:
        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        action = payload.get("action")
        if not isinstance(action, dict) or action.get("type") != "tool_call":
            continue
        observation = payload.get("observation")
        if not isinstance(observation, dict):
            observation = {}
        excerpt, truncated = _trace_payload_excerpt(payload, max_excerpt_chars=max_excerpt_chars)
        tool_events.append(
            TraceToolEvent(
                index=int(payload.get("index", 0)),
                tool_name=str(action.get("action", "unknown")),
                status=str(observation.get("status", "unknown")),
                summary=str(observation.get("summary", "")),
                payload_excerpt=excerpt,
                payload_truncated=truncated,
                full_payload=payload,
            )
        )
    return TraceView(trace_path=trace_path, event_count=len(records), tool_events=tool_events)
