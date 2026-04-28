from datetime import datetime
from pathlib import Path
from typing import Iterable

from pydantic import ValidationError

from app.memory.models import MemoryKind, MemoryRecord, MemorySearchResult


class MemoryStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "memories.jsonl"

    def append(self, record: MemoryRecord) -> MemoryRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")
        return record

    def list_records(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        records: list[MemoryRecord] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                records.append(MemoryRecord.model_validate_json(line))
            except ValidationError:
                continue
        return records

    def search(
        self,
        *,
        query: str,
        kinds: set[MemoryKind] | None = None,
        tags: set[str] | None = None,
        limit: int = 10,
    ) -> list[MemorySearchResult]:
        terms = _query_terms(query)
        normalized_tags = {tag.casefold() for tag in tags or set()}
        results: list[MemorySearchResult] = []
        for record in self.list_records():
            if kinds is not None and record.kind not in kinds:
                continue
            if normalized_tags and not normalized_tags.intersection(record.tags):
                continue
            score, matched = _score_record(record, terms)
            if score > 0 or not terms:
                results.append(
                    MemorySearchResult(record=record, score=score, matched_terms=matched)
                )
        results.sort(key=lambda result: (result.score, result.record.updated_at), reverse=True)
        return results[:limit]

    def update(self, record_id: str, **changes: object) -> MemoryRecord:
        updated_record: MemoryRecord | None = None
        rewritten_lines: list[str] = []
        for line in self._raw_lines():
            if not line.strip():
                continue
            try:
                record = MemoryRecord.model_validate_json(line)
            except ValidationError:
                rewritten_lines.append(line)
                continue
            if record.id != record_id:
                rewritten_lines.append(line)
                continue
            updated_record = _updated_record(record, changes)
            rewritten_lines.append(updated_record.model_dump_json())
        if updated_record is None:
            raise KeyError(f"unknown memory id: {record_id}")
        self._rewrite_lines(rewritten_lines)
        return updated_record

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


def _query_terms(query: str) -> list[str]:
    return [term for term in query.casefold().replace("_", " ").split() if term]


def _score_record(record: MemoryRecord, terms: list[str]) -> tuple[int, list[str]]:
    haystack = " ".join(
        [record.title, record.content, record.kind, " ".join(record.tags)]
    ).casefold()
    matched = [term for term in terms if term in haystack]
    score = len(matched)
    if any(term in record.title.casefold() for term in terms):
        score += 2
    if any(term in record.tags for term in terms):
        score += 2
    return score, matched


def _updated_record(record: MemoryRecord, changes: dict[str, object]) -> MemoryRecord:
    payload = record.model_dump()
    payload.update(changes)
    payload["updated_at"] = datetime.now().astimezone()
    return MemoryRecord.model_validate(payload)
