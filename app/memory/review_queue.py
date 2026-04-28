from datetime import datetime
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from app.evolution.models import LessonCandidate, LessonCandidateStatus


class MemoryReviewQueue:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "review_queue.jsonl"

    def append(self, candidate: LessonCandidate) -> LessonCandidate:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(candidate.model_dump_json())
            handle.write("\n")
        return candidate

    def list_candidates(self) -> list[LessonCandidate]:
        candidates: list[LessonCandidate] = []
        for line in self._raw_lines():
            if not line.strip():
                continue
            try:
                candidates.append(LessonCandidate.model_validate_json(line))
            except ValidationError:
                continue
        return candidates

    def update_status(
        self,
        candidate_id: str,
        status: LessonCandidateStatus,
    ) -> LessonCandidate:
        updated: LessonCandidate | None = None
        rewritten_lines: list[str] = []
        for line in self._raw_lines():
            if not line.strip():
                continue
            try:
                candidate = LessonCandidate.model_validate_json(line)
            except ValidationError:
                rewritten_lines.append(line)
                continue
            if candidate.id != candidate_id:
                rewritten_lines.append(line)
                continue
            updated = _updated_candidate(candidate, status)
            rewritten_lines.append(updated.model_dump_json())
        if updated is None:
            raise KeyError(f"unknown lesson candidate: {candidate_id}")
        self._rewrite_lines(rewritten_lines)
        return updated

    def _raw_lines(self) -> list[str]:
        if not self.path.exists():
            return []
        return self.path.read_text(encoding="utf-8").splitlines()

    def _rewrite_lines(self, lines: Iterable[str]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".jsonl.tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            for line in lines:
                handle.write(line)
                handle.write("\n")
        temp_path.replace(self.path)


def _updated_candidate(
    candidate: LessonCandidate,
    status: LessonCandidateStatus,
) -> LessonCandidate:
    payload = candidate.model_dump()
    payload["status"] = status
    payload["updated_at"] = datetime.now().astimezone()
    return LessonCandidate.model_validate(payload)
