from pydantic import BaseModel, ConfigDict, Field

from app.memory.models import MemoryKind


class MemoryRecallHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: MemoryKind
    title: str
    content_excerpt: str
    tags: list[str] = Field(default_factory=list)
    score: int = Field(ge=0)
    source: str


class MemoryRecallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    kinds: list[MemoryKind] = Field(default_factory=list)
    hits: list[MemoryRecallHit] = Field(default_factory=list)
    total_matches: int = Field(default=0, ge=0)
    returned_chars: int = Field(default=0, ge=0)
    truncated: bool = False
