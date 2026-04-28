from datetime import datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

MemoryKind = Literal[
    "project_fact",
    "task_state",
    "file_summary",
    "failure_lesson",
    "trace_insight",
]


class MemoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: MemoryKind
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=1, max_length=12000)
    source: str = Field(min_length=1, max_length=240)
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, tags: list[str]) -> list[str]:
        normalized: list[str] = []
        for tag in tags:
            value = tag.strip().casefold()
            if value and value not in normalized:
                normalized.append(value)
        return normalized


class MemorySearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record: MemoryRecord
    score: int = Field(ge=0)
    matched_terms: list[str] = Field(default_factory=list)


class FileSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content_sha256: str
    mtime_ns: int
    size_bytes: int
    line_count: int
    summary: str
    symbols: list[str] = Field(default_factory=list)
