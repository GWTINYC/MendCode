from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.task import TaskType

EvalStatus = Literal["completed", "failed"]
EvalStep = Literal["bootstrap", "locate", "inspect", "patch", "verify", "summarize"]


class BatchEvalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    task_type: TaskType
    task_file: str
    status: EvalStatus
    current_step: EvalStep
    summary: str
    passed_count: int
    failed_count: int
    applied_patch: bool
    tool_results: list[dict[str, Any]] = Field(default_factory=list)
    trace_path: str
    workspace_path: str | None = None


class BatchEvalSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_count: int
    completed_count: int
    failed_count: int
    output_dir: str
    summary_json_path: str
    summary_md_path: str
    results: list[BatchEvalResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_counts(self) -> "BatchEvalSummary":
        if self.task_count != len(self.results):
            raise ValueError("task_count must match number of results")
        if self.completed_count + self.failed_count != self.task_count:
            raise ValueError("completed_count plus failed_count must match task_count")
        return self
