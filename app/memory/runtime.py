from pathlib import Path

from pydantic import BaseModel, ConfigDict

from app.evolution.models import LessonCandidate
from app.memory.file_summary import build_file_summary
from app.memory.models import FileSummary, MemoryKind, MemoryRecord
from app.memory.recall import MemoryRecallHit, MemoryRecallResult
from app.memory.review_queue import MemoryReviewQueue
from app.memory.store import MemoryStore


class ReviewQueueResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    status: str


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
        candidate = self.review_queue.update_status(candidate_id, "accepted")
        record = MemoryRecord(
            kind=candidate.suggested_memory_kind,
            title=candidate.summary,
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
        return self.store.append(record)

    def reject_candidate(self, candidate_id: str) -> ReviewQueueResult:
        candidate = self.review_queue.update_status(candidate_id, "rejected")
        return ReviewQueueResult(candidate_id=candidate.id, status=candidate.status)


def _candidate_content(candidate: LessonCandidate) -> str:
    lines = [candidate.summary]
    if candidate.source_trace_path:
        lines.append(f"Trace: {candidate.source_trace_path}")
    if candidate.evidence:
        lines.append(f"Evidence: {candidate.evidence}")
    return "\n".join(lines)
