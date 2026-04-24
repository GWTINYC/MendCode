from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.run_state import RunState
from app.schemas.task import TaskType

EvalStatus = RunState.model_fields["status"].annotation
EvalStep = RunState.model_fields["current_step"].annotation


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

    @model_validator(mode="after")
    def validate_status(self) -> "BatchEvalResult":
        if self.status == "running":
            raise ValueError("status must be completed or failed")
        return self


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
    def validate_counts(self) -> "BatchEvalSummary":
        if self.task_count != len(self.results):
            raise ValueError("task_count must match number of results")
        completed_results = sum(1 for result in self.results if result.status == "completed")
        failed_results = sum(1 for result in self.results if result.status == "failed")
        if self.completed_count != completed_results:
            raise ValueError("completed_count must match completed results")
        if self.failed_count != failed_results:
            raise ValueError("failed_count must match failed results")
        if self.completed_count + self.failed_count != self.task_count:
            raise ValueError("completed_count plus failed_count must match task_count")
        return self
