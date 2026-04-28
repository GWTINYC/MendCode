from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ContextItemKind = Literal[
    "base_context",
    "memory_recall",
    "context_warning",
    "context_metrics",
]


class StrictContextModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ContextItem(StrictContextModel):

    kind: ContextItemKind
    title: str
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ContextBudget(StrictContextModel):
    max_memory_items: int = Field(default=5, ge=0)


class ContextMetrics(StrictContextModel):
    context_chars: int = Field(default=0, ge=0)
    memory_recall_hits: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    read_file_count: int = Field(default=0, ge=0)
    repeated_read_file_count: int = Field(default=0, ge=0)


class ContextWarning(StrictContextModel):
    code: str
    message: str
    source: str | None = None


class ContextBundle(StrictContextModel):
    provider_context: str
    metrics: ContextMetrics
    warnings: list[ContextWarning] = Field(default_factory=list)
    items: list[ContextItem] = Field(default_factory=list)
