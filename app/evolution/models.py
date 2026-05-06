from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.memory.models import MemoryKind

LessonCandidateKind = Literal[
    "failure_lesson",
    "tool_policy_lesson",
    "context_lesson",
    "test_fix_lesson",
]
LessonCandidateStatus = Literal["pending", "accepted", "rejected"]
EvolutionRuleType = Literal[
    "tool_required",
    "observation_required",
    "tool_schema_hint",
    "answer_style",
]
EvolutionRuleStatus = Literal["active", "disabled"]
EvolutionRuleCandidateStatus = Literal["pending", "accepted", "rejected"]
EvolutionTargetKind = Literal["memory", "rule"]


class EvolutionRuleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=120)
    rule_type: EvolutionRuleType
    rule_text: str = Field(min_length=1, max_length=1200)
    scope: str = Field(default="", max_length=400)
    activation_hint: str = Field(default="", max_length=600)
    source_report: str | None = Field(default=None, max_length=240)
    source_trace: str | None = Field(default=None, max_length=240)
    evidence: dict[str, Any] = Field(default_factory=dict)
    root_cause: str | None = Field(default=None, max_length=240)
    status: EvolutionRuleCandidateStatus = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class EvolutionRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    candidate_id: str
    rule_type: EvolutionRuleType
    rule_text: str = Field(min_length=1, max_length=1200)
    scope: str = Field(default="", max_length=400)
    activation_hint: str = Field(default="", max_length=600)
    evidence_ref: str | None = None
    source_report: str | None = None
    source_trace: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    status: EvolutionRuleStatus = "active"


class LessonCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: LessonCandidateKind
    summary: str = Field(min_length=1, max_length=240)
    evidence: dict[str, object] = Field(default_factory=dict)
    source_trace_path: str | None = None
    suggested_memory_kind: MemoryKind = "failure_lesson"
    suggested_skill: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    status: LessonCandidateStatus = "pending"
    target_kind: EvolutionTargetKind = "memory"
    rule_candidate: EvolutionRuleCandidate | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    updated_at: datetime = Field(default_factory=lambda: datetime.now().astimezone())


class EvolutionTurnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str
    final_response: str | None = None
    turn_status: str
    tool_steps: list[dict[str, object]] = Field(default_factory=list)
    trace_path: str | None = None
    verification_results: list[dict[str, object]] = Field(default_factory=list)
    context_metrics: dict[str, object] = Field(default_factory=dict)


class EvolutionTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_candidates: list[LessonCandidate] = Field(default_factory=list)
    skipped_reason: str | None = None
    signals: list[str] = Field(default_factory=list)
    error: dict[str, str] | None = None
