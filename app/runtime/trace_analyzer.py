import json
from pathlib import Path
from typing import Any

from app.memory.models import MemoryRecord


def analyze_trace(trace_path: Path) -> MemoryRecord | None:
    if not trace_path.exists():
        raise FileNotFoundError(trace_path)
    events = _read_events(trace_path)
    if _final_run_status(events) == "completed":
        return None
    failed_events = [_failure_payload(event) for event in events]
    failed_events = [event for event in failed_events if event is not None]
    if not failed_events:
        return None
    first = failed_events[0]
    category = _category_for(first)
    summary = str(first.get("summary") or "Unknown failure")
    error_message = str(first.get("error_message") or "")
    return MemoryRecord(
        kind="failure_lesson",
        title=f"{summary} ({category})",
        content=_lesson_content(
            summary=summary,
            error_message=error_message,
            category=category,
        ),
        source=f"trace:{trace_path}",
        tags=["trace", "failure", category],
        metadata={
            "category": category,
            "trace_path": str(trace_path),
            "summary": summary,
            "error_message": error_message,
        },
    )


def _read_events(trace_path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line in trace_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _failure_payload(event: dict[str, Any]) -> dict[str, Any] | None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    observation = payload.get("observation")
    if isinstance(observation, dict) and observation.get("status") in {
        "failed",
        "rejected",
    }:
        return {
            "summary": observation.get("summary"),
            "error_message": observation.get("error_message"),
            "action": payload.get("action"),
        }
    if payload.get("status") == "failed":
        return {
            "summary": payload.get("summary"),
            "error_message": payload.get("error_message"),
        }
    return None


def _final_run_status(events: list[dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event.get("event_type") != "agent.run.completed":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict) and isinstance(payload.get("status"), str):
            return str(payload["status"])
    return None


def _category_for(payload: dict[str, Any]) -> str:
    text = " ".join(
        str(payload.get(key) or "") for key in ["summary", "error_message"]
    ).casefold()
    normalized_text = text.replace("-", " ").replace("_", " ")
    if "repeated" in normalized_text:
        return "tool_repetition"
    if "provider" in normalized_text or "tool call" in normalized_text:
        return "provider_protocol"
    if "permission" in normalized_text or "confirmation" in normalized_text:
        return "permission"
    if "verification" in normalized_text or "run command" in normalized_text:
        return "verification"
    return "runtime_failure"


def _lesson_content(*, summary: str, error_message: str, category: str) -> str:
    return "\n".join(
        [
            f"Category: {category}",
            f"Summary: {summary}",
            f"Error: {error_message or 'none'}",
            "Constraint: future runs should use tool evidence and preserve "
            "structured observations.",
        ]
    )
