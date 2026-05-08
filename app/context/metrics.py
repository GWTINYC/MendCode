from collections import Counter
from collections.abc import Iterable
from pathlib import PurePosixPath
from typing import Any

from app.agent.provider import AgentObservationRecord
from app.context.models import ContextMetrics


def metrics_for_observations(
    observations: Iterable[AgentObservationRecord],
) -> ContextMetrics:
    observation_list = list(observations)
    read_file_paths = normalized_read_file_paths(observation_list)
    path_counts = Counter(read_file_paths)
    repeated_read_file_count = sum(count - 1 for count in path_counts.values() if count > 1)

    return ContextMetrics(
        observation_count=len(observation_list),
        read_file_count=len(read_file_paths),
        repeated_read_file_count=repeated_read_file_count,
    )


def normalized_read_file_paths(
    observations: Iterable[AgentObservationRecord],
) -> list[str]:
    return [
        normalized_path
        for observation in observations
        if _is_read_file_observation(observation)
        for path in [_read_file_path(observation)]
        for normalized_path in [_normalize_path(path)]
        if normalized_path is not None
    ]


def merge_context_metrics(*metrics: ContextMetrics) -> ContextMetrics:
    merged = ContextMetrics()
    for metric in metrics:
        merged = ContextMetrics(
            context_chars=merged.context_chars + metric.context_chars,
            estimated_context_tokens=(
                merged.estimated_context_tokens + metric.estimated_context_tokens
            ),
            raw_context_chars=merged.raw_context_chars + metric.raw_context_chars,
            raw_context_tokens=merged.raw_context_tokens + metric.raw_context_tokens,
            compacted_context_chars=(
                merged.compacted_context_chars + metric.compacted_context_chars
            ),
            compacted_context_tokens=(
                merged.compacted_context_tokens + metric.compacted_context_tokens
            ),
            memory_recall_hits=merged.memory_recall_hits + metric.memory_recall_hits,
            observation_count=merged.observation_count + metric.observation_count,
            read_file_count=merged.read_file_count + metric.read_file_count,
            repeated_read_file_count=(
                merged.repeated_read_file_count + metric.repeated_read_file_count
            ),
            compacted_item_count=merged.compacted_item_count + metric.compacted_item_count,
            file_summary_hit_count=(
                merged.file_summary_hit_count + metric.file_summary_hit_count
            ),
            repo_context_chars=merged.repo_context_chars + metric.repo_context_chars,
            repo_context_tokens=merged.repo_context_tokens + metric.repo_context_tokens,
            observation_chars_saved=(
                merged.observation_chars_saved + metric.observation_chars_saved
            ),
            observation_tokens_saved=(
                merged.observation_tokens_saved + metric.observation_tokens_saved
            ),
            section_chars=_merge_int_maps(merged.section_chars, metric.section_chars),
            section_tokens=_merge_int_maps(merged.section_tokens, metric.section_tokens),
            section_token_budgets={
                **merged.section_token_budgets,
                **metric.section_token_budgets,
            },
        )
    return merged


def _merge_int_maps(first: dict[str, int], second: dict[str, int]) -> dict[str, int]:
    merged = dict(first)
    for key, value in second.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def _is_read_file_observation(record: AgentObservationRecord) -> bool:
    if record.action is not None and getattr(record.action, "action", None) == "read_file":
        return True
    if record.tool_invocation is not None and record.tool_invocation.name == "read_file":
        return True
    payload_tool = record.observation.payload.get("tool") or record.observation.payload.get(
        "tool_name"
    )
    return payload_tool == "read_file"


def _read_file_path(record: AgentObservationRecord) -> str | None:
    payload = record.observation.payload
    for key in ("relative_path", "path", "file_path"):
        value = _string_value(payload.get(key))
        if value is not None:
            return value

    if record.action is not None:
        value = _path_from_args(getattr(record.action, "args", {}))
        if value is not None:
            return value

    if record.tool_invocation is not None:
        value = _path_from_args(record.tool_invocation.args)
        if value is not None:
            return value

    return None


def _path_from_args(args: dict[str, Any]) -> str | None:
    for key in ("relative_path", "path", "file_path"):
        value = _string_value(args.get(key))
        if value is not None:
            return value
    return None


def _string_value(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _normalize_path(path: str | None) -> str | None:
    if path is None:
        return None
    stripped = path.strip()
    if not stripped:
        return None
    while stripped.startswith("./"):
        stripped = stripped[2:]
    return PurePosixPath(stripped).as_posix()
