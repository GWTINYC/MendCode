from pathlib import Path

import pytest

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


def test_enqueue_candidate_leaves_long_term_memory_untouched(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="Queue only.",
        suggested_memory_kind="failure_lesson",
    )

    runtime.enqueue_candidate(candidate)

    assert runtime.store.list_records() == []
    assert not runtime.store.path.exists()


def test_accept_candidate_handles_long_summary_before_marking_accepted(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="x" * 240,
        suggested_memory_kind="failure_lesson",
    )
    runtime.enqueue_candidate(candidate)

    accepted = runtime.accept_candidate(candidate.id)

    assert accepted.title == ("x" * 157) + "..."
    assert len(accepted.title) == 160
    assert runtime.list_candidates()[0].status == "accepted"


def test_accept_candidate_is_idempotent_without_duplicate_memory(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="Accept once.",
        suggested_memory_kind="failure_lesson",
    )
    runtime.enqueue_candidate(candidate)

    first = runtime.accept_candidate(candidate.id)
    second = runtime.accept_candidate(candidate.id)

    assert second.id == first.id
    records = runtime.store.list_records()
    assert len(records) == 1
    assert records[0].metadata["candidate_id"] == candidate.id


def test_rejected_candidate_cannot_be_accepted(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="Reject first.",
        suggested_memory_kind="failure_lesson",
    )
    runtime.enqueue_candidate(candidate)
    runtime.reject_candidate(candidate.id)

    with pytest.raises(ValueError, match="cannot accept rejected lesson candidate"):
        runtime.accept_candidate(candidate.id)

    assert runtime.store.list_records() == []
    assert runtime.list_candidates()[0].status == "rejected"


def test_review_queue_ignores_invalid_rows_and_preserves_them_on_rewrite(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    invalid_row = '{"kind":"future_candidate","summary":"future"}'
    candidate = LessonCandidate(
        kind="context_lesson",
        summary="Valid row.",
        suggested_memory_kind="failure_lesson",
    )
    runtime.enqueue_candidate(candidate)
    with runtime.review_queue.path.open("a", encoding="utf-8") as handle:
        handle.write(invalid_row)
        handle.write("\n")

    listed = runtime.list_candidates()
    runtime.reject_candidate(candidate.id)

    assert [candidate.id for candidate in listed] == [candidate.id]
    lines = runtime.review_queue.path.read_text(encoding="utf-8").splitlines()
    assert invalid_row in lines
