from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

RepoMapEntryType = Literal["file", "directory", "symlink"]


class RepoMapEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    type: RepoMapEntryType
    size_bytes: int | None = Field(default=None, ge=0)
    depth: int = Field(ge=0)
    summary: str = ""


class RepoMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root: str = Field(min_length=1)
    generated_at: datetime
    entries: list[RepoMapEntry] = Field(default_factory=list)
    entry_points: list[str] = Field(default_factory=list)
    test_commands: list[str] = Field(default_factory=list)
    core_modules: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)

    @field_serializer("generated_at", when_used="json")
    def serialize_generated_at(self, value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")
