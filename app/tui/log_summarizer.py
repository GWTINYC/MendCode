from typing import Any

from pydantic import BaseModel

from app.agent.loop import AgentLoopResult, AgentStep
from app.agent.session import AgentSessionTurn

_MAX_TEXT_CHARS = 1200
_MAX_COLLECTION_ITEMS = 25


def _dump_model(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=True)
    return value


def _text_excerpt(value: object, *, max_chars: int = _MAX_TEXT_CHARS) -> dict[str, object]:
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
    sample = [_dump_model(item) for item in values[:_MAX_COLLECTION_ITEMS]]
    return {
        count_key: len(values),
        sample_key: sample,
        truncated_key: len(values) > _MAX_COLLECTION_ITEMS,
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
        "failed_node",
        "test_name",
        "error_summary",
        "diff_stat",
        "total_entries",
        "total_matches",
        "truncated",
        "stdout_excerpt",
        "stderr_excerpt",
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


def _action_name(step: AgentStep) -> str:
    action = step.action
    return str(getattr(action, "action", action.type))


def _compact_step(step: AgentStep) -> dict[str, object]:
    compact: dict[str, object] = {
        "index": step.index,
        "action": _action_name(step),
        "status": step.observation.status,
        "summary": step.observation.summary,
    }
    if step.observation.error_message is not None:
        compact["error_message"] = step.observation.error_message
    payload = _compact_payload(step.observation.payload)
    if payload:
        compact["payload"] = payload
    return compact


def compact_agent_loop_result(result: AgentLoopResult) -> dict[str, object]:
    return {
        "run_id": result.run_id,
        "status": result.status,
        "summary": result.summary,
        "trace_path": result.trace_path,
        "workspace_path": result.workspace_path,
        "step_count": len(result.steps),
        "steps": [_compact_step(step) for step in result.steps],
    }


def compact_agent_session_turn(turn: AgentSessionTurn) -> dict[str, object]:
    return {
        "index": turn.index,
        "problem_statement": turn.problem_statement,
        "result": compact_agent_loop_result(turn.result),
        "review": turn.review.model_dump(mode="json", exclude_none=True),
        "attempts": [
            attempt.model_dump(mode="json", exclude_none=True)
            for attempt in turn.attempts
        ],
        "tool_summaries": [
            summary.model_dump(mode="json", exclude_none=True)
            for summary in turn.tool_summaries
        ],
    }
