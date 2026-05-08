from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ContextItemKind = Literal[
    "base_context",
    "memory_recall",
    "evolution_rule",
    "evolution_guidance",
    "context_warning",
    "context_metrics",
    "observation",
    "file_summary",
    "repo_context",
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
    max_context_tokens: int = Field(default=4000, ge=1)
    max_base_tokens: int = Field(default=400, ge=0)
    max_task_state_tokens: int = Field(default=250, ge=0)
    max_repo_context_tokens: int = Field(default=500, ge=0)
    max_memory_tokens: int = Field(default=800, ge=0)
    max_guidance_tokens: int = Field(default=400, ge=0)
    max_observations_tokens: int = Field(default=1200, ge=0)
    max_file_summaries_tokens: int = Field(default=450, ge=0)
    max_context_chars: int = Field(default=16000, ge=1000)
    max_memory_chars: int = Field(default=4000, ge=0)
    max_evolution_rule_chars: int = Field(default=1200, ge=0)
    max_observation_chars: int = Field(default=8000, ge=0)
    max_file_summary_chars: int = Field(default=3000, ge=0)
    max_repo_context_chars: int = Field(default=2000, ge=0)
    max_observation_items: int = Field(default=12, ge=0)
    max_item_excerpt_chars: int = Field(default=1200, ge=100)

    def section_token_budgets(self) -> dict[str, int]:
        return {
            "base": self.max_base_tokens,
            "task_state": self.max_task_state_tokens,
            "repo_context": self.max_repo_context_tokens,
            "memory": self.max_memory_tokens,
            "guidance": self.max_guidance_tokens,
            "observations": self.max_observations_tokens,
            "file_summaries": self.max_file_summaries_tokens,
        }


class ContextMetrics(StrictContextModel):
    context_chars: int = Field(default=0, ge=0)
    estimated_context_tokens: int = Field(default=0, ge=0)
    raw_context_chars: int = Field(default=0, ge=0)
    raw_context_tokens: int = Field(default=0, ge=0)
    compacted_context_chars: int = Field(default=0, ge=0)
    compacted_context_tokens: int = Field(default=0, ge=0)
    memory_recall_hits: int = Field(default=0, ge=0)
    observation_count: int = Field(default=0, ge=0)
    read_file_count: int = Field(default=0, ge=0)
    repeated_read_file_count: int = Field(default=0, ge=0)
    compacted_item_count: int = Field(default=0, ge=0)
    file_summary_hit_count: int = Field(default=0, ge=0)
    repo_context_chars: int = Field(default=0, ge=0)
    repo_context_tokens: int = Field(default=0, ge=0)
    observation_chars_saved: int = Field(default=0, ge=0)
    observation_tokens_saved: int = Field(default=0, ge=0)
    section_chars: dict[str, int] = Field(default_factory=dict)
    section_tokens: dict[str, int] = Field(default_factory=dict)
    section_token_budgets: dict[str, int] = Field(default_factory=dict)


class ContextWarning(StrictContextModel):
    code: str
    message: str
    source: str | None = None


class ContextBundle(StrictContextModel):
    provider_context: str
    metrics: ContextMetrics
    warnings: list[ContextWarning] = Field(default_factory=list)
    items: list[ContextItem] = Field(default_factory=list)
