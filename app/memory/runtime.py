from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.evolution.models import LessonCandidate, LessonCandidateStatus
from app.memory.file_summary import build_file_summary
from app.memory.models import FileSummary, MemoryKind, MemoryRecord
from app.memory.recall import MemoryRecallHit, MemoryRecallResult
from app.memory.review_queue import MemoryReviewQueue
from app.memory.store import MemoryStore


class ReviewQueueResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    status: LessonCandidateStatus


class MemoryRuntime:
    def __init__(self, store: MemoryStore) -> None:
        self.store = store
        self.review_queue = MemoryReviewQueue(store.root)

    def recall_for_turn(
        self,
        *,
        user_message: str,
        repo_state: dict[str, object],
        max_items: int = 5,
    ) -> MemoryRecallResult:
        del repo_state
        kinds: set[MemoryKind] = {
            "project_fact",
            "task_state",
            "failure_lesson",
            "trace_insight",
        }
        results = self.store.search(
            query=user_message,
            kinds=kinds,
            limit=max_items + 1,
        )
        limited_results = results[:max_items]
        hits = [
            MemoryRecallHit(
                id=result.record.id,
                kind=result.record.kind,
                title=result.record.title,
                content_excerpt=result.record.content[:1200],
                tags=result.record.tags,
                score=result.score,
                source=result.record.source,
            )
            for result in limited_results
        ]
        returned_chars = sum(len(hit.title) + len(hit.content_excerpt) for hit in hits)
        return MemoryRecallResult(
            query=user_message,
            kinds=sorted(kinds),
            hits=hits,
            total_matches=len(results),
            returned_chars=returned_chars,
            truncated=len(results) > max_items,
        )

    def get_file_summary(self, repo_path: Path, path: str) -> FileSummary:
        return build_file_summary(repo_path, path)

    def enqueue_candidate(self, candidate: LessonCandidate) -> ReviewQueueResult:
        written = self.review_queue.append(candidate)
        return ReviewQueueResult(candidate_id=written.id, status=written.status)

    def list_candidates(self) -> list[LessonCandidate]:
        return self.review_queue.list_candidates()

    def accept_candidate(self, candidate_id: str) -> MemoryRecord:
        candidate = self._candidate_for_id(candidate_id)
        existing = self._memory_for_candidate(candidate.id)
        if candidate.status == "accepted":
            if existing is None:
                raise ValueError(f"accepted lesson candidate has no memory: {candidate_id}")
            return existing
        if candidate.status == "rejected":
            raise ValueError(f"cannot accept rejected lesson candidate: {candidate_id}")
        if existing is not None:
            self.review_queue.update_status(candidate.id, "accepted")
            return existing

        record = self.store.append(_memory_record_from_candidate(candidate))
        self.review_queue.update_status(candidate.id, "accepted")
        return record

    def reject_candidate(self, candidate_id: str) -> ReviewQueueResult:
        candidate = self._candidate_for_id(candidate_id)
        if candidate.status == "accepted":
            raise ValueError(f"cannot reject accepted lesson candidate: {candidate_id}")
        if candidate.status == "rejected":
            return ReviewQueueResult(candidate_id=candidate.id, status=candidate.status)
        candidate = self.review_queue.update_status(candidate.id, "rejected")
        return ReviewQueueResult(candidate_id=candidate.id, status=candidate.status)

    def _candidate_for_id(self, candidate_id: str) -> LessonCandidate:
        for candidate in self.review_queue.list_candidates():
            if candidate.id == candidate_id:
                return candidate
        raise KeyError(f"unknown lesson candidate: {candidate_id}")

    def _memory_for_candidate(self, candidate_id: str) -> MemoryRecord | None:
        for record in self.store.list_records():
            if record.metadata.get("candidate_id") == candidate_id:
                return record
        return None


def _memory_record_from_candidate(candidate: LessonCandidate) -> MemoryRecord:
    return MemoryRecord(
        kind=candidate.suggested_memory_kind,
        title=_candidate_title(candidate),
        content=_candidate_content(candidate),
        source=f"lesson_candidate:{candidate.id}",
        tags=["lesson", candidate.kind],
        metadata={
            "candidate_id": candidate.id,
            "candidate_kind": candidate.kind,
            "source_trace_path": candidate.source_trace_path,
            "confidence": candidate.confidence,
            "evidence": candidate.evidence,
        },
    )


def _candidate_title(candidate: LessonCandidate) -> str:
    if len(candidate.summary) <= 160:
        return candidate.summary
    return f"{candidate.summary[:157]}..."


def _candidate_content(candidate: LessonCandidate) -> str:
    lines = [candidate.summary]
    if candidate.source_trace_path:
        lines.append(f"Trace: {candidate.source_trace_path}")
    if candidate.evidence:
        lines.append(f"Evidence: {candidate.evidence}")
    return "\n".join(lines)
