from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ContextItemKind = Literal[
    "base_context",
    "memory_recall",
    "evolution_rule",
    "context_warning",
    "context_metrics",
    "observation",
    "file_summary",
    "compaction_notice",
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
    max_evolution_rules: int = Field(default=3, ge=0)
    max_context_chars: int = Field(default=16000, ge=1000)
    max_memory_chars: int = Field(default=4000, ge=0)
    max_evolution_rule_chars: int = Field(default=1200, ge=0)
    max_observation_chars: int = Field(default=8000, ge=0)
    max_file_summary_chars: int = Field(default=3000, ge=0)
    max_observation_items: int = Field(default=12, ge=0)
    max_item_excerpt_chars: int = Field(default=1200, ge=100)


class ContextMetrics(StrictContextModel):
    context_chars: int = Field(default=0, ge=0)
    raw_context_chars: int = Field(default=0, ge=0)
    compacted_context_chars: int = Field(default=0, ge=0)
    memory_recall_hits: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    read_file_count: int = Field(default=0, ge=0)
    repeated_read_file_count: int = Field(default=0, ge=0)
    compacted_item_count: int = Field(default=0, ge=0)
    file_summary_hit_count: int = Field(default=0, ge=0)
    observation_chars_saved: int = Field(default=0, ge=0)


class ContextWarning(StrictContextModel):
    code: str
    message: str
    source: str | None = None


class ContextBundle(StrictContextModel):
    provider_context: str
    metrics: ContextMetrics
    warnings: list[ContextWarning] = Field(default_factory=list)
    items: list[ContextItem] = Field(default_factory=list)
