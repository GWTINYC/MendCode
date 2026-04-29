from typing import Any

from app.agent.provider import AgentObservationRecord
from app.context.models import ContextItem


def compact_observation_record(
    record: AgentObservationRecord,
    *,
    max_chars: int,
    max_collection_items: int = 8,
) -> ContextItem:
    tool_name = _tool_name(record)
    metadata: dict[str, Any] = {
        "tool_name": tool_name,
        "status": record.observation.status,
    }
    payload = record.observation.payload
    content_parts = [record.observation.summary]
    if record.observation.error_message:
        content_parts.append(_excerpt(record.observation.error_message, max_chars=max_chars))

    for key in [
        "relative_path",
        "file_path",
        "path",
        "command",
        "pattern",
        "total_entries",
        "total_matches",
        "exit_code",
        "status",
        "truncated",
    ]:
        if key in payload:
            metadata[key] = payload[key]

    if isinstance(payload.get("content"), str):
        content = str(payload["content"])
        metadata["content_length"] = len(content)
        metadata["content_truncated"] = len(content) > max_chars
        content_parts.append(_excerpt(content, max_chars=max_chars))

    for key, sample_key in [("entries", "entries_sample"), ("matches", "matches_sample")]:
        values = payload.get(key)
        if isinstance(values, list):
            metadata[f"{key}_count"] = len(values)
            metadata[f"{key}_truncated"] = len(values) > max_collection_items
            metadata[sample_key] = [
                _compact_mapping(item, max_chars=240)
                for item in values[:max_collection_items]
                if isinstance(item, dict)
            ]

    text = "\n".join(part for part in content_parts if part)
    return ContextItem(
        kind="observation",
        title=f"{tool_name or 'tool'}: {record.observation.status}",
        content=_excerpt(text, max_chars=max_chars),
        metadata=metadata,
    )


def compact_memory_hit(hit: Any, *, max_chars: int) -> dict[str, object]:
    dump = hit.model_dump(mode="json", exclude_none=True)
    if isinstance(dump.get("content_excerpt"), str):
        dump["content_excerpt"] = _excerpt(str(dump["content_excerpt"]), max_chars=max_chars)
    return dump


def _tool_name(record: AgentObservationRecord) -> str | None:
    if record.tool_invocation is not None:
        return record.tool_invocation.name
    if record.action is not None:
        return getattr(record.action, "action", None)
    payload_tool = record.observation.payload.get("tool_name") or record.observation.payload.get(
        "tool"
    )
    return str(payload_tool) if isinstance(payload_tool, str) else None


def _compact_mapping(value: dict[str, object], *, max_chars: int) -> dict[str, object]:
    compact: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, str):
            compact[str(key)] = _excerpt(item, max_chars=max_chars)
        elif item is None or isinstance(item, (bool, int, float)):
            compact[str(key)] = item
        else:
            compact[str(key)] = _excerpt(str(item), max_chars=max_chars)
    return compact


def _excerpt(value: str, *, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"
