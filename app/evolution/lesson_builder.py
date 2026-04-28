import hashlib
import json
from datetime import datetime, timezone

from app.evolution.models import EvolutionTurnInput, LessonCandidate
from app.memory.models import MemoryKind

_DETERMINISTIC_CREATED_AT = datetime.fromtimestamp(0, tz=timezone.utc)


def build_lesson_candidates(
    turn: EvolutionTurnInput,
) -> tuple[list[str], list[LessonCandidate]]:
    signals: list[str] = []
    candidates: list[LessonCandidate] = []

    if _has_rejected_tool(turn):
        signals.append("tool_rejected")
        candidates.append(
            _lesson_candidate(
                kind="tool_policy_lesson",
                summary="Tool rejected during turn",
                evidence=_rejected_tool_evidence(turn),
                source_trace_path=turn.trace_path,
                suggested_memory_kind="trace_insight",
                confidence=0.7,
            )
        )

    if _repeated_read_file_count(turn) > 0:
        signals.append("repeated_read_file")
        candidates.append(
            _lesson_candidate(
                kind="context_lesson",
                summary="Detected repeated read_file calls during context gathering",
                evidence={
                    "repeated_read_file_count": _repeated_read_file_count(turn),
                    "read_file_count": turn.context_metrics.get("read_file_count", 0),
                },
                source_trace_path=turn.trace_path,
                suggested_memory_kind="trace_insight",
                confidence=0.6,
            )
        )

    if _verification_recovered(turn):
        signals.append("verification_recovered")
        candidates.append(
            _lesson_candidate(
                kind="test_fix_lesson",
                summary="Verification failed and later succeeded after a run_command",
                evidence={"source": "run_command", "status_sequence": ["failed", "succeeded"]},
                source_trace_path=turn.trace_path,
                suggested_memory_kind="failure_lesson",
                suggested_skill="test-fix",
                confidence=0.75,
            )
        )

    if turn.turn_status != "completed":
        signals.append("turn_failed")
        candidates.append(
            _lesson_candidate(
                kind="failure_lesson",
                summary=f"Turn failed: {_summary_text(turn.final_response)}",
                evidence={
                    "turn_status": turn.turn_status,
                    "final_response": turn.final_response,
                },
                source_trace_path=turn.trace_path,
                suggested_memory_kind="failure_lesson",
                confidence=0.6,
            )
        )

    return signals, candidates


def _lesson_candidate(
    *,
    kind: str,
    summary: str,
    evidence: dict[str, object] | None = None,
    source_trace_path: str | None = None,
    suggested_memory_kind: MemoryKind = "failure_lesson",
    suggested_skill: str | None = None,
    confidence: float = 0.5,
) -> LessonCandidate:
    evidence = evidence or {}
    payload = {
        "kind": kind,
        "summary": summary,
        "evidence": evidence,
        "source_trace_path": source_trace_path,
        "suggested_memory_kind": suggested_memory_kind,
        "suggested_skill": suggested_skill,
    }
    candidate_id = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()[:32]
    return LessonCandidate(
        id=candidate_id,
        kind=kind,
        summary=summary,
        evidence=evidence,
        source_trace_path=source_trace_path,
        suggested_memory_kind=suggested_memory_kind,
        suggested_skill=suggested_skill,
        confidence=confidence,
        created_at=_DETERMINISTIC_CREATED_AT,
        updated_at=_DETERMINISTIC_CREATED_AT,
    )


def _summary_text(value: str | None) -> str:
    if value is None or not value.strip():
        return "no final response"
    return value.strip()[:180]


def _has_rejected_tool(turn: EvolutionTurnInput) -> bool:
    return any(_observation_status(step) == "rejected" for step in turn.tool_steps)


def _rejected_tool_evidence(turn: EvolutionTurnInput) -> dict[str, object]:
    for step in turn.tool_steps:
        if _observation_status(step) != "rejected":
            continue
        action = step.get("action")
        observation = step.get("observation")
        return {
            "index": step.get("index"),
            "action": action if isinstance(action, dict) else {},
            "observation": observation if isinstance(observation, dict) else {},
        }
    return {}


def _observation_status(step: dict[str, object]) -> str | None:
    observation = step.get("observation")
    if not isinstance(observation, dict):
        return None
    status = observation.get("status")
    if isinstance(status, str):
        return status
    return None


def _repeated_read_file_count(turn: EvolutionTurnInput) -> int:
    value = turn.context_metrics.get("repeated_read_file_count", 0)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return 0


def _verification_recovered(turn: EvolutionTurnInput) -> bool:
    statuses = _run_command_statuses(turn.tool_steps)
    if not statuses:
        statuses = _verification_statuses(turn.verification_results)
    seen_failed = False
    for status in statuses:
        if status == "failed":
            seen_failed = True
        elif status == "succeeded" and seen_failed:
            return True
    return False


def _run_command_statuses(tool_steps: list[dict[str, object]]) -> list[str]:
    statuses: list[str] = []
    for step in tool_steps:
        if _action_name(step) != "run_command":
            continue
        status = _observation_status(step)
        if status in {"failed", "succeeded"}:
            statuses.append(status)
    return statuses


def _action_name(step: dict[str, object]) -> str | None:
    action = step.get("action")
    if not isinstance(action, dict):
        return None
    name = action.get("action")
    if isinstance(name, str):
        return name
    return None


def _verification_statuses(results: list[dict[str, object]]) -> list[str]:
    statuses: list[str] = []
    for result in results:
        status = result.get("status")
        if status in {"failed", "succeeded"}:
            statuses.append(status)
        elif status == "passed":
            statuses.append("succeeded")
    return statuses
