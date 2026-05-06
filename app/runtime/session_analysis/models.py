from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

InputKind = Literal["conversation_markdown", "jsonl_trace"]
FindingSeverity = Literal["info", "warning", "error"]

MAX_EXCERPT_CHARS = 1200


def compact_text(value: Any, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    text = "" if value is None else str(value)
    text = text.replace("\r\n", "\n")
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n[truncated]"


def compact_json(value: Any, *, max_chars: int = MAX_EXCERPT_CHARS) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        text = str(value)
    return compact_text(text, max_chars=max_chars)


def fingerprint_value(value: Any) -> str:
    raw = compact_json(value, max_chars=8000)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class ToolCallEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_index: int = 0
    status: str = "unknown"
    requires_confirmation: bool = False
    risk_level: str = "unknown"
    duration_ms: int | None = None
    raw_excerpt: str = ""

    @field_validator("tool_name")
    @classmethod
    def validate_tool_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("tool_name is required")
        return stripped

    @computed_field
    @property
    def arguments_excerpt(self) -> str:
        return compact_json(self.arguments)

    @computed_field
    @property
    def arguments_fingerprint(self) -> str:
        return fingerprint_value({"tool_name": self.tool_name, "arguments": self.arguments})


class ObservationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    status: str = "unknown"
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    content_excerpt: str = ""
    exit_code: int | None = None
    error_excerpt: str = ""
    raw_excerpt: str = ""
    call_index: int | None = None
    requires_confirmation: bool = False
    risk_level: str = "unknown"

    @field_validator(
        "stdout_excerpt",
        "stderr_excerpt",
        "content_excerpt",
        "error_excerpt",
        "raw_excerpt",
    )
    @classmethod
    def bound_text(cls, value: str) -> str:
        return compact_text(value)

    @computed_field
    @property
    def visible_chars(self) -> int:
        return len(self.stdout_excerpt) + len(self.stderr_excerpt) + len(self.content_excerpt)


class SessionTranscript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    source_path: Path
    input_kind: InputKind
    user_messages: list[str] = Field(default_factory=list)
    assistant_messages: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallEvent] = Field(default_factory=list)
    observations: list[ObservationEvent] = Field(default_factory=list)
    final_answer: str = ""

    @field_validator("final_answer")
    @classmethod
    def bound_final_answer(cls, value: str) -> str:
        return compact_text(value, max_chars=6000)


class AnalysisFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    severity: FindingSeverity = "warning"
    summary: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class SessionAnalysisReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    source_path: Path
    input_kind: InputKind
    user_messages: list[str] = Field(default_factory=list)
    final_answer_excerpt: str = ""
    tool_calls: list[ToolCallEvent] = Field(default_factory=list)
    observations: list[ObservationEvent] = Field(default_factory=list)
    expected_tools: list[AnalysisFinding] = Field(default_factory=list)
    missing_tools: list[AnalysisFinding] = Field(default_factory=list)
    repeated_tools: list[AnalysisFinding] = Field(default_factory=list)
    failed_tools: list[AnalysisFinding] = Field(default_factory=list)
    oversized_outputs: list[AnalysisFinding] = Field(default_factory=list)
    unsupported_claims: list[AnalysisFinding] = Field(default_factory=list)
    risk_events: list[AnalysisFinding] = Field(default_factory=list)
    root_causes: list[AnalysisFinding] = Field(default_factory=list)
    recommendations: list[AnalysisFinding] = Field(default_factory=list)
    confidence: str = "medium"

    @computed_field
    @property
    def observed_tools(self) -> list[str]:
        return sorted(
            {call.tool_name for call in self.tool_calls}
            | {obs.tool_name for obs in self.observations}
        )
