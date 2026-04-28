from pathlib import Path

from app.evolution.models import LessonCandidate
from app.memory.models import MemoryRecord
from app.memory.runtime import MemoryRuntime
from app.memory.store import MemoryStore


def _runtime(tmp_path: Path) -> MemoryRuntime:
    return MemoryRuntime(MemoryStore(tmp_path / "memory"))


def test_memory_runtime_recalls_compact_hits(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    runtime.store.append(
        MemoryRecord(
            kind="project_fact",
            title="pytest command",
            content="Use python -m pytest -q for checks.",
            source="test",
            tags=["pytest"],
        )
    )

    result = runtime.recall_for_turn(
        user_message="pytest 怎么运行",
        repo_state={"repo_path": str(tmp_path)},
        max_items=2,
    )

    assert result.total_matches == 1
    assert result.hits[0].title == "pytest command"
    assert result.hits[0].content_excerpt == "Use python -m pytest -q for checks."
    assert result.returned_chars > 0


def test_memory_runtime_review_queue_append_list_accept_reject(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="Use read_file tail_lines for final-line questions.",
        evidence={"tool": "read_file", "path": "README.md"},
        source_trace_path="trace.jsonl",
        suggested_memory_kind="failure_lesson",
        confidence=0.8,
    )

    enqueued = runtime.enqueue_candidate(candidate)
    listed = runtime.list_candidates()

    assert enqueued.candidate_id == candidate.id
    assert listed[0].summary == candidate.summary

    accepted = runtime.accept_candidate(candidate.id)
    assert accepted.kind == "failure_lesson"
    assert accepted.title == candidate.summary
    assert runtime.list_candidates()[0].status == "accepted"

    second = LessonCandidate(
        kind="tool_policy_lesson",
        summary="Rejected tool calls should be reviewed.",
        evidence={"status": "rejected"},
        source_trace_path="trace.jsonl",
        suggested_memory_kind="trace_insight",
        confidence=0.7,
    )
    runtime.enqueue_candidate(second)
    runtime.reject_candidate(second.id)

    statuses = {candidate.id: candidate.status for candidate in runtime.list_candidates()}
    assert statuses[second.id] == "rejected"
